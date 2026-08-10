"""
Pruebas Unitarias para el Motor de Chequeo de Infraestructura.
"""

from unittest.mock import patch, MagicMock
import pytest
import requests
from src.checker import ServiceChecker, HealthCheckResult


def test_health_check_success():
    """Prueba un chequeo exitoso HTTP 200."""
    checker = ServiceChecker(timeout_seconds=5)
    
    with patch("requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        result = checker.check_target("Test Site", "https://example.com", 200)

        assert isinstance(result, HealthCheckResult)
        assert result.is_up is True
        assert result.status_code == 200
        assert result.error_message is None


def test_health_check_timeout():
    """Prueba el manejo adecuado cuando ocurre un Timeout."""
    checker = ServiceChecker(timeout_seconds=2)

    with patch("requests.get", side_effect=requests.exceptions.Timeout):
        result = checker.check_target("Timeout Site", "https://example.com", 200)

        assert result.is_up is False
        assert result.status_code is None
        assert "Timeout superado" in result.error_message


def test_health_check_connection_error():
    """Prueba el manejo adecuado cuando falla la conexión de red/DNS."""
    checker = ServiceChecker(timeout_seconds=2)

    with patch("requests.get", side_effect=requests.exceptions.ConnectionError):
        result = checker.check_target("Down Site", "https://invalid-domain.test", 200)

        assert result.is_up is False
        assert result.status_code is None
        assert "Error de red/DNS" in result.error_message