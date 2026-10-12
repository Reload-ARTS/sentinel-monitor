"""
Pruebas Unitarias para el Motor de Chequeo de Infraestructura.
"""

from unittest.mock import patch, MagicMock
import pytest
import requests
from src.checker import ServiceChecker, HealthCheckResult


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    """Incluso un mock omitido debe fallar antes de contactar la red."""
    import socket

    def forbidden(*args, **kwargs):
        pytest.fail("Solicitud de red inesperada")

    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


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


@pytest.mark.parametrize("mode", ["import", "script", "module"])
@pytest.mark.parametrize("valid", [False, True])
def test_entry_modes_validate_before_network(tmp_path, monkeypatch, capsys, caplog, mode, valid):
    """Ejecuta entradas reales con archivo temporal y GET simulado."""
    import json
    import runpy
    import sys
    from pathlib import Path
    from src import checker

    script = Path(checker.__file__).resolve()
    (tmp_path / "config").mkdir()
    config = {"settings": {"timeout_seconds": 2, "max_acceptable_latency_ms": 1000},
              "targets": [{"name": "Primero", "url": "http://localhost/health"},
                          {"name": "Segundo", "url": "http://localhost/other", "expected_status": 204}]}
    if not valid:
        config["targets"][1]["url"] = "https://user:SECRET@example.test/"
    (tmp_path / "config" / "targets.json").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    # Reproduce el sys.path de python src/checker.py sin crear un proceso de red.
    if mode == "script":
        monkeypatch.syspath_prepend(str(script.parent))
    with patch("requests.get") as get, patch("requests.post", side_effect=AssertionError("POST inesperado")) as post:
        if valid:
            get.side_effect = [MagicMock(status_code=200), MagicMock(status_code=204)]
        else:
            get.side_effect = AssertionError("GET inesperado")
        if mode == "import":
            code = checker.main()
        else:
            with pytest.raises(SystemExit) as exit_info:
                if mode == "script":
                    runpy.run_path(str(script), run_name="__main__")
                else:
                    # Evita ejecutar dos veces un módulo previamente importado.
                    monkeypatch.delitem(sys.modules, "src.checker")
                    runpy.run_module("src.checker", run_name="__main__")
            code = exit_info.value.code
        out = capsys.readouterr()
        post.assert_not_called()
        if valid:
            assert code == 0
            assert get.call_count == 2
            get.assert_any_call("http://localhost/health", timeout=2, headers={"User-Agent": "SentinelMonitor/1.0"})
            results = json.loads(out.out.split("--- RESUMEN DE RESULTADOS DE PRUEBA ---\n", 1)[1])
            assert [result["is_up"] for result in results] == [True, True]
            assert [result["status_code"] for result in results] == [200, 204]
        else:
            assert code == 2
            get.assert_not_called()
            assert out.out == ""
            assert "targets[1].url" in caplog.text
            assert "SECRET" not in caplog.text + out.out + out.err


def test_missing_configuration_returns_two(tmp_path, monkeypatch, caplog):
    from src.checker import main

    monkeypatch.chdir(tmp_path)
    assert main() == 2
    assert "no se pudo leer" in caplog.text


def test_unexpected_loader_error_is_not_hidden(monkeypatch):
    from src import checker

    def broken():
        raise RuntimeError("Defecto interno")

    monkeypatch.setattr(checker, "load_targets_from_config", broken)
    with pytest.raises(RuntimeError, match="Defecto interno"):
        checker.main()


def test_numeric_parsing_failure_returns_two_without_network(tmp_path, monkeypatch, caplog, capsys):
    from src.checker import main

    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "targets.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    def failed_parsing(*args, **kwargs):
        raise ValueError("SECRET 999999")

    monkeypatch.setattr("src.config.json.load", failed_parsing)
    with patch("requests.get", side_effect=AssertionError("GET inesperado")) as get, \
            patch("requests.post", side_effect=AssertionError("POST inesperado")) as post:
        assert main() == 2
        get.assert_not_called()
        post.assert_not_called()
    output = capsys.readouterr()
    assert output.out == ""
    assert "valor numérico" in caplog.text
    assert "SECRET" not in caplog.text + output.out + output.err
    assert "999999" not in caplog.text + output.out + output.err
