"""
Módulo de Notificaciones y Alertas en Tiempo Real.
Maneja el envío de alertas mediante Webhooks (Discord/Slack/Teams).
"""

import os
import logging
from typing import Dict, Any, Optional
import requests
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
load_dotenv()

logger = logging.getLogger("SentinelNotifier")


class AlertNotifier:
    """Clase para la gestión y envío de alertas ante fallas o degradación de servicio."""

    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or os.getenv("WEBHOOK_URL")
        self.enabled = os.getenv("ENABLE_ALERTS", "true").lower() == "true"

    def send_alert(self, target_name: str, url: str, reason: str, details: Optional[str] = None) -> bool:
        """
        Envía un mensaje de alerta enriquecido a través del Webhook configurado.
        """
        if not self.enabled:
            logger.info("Alertas desactivadas por configuración (ENABLE_ALERTS=false).")
            return False

        # Formato de payload compatible con Discord Webhooks
        payload = {
            "username": "Sentinel Bot",
            "avatar_url": "https://cdn-icons-png.flaticon.com/512/584/584052.png",
            "embeds": [
                {
                    "title": f"🚨 ALERTA DE INFRAESTRUCTURA: {target_name}",
                    "color": 15158332,  # Rojo de emergencia (Hex #E74C3C)
                    "fields": [
                        {"name": "Servicio", "value": target_name, "inline": True},
                        {"name": "URL", "value": url, "inline": True},
                        {"name": "Causa", "value": reason, "inline": False},
                        {"name": "Detalles Técnicos", "value": details or "N/A", "inline": False}
                    ],
                    "footer": {"text": "Sentinel Infrastructure Health Monitor"}
                }
            ]
        }

        if not self.webhook_url or "TU_WEBHOOK_AQUI" in self.webhook_url:
            logger.warning(
                f"[MODO SIMULACIÓN] Alerta no enviada por Webhook no configurado.\n"
                f"-> Servicio: {target_name} | Causa: {reason}"
            )
            return False

        try:
            response = requests.post(self.webhook_url, json=payload, timeout=5)
            if response.status_code in (200, 204):
                logger.info(f"Alerta enviada exitosamente para {target_name}")
                return True
            else:
                logger.error(f"Error al enviar alerta por Webhook. HTTP {response.status_code}")
                return False

        except requests.exceptions.RequestException as exc:
            logger.error(f"Fallo de conexión al enviar alerta vía Webhook: {exc}")
            return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("Iniciando prueba manual del Módulo de Notificaciones...")

    notifier = AlertNotifier()
    
    # Prueba de alerta simulada
    notifier.send_alert(
        target_name="Servidor de Base de Datos",
        url="https://db.internal.example.com",
        reason="Fallo de conexión HTTP 500",
        details="Timeout al intentar establecer conexión con el puerto 5432"
    )