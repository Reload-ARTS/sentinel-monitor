"""
Módulo de Verificación de Endpoints HTTP/HTTPS.
Proporciona la funcionalidad para evaluar disponibilidad y rendimiento de servicios web.
"""

from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
import json
import logging
import time
import requests

# Configuración básica de Logging estructurado
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("SentinelChecker")


@dataclass
class HealthCheckResult:
    """Estructura de datos fuertemente tipada para almacenar el resultado de un chequeo."""
    target_name: str
    url: str
    is_up: bool
    status_code: Optional[int]
    response_time_ms: float
    error_message: Optional[str] = None


class ServiceChecker:
    """Clase encargada de ejecutar auditorías de disponibilidad sobre lista de objetivos."""

    def __init__(self, timeout_seconds: int = 5):
        self.timeout = timeout_seconds

    def check_target(self, name: str, url: str, expected_status: int = 200) -> HealthCheckResult:
        """
        Ejecuta una petición HTTP GET a un objetivo y evalúa su estado de salud.
        """
        start_time = time.perf_counter()
        
        try:
            response = requests.get(
                url, 
                timeout=self.timeout,
                headers={"User-Agent": "SentinelMonitor/1.0"}
            )
            elapsed_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
            
            is_up = (response.status_code == expected_status)
            error_msg = None if is_up else f"Status Code {response.status_code} != {expected_status}"
            
            logger.info(f"VERIFICADO: {name} ({url}) - Code: {response.status_code} - {elapsed_time_ms}ms")
            
            return HealthCheckResult(
                target_name=name,
                url=url,
                is_up=is_up,
                status_code=response.status_code,
                response_time_ms=elapsed_time_ms,
                error_message=error_msg
            )

        except requests.exceptions.Timeout:
            elapsed_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.warning(f"TIMEOUT: {name} ({url}) superó el tiempo límite de {self.timeout}s")
            return HealthCheckResult(
                target_name=name,
                url=url,
                is_up=False,
                status_code=None,
                response_time_ms=elapsed_time_ms,
                error_message=f"Timeout superado ({self.timeout}s)"
            )

        except requests.exceptions.RequestException as exc:
            elapsed_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.error(f"FALLO DE CONEXIÓN: {name} ({url}) - Error: {str(exc)}")
            return HealthCheckResult(
                target_name=name,
                url=url,
                is_up=False,
                status_code=None,
                response_time_ms=elapsed_time_ms,
                error_message=f"Error de red/DNS: {type(exc).__name__}"
            )


def load_targets_from_config(config_path: str = "config/targets.json") -> Dict[str, Any]:
    """Carga la configuración de objetivos desde un archivo JSON."""
    with open(config_path, "r", encoding="utf-8") as file:
        return json.load(file)


if __name__ == "__main__":
    logger.info("Iniciando prueba manual del Motor de Chequeo...")
    
    config = load_targets_from_config()
    timeout = config.get("settings", {}).get("timeout_seconds", 5)
    
    checker = ServiceChecker(timeout_seconds=timeout)
    results = []
    
    for target in config.get("targets", []):
        res = checker.check_target(
            name=target["name"], 
            url=target["url"], 
            expected_status=target.get("expected_status", 200)
        )
        results.append(asdict(res))
        
    print("\n--- RESUMEN DE RESULTADOS DE PRUEBA ---")
    print(json.dumps(results, indent=2))