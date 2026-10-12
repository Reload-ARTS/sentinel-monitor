"""Validación local y envío Discord, sin efectos secundarios al importar."""

import re
import logging
from urllib.parse import urlsplit

import requests

if __package__:
    from .config import ConfigurationError
else:
    from config import ConfigurationError


def validate_alert_settings(environ):
    """Interpreta las variables existentes sin red ni diagnósticos sensibles."""
    flag = environ.get("ENABLE_ALERTS", "true").strip().lower()
    if flag not in ("true", "false"):
        raise ConfigurationError("ENABLE_ALERTS: debe ser true o false.")
    if flag == "false":
        return False, None
    webhook = environ.get("WEBHOOK_URL", "")
    try:
        if not webhook or any(ord(c) < 33 or ord(c) >= 127 for c in webhook):
            raise ValueError
        parsed = urlsplit(webhook)
        if (parsed.scheme != "https" or parsed.hostname != "discord.com"
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443) or parsed.netloc.endswith(":")
                or parsed.query or parsed.fragment or "TU_WEBHOOK_AQUI" in webhook
                or not re.fullmatch(r"/api(?:/v[0-9]+)?/webhooks/[0-9]+/[A-Za-z0-9_-]+", parsed.path)):
            raise ValueError
    except ValueError:
        raise ConfigurationError("WEBHOOK_URL: se requiere un webhook Discord HTTPS válido con alertas habilitadas.") from None
    return True, webhook


class AlertNotifier:
    """Envía datos preparados sin leer implícitamente variables de entorno."""

    def __init__(self, webhook_url):
        self.webhook_url = webhook_url
        self.attempt_started = False

    def prepare_alert(self, name, http_status):
        """Payload limitado a la identificación segura y causa HTTP de la caída."""
        reason = f"HTTP inesperado: {http_status}" if http_status is not None else "Timeout o fallo de transporte HTTP"
        return {
            "username": "Sentinel Bot",
            "allowed_mentions": {"parse": []},
            "embeds": [{"title": "Alerta de infraestructura", "color": 15158332,
                        "fields": [{"name": "Servicio", "value": name[:1024], "inline": False},
                                   {"name": "Causa", "value": reason, "inline": False}]}],
        }

    def send_alert(self, payload):
        """Devuelve aceptación/fallo previsto; errores internos llegan al coordinador."""
        # urllib3 puede registrar la ruta (que contiene el token) en modo debug.
        transport_loggers = [logging.getLogger(name) for name in ("urllib3.connectionpool", "urllib3.util.retry")]
        previous = [(item, item.disabled) for item in transport_loggers]
        for item in transport_loggers:
            item.disabled = True
        try:
            self.attempt_started = True
            response = requests.post(self.webhook_url, json=payload, timeout=5, allow_redirects=False)
            try:
                return "accepted" if response.status_code in (200, 204) else "failed"
            finally:
                response.close()
        except requests.exceptions.RequestException:
            return "failed"
        finally:
            for item, disabled in previous:
                item.disabled = disabled
