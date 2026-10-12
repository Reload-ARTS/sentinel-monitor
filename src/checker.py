"""
Módulo de Verificación de Endpoints HTTP/HTTPS.
Proporciona la funcionalidad para evaluar disponibilidad y rendimiento de servicios web.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional, Literal
import json
import logging
import math
import os
from pathlib import Path
import sys
import time
import requests

if __package__:
    from .config import ConfigurationError, load_config
    from .notifier import AlertNotifier, validate_alert_settings
else:
    from config import ConfigurationError, load_config
    from notifier import AlertNotifier, validate_alert_settings

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
            
            logger.info("Comprobación %s: HTTP %s, %.2f ms", status, response.status_code, elapsed_time_ms)
            
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
            logger.warning("Timeout durante la comprobación HTTP.")
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
            logger.error("Fallo de transporte durante la comprobación HTTP.")
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


def _report(execution_status, targets, not_checked, errors, total, exit_code):
    """Construye el resumen desde las listas, sin contadores independientes."""
    return {
        "schema_version": "1",
        "execution_status": execution_status,
        "summary": {
            "total": total,
            "checked": len(targets),
            "healthy": sum(t["status"] == "HEALTHY" for t in targets),
            "degraded": sum(t["status"] == "DEGRADED" for t in targets),
            "down": sum(t["status"] == "DOWN" for t in targets),
            "not_checked": len(not_checked),
        },
        "targets": targets,
        "not_checked": not_checked,
        "errors": errors,
        "exit_code": exit_code,
    }


def _target_identity(target, index):
    """No permite URLs o controles en identificadores públicos de resultados."""
    name = target["name"]
    if "://" in name or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in name):
        name = f"Objetivo {index + 1}"
    return {"name": name}


def _target_result(result, target, index):
    # Una interrupción o resultado inválido no constituye evidencia de DOWN.
    if result.status not in ("HEALTHY", "DEGRADED", "DOWN"):
        raise ValueError("Resultado de salud inválido")
    if (isinstance(result.response_time_ms, bool)
            or not isinstance(result.response_time_ms, (int, float))
            or not math.isfinite(result.response_time_ms) or result.response_time_ms < 0):
        raise ValueError("Duración inválida")
    code = result.status_code
    if code is not None and (isinstance(code, bool) or not isinstance(code, int) or not 100 <= code <= 599):
        raise ValueError("Código HTTP inválido")
    if result.status != "DOWN" and code is None:
        raise ValueError("Respuesta HTTP ausente")
    return {**_target_identity(target, index), "status": result.status,
            "http_status": code, "latency_ms": result.response_time_ms,
            "notification": "disabled" if result.status == "DOWN" else "not_required"}


def run_monitoring() -> Dict[str, Any]:
    """Valida todas las fuentes antes de comprobar y notifica únicamente DOWN."""
    try:
        config = load_targets_from_config()
        targets = config["targets"]
        if not isinstance(targets, list) or not targets:
            raise ValueError("Contrato del cargador incumplido")
        # Establecer identidades seguras antes de poder informar objetivos pendientes.
        identities = [_target_identity(target, index) for index, target in enumerate(targets)]
        # Carga explícita en la entrada; importar módulos no lee archivos .env.
        from dotenv import load_dotenv
        try:
            load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
        except (OSError, UnicodeError):
            raise ConfigurationError("Entorno: no se pudo leer la configuración local de alertas.") from None
        alerts_enabled, webhook = validate_alert_settings(os.environ)
    except ConfigurationError as exc:
        logger.error("Configuración inválida: %s", exc)
        return _report("not_started", [], [],
                       [{"type": "configuration_error", "message": "La configuración no es válida o no pudo leerse."}], None, 2)
    except Exception:
        logger.error("Error interno al preparar la ejecución.")
        return _report("not_started", [], [],
                       [{"type": "internal_error", "message": "No fue posible preparar las comprobaciones."}], None, 3)

    results = []
    try:
        settings = config["settings"]
        checker = ServiceChecker(timeout_seconds=settings["timeout_seconds"],
                                 max_acceptable_latency_ms=settings["max_acceptable_latency_ms"])
        notifier = AlertNotifier(webhook) if alerts_enabled else None
        for index, target in enumerate(targets):
            result = checker.check_target(target["name"], target["url"], target["expected_status"])
            entry = _target_result(result, target, index)
            results.append(entry)
            if entry["status"] == "DOWN" and alerts_enabled:
                notifier.attempt_started = False
                entry["notification"] = "not_attempted"
                payload = notifier.prepare_alert(entry["name"], entry["http_status"])
                try:
                    outcome = notifier.send_alert(payload)
                    if outcome not in ("accepted", "failed"):
                        raise ValueError("Resultado de notificación inválido")
                    entry["notification"] = outcome
                except Exception:
                    if notifier.attempt_started:
                        entry["notification"] = "failed"
                    raise
                logger.info("Notificación Discord: %s", entry["notification"])
    except Exception:
        # Frontera de ejecución: conservar evidencia, no ocultar el error como DOWN.
        logger.error("Error interno: no fue posible completar las comprobaciones.")
        remaining = identities[len(results):]
        return _report("incomplete", results, remaining,
                       [{"type": "internal_error", "message": "No fue posible completar las comprobaciones."}], len(targets), 3)
    code = 1 if any(t["status"] == "DOWN" for t in results) else 0
    return _report("completed", results, [], [], len(targets), code)


def main() -> int:
    """Emite exactamente un documento JSON; diagnósticos exclusivamente en stderr."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    # dotenv puede emitir avisos de parsing; tampoco deben llegar a stdout.
    managed_loggers = (logger, logging.getLogger("dotenv.main"))
    previous = [(item, item.level, item.propagate, item.handlers[:]) for item in managed_loggers]
    for item in managed_loggers:
        item.handlers = [handler]
        item.setLevel(logging.INFO)
        item.propagate = False
    try:
        report = run_monitoring()
        print(json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False))
        return report["exit_code"]
    finally:
        for item, level, propagation, handlers in previous:
            item.handlers = handlers
            item.setLevel(level)
            item.propagate = propagation
        handler.close()


if __name__ == "__main__":
    raise SystemExit(main())
