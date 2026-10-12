"""
Módulo de Verificación de Endpoints HTTP/HTTPS.
Proporciona la funcionalidad para evaluar disponibilidad y rendimiento de servicios web.
"""

from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional, Literal
import json
import logging
import time
import requests

if __package__:
    from .config import ConfigurationError, load_config
else:
    from config import ConfigurationError, load_config

# Configuración básica de Logging estructurado
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("SentinelChecker")

HealthStatus = Literal["HEALTHY", "DEGRADED", "DOWN"]


def classify_http_status(status_code: int, expected_status: int,
                         response_time_ms: float, max_acceptable_latency_ms: float) -> HealthStatus:
    """Clasifica usando la duración sin redondear; HTTP inesperado prevalece."""
    if status_code != expected_status:
        return "DOWN"
    return "DEGRADED" if response_time_ms > max_acceptable_latency_ms else "HEALTHY"


@dataclass
class HealthCheckResult:
    """Estructura de datos fuertemente tipada para almacenar el resultado de un chequeo."""
    target_name: str
    url: str
    status: HealthStatus
    status_code: Optional[int]
    response_time_ms: float
    error_message: Optional[str] = None

    @property
    def is_up(self) -> bool:
        """La degradación conserva disponibilidad; DOWN indica caída."""
        return self.status in ("HEALTHY", "DEGRADED")


class ServiceChecker:
    """Clase encargada de ejecutar auditorías de disponibilidad sobre lista de objetivos."""

    def __init__(self, timeout_seconds: int = 5, *, max_acceptable_latency_ms: float):
        self.timeout = timeout_seconds
        self.max_acceptable_latency_ms = max_acceptable_latency_ms

    def check_target(self, name: str, url: str, expected_status: int = 200) -> HealthCheckResult:
        """
        Ejecuta una petición HTTP GET a un objetivo y evalúa su estado de salud.
        """
        start_time = time.perf_counter()
        
        try:
            response = requests.get(
                url, 
                timeout=self.timeout,
                headers={"User-Agent": "SentinelMonitor/1.0"},
                allow_redirects=False,
            )
            elapsed_time_ms = (time.perf_counter() - start_time) * 1000
            
            status = classify_http_status(response.status_code, expected_status,
                                          elapsed_time_ms, self.max_acceptable_latency_ms)
            error_msg = None if status != "DOWN" else f"Status Code {response.status_code} != {expected_status}"
            
            logger.info(f"VERIFICADO: {name} ({url}) - Code: {response.status_code} - {elapsed_time_ms:.2f}ms")
            
            return HealthCheckResult(
                target_name=name,
                url=url,
                status=status,
                status_code=response.status_code,
                response_time_ms=elapsed_time_ms,
                error_message=error_msg
            )

        except requests.exceptions.Timeout:
            elapsed_time_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(f"TIMEOUT: {name} ({url}) superó el tiempo límite de {self.timeout}s")
            return HealthCheckResult(
                target_name=name,
                url=url,
                status="DOWN",
                status_code=None,
                response_time_ms=elapsed_time_ms,
                error_message=f"Timeout superado ({self.timeout}s)"
            )

        except requests.exceptions.RequestException as exc:
            elapsed_time_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"FALLO DE CONEXIÓN: {name} ({url}) - Error: {str(exc)}")
            return HealthCheckResult(
                target_name=name,
                url=url,
                status="DOWN",
                status_code=None,
                response_time_ms=elapsed_time_ms,
                error_message=f"Error de red/DNS: {type(exc).__name__}"
            )


def load_targets_from_config(config_path: str = "config/targets.json") -> Dict[str, Any]:
    """Carga la configuración de objetivos desde un archivo JSON."""
    return load_config(config_path)


def main() -> int:
    """Ejecuta una pasada solo después de validar toda la configuración JSON."""
    logger.info("Iniciando prueba manual del Motor de Chequeo...")
    
    try:
        config = load_targets_from_config()
    except ConfigurationError as exc:
        logger.error("Configuración inválida: %s", exc)
        return 2
    settings = config["settings"]
    
    checker = ServiceChecker(timeout_seconds=settings["timeout_seconds"],
                             max_acceptable_latency_ms=settings["max_acceptable_latency_ms"])
    results = []
    
    for target in config.get("targets", []):
        res = checker.check_target(
            name=target["name"], 
            url=target["url"], 
            expected_status=target.get("expected_status", 200)
        )
        results.append({**asdict(res), "is_up": res.is_up})
        
    print("\n--- RESUMEN DE RESULTADOS DE PRUEBA ---")
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
