"""
Pruebas Unitarias para el Motor de Chequeo de Infraestructura.
"""

from unittest.mock import patch, MagicMock
import pytest
import requests
from src.checker import ServiceChecker, HealthCheckResult, classify_http_status


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
    checker = ServiceChecker(timeout_seconds=5, max_acceptable_latency_ms=1000)
    
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
    checker = ServiceChecker(timeout_seconds=2, max_acceptable_latency_ms=1000)

    with patch("requests.get", side_effect=requests.exceptions.Timeout):
        result = checker.check_target("Timeout Site", "https://example.com", 200)

        assert result.is_up is False
        assert result.status == "DOWN"
        assert result.status_code is None
        assert "Timeout superado" in result.error_message


def test_health_check_connection_error():
    """Prueba el manejo adecuado cuando falla la conexión de red/DNS."""
    checker = ServiceChecker(timeout_seconds=2, max_acceptable_latency_ms=1000)

    with patch("requests.get", side_effect=requests.exceptions.ConnectionError):
        result = checker.check_target("Down Site", "https://invalid-domain.test", 200)

        assert result.is_up is False
        assert result.status == "DOWN"
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
            get.assert_any_call("http://localhost/health", timeout=2, headers={"User-Agent": "SentinelMonitor/1.0"}, allow_redirects=False)
            report = json.loads(out.out)
            assert report["exit_code"] == code
            assert report["execution_status"] == "completed"
            assert [result["status"] for result in report["targets"]] == ["HEALTHY", "HEALTHY"]
            assert [result["http_status"] for result in report["targets"]] == [200, 204]
        else:
            assert code == 2
            get.assert_not_called()
            assert json.loads(out.out)["execution_status"] == "not_started"
            assert json.loads(out.out)["exit_code"] == 2
            assert "targets[1].url" in out.err
            assert "SECRET" not in caplog.text + out.out + out.err


def test_missing_configuration_returns_two(tmp_path, monkeypatch, capsys):
    from src.checker import main

    monkeypatch.chdir(tmp_path)
    assert main() == 2
    assert "no se pudo leer" in capsys.readouterr().err


def test_unexpected_loader_error_is_reported_safely(monkeypatch, capsys):
    from src import checker

    def broken():
        raise RuntimeError("Defecto interno")

    monkeypatch.setattr(checker, "load_targets_from_config", broken)
    assert checker.main() == 3
    output = capsys.readouterr()
    report = __import__("json").loads(output.out)
    assert report["execution_status"] == "not_started"
    assert report["summary"]["total"] is None
    assert report["errors"][0]["type"] == "internal_error"
    assert "Defecto interno" not in output.out + output.err


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
    assert __import__("json").loads(output.out)["exit_code"] == 2
    assert "valor numérico" in output.err
    assert "SECRET" not in caplog.text + output.out + output.err
    assert "999999" not in caplog.text + output.out + output.err


@pytest.mark.parametrize("observed, expected, latency, threshold, status", [
    (200, 200, 999, 1000, "HEALTHY"),
    (200, 200, 1000, 1000, "HEALTHY"),
    (200, 200, 1001, 1000, "DEGRADED"),
    (200, 200, 1000.004, 1000, "DEGRADED"),
    (503, 200, 1, 1000, "DOWN"),
    (503, 200, 2000, 1000, "DOWN"),
    (302, 200, 1, 1000, "DOWN"),
    (301, 301, 1000, 1000, "HEALTHY"),
    (301, 301, 1001, 1000, "DEGRADED"),
    (204, 204, 50, 50, "HEALTHY"),
])
def test_pure_http_classification(observed, expected, latency, threshold, status):
    assert classify_http_status(observed, expected, latency, threshold) == status


@pytest.mark.parametrize("observed, expected, seconds, status", [
    (200, 200, 0.5, "HEALTHY"),
    (200, 200, 1, "HEALTHY"),
    (200, 200, 1.5, "DEGRADED"),
    (200, 200, 1.000004, "DEGRADED"),
    (503, 200, 0.001, "DOWN"),
    (503, 200, 2, "DOWN"),
    (302, 200, 0.001, "DOWN"),
    (301, 301, 0.5, "HEALTHY"),
    (301, 301, 1.5, "DEGRADED"),
])
def test_http_result_with_controlled_clock(observed, expected, seconds, status):
    checker = ServiceChecker(timeout_seconds=3, max_acceptable_latency_ms=1000)
    with patch("requests.get", return_value=MagicMock(status_code=observed)) as get, \
            patch("time.perf_counter", side_effect=[0, seconds]):
        result = checker.check_target("Servicio", "http://localhost/health", expected)
    assert result.status == status
    assert result.is_up is (status != "DOWN")
    assert result.response_time_ms == seconds * 1000
    assert result.status_code == observed
    assert (result.error_message is None) is (status != "DOWN")
    get.assert_called_once_with("http://localhost/health", timeout=3,
                                headers={"User-Agent": "SentinelMonitor/1.0"}, allow_redirects=False)
    if seconds == 1.000004:
        assert result.response_time_ms > 1000
        assert round(result.response_time_ms, 2) == 1000


@pytest.mark.parametrize("error", [requests.exceptions.Timeout, requests.exceptions.ConnectionError])
def test_transport_down_preserves_duration(error):
    checker = ServiceChecker(max_acceptable_latency_ms=50)
    with patch("requests.get", side_effect=error), patch("time.perf_counter", side_effect=[0, 1.000004]):
        result = checker.check_target("Servicio", "http://localhost")
    assert result.status == "DOWN"
    assert result.is_up is False
    assert result.status_code is None
    assert result.response_time_ms == 1.000004 * 1000
    assert result.error_message


def test_threshold_is_required():
    with pytest.raises(TypeError):
        ServiceChecker()


def test_unexpected_check_error_is_not_down():
    checker = ServiceChecker(max_acceptable_latency_ms=1000)
    with patch("requests.get", side_effect=RuntimeError("Defecto interno")):
        with pytest.raises(RuntimeError, match="Defecto interno"):
            checker.check_target("Servicio", "http://localhost")


def test_main_uses_config_threshold_and_serializes_status(tmp_path, monkeypatch, capsys):
    import json
    from src.checker import main

    (tmp_path / "config").mkdir()
    config = {"settings": {"timeout_seconds": 2, "max_acceptable_latency_ms": 50},
              "targets": [{"name": "A", "url": "http://localhost/a"},
                          {"name": "B", "url": "http://localhost/b"},
                          {"name": "C", "url": "http://localhost/c"}]}
    (tmp_path / "config" / "targets.json").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with patch("requests.get", side_effect=[MagicMock(status_code=200), MagicMock(status_code=200), MagicMock(status_code=503)]), \
            patch("time.perf_counter", side_effect=[0, 0.025, 0, 0.075, 0, 0.1]), \
            patch("requests.post", side_effect=AssertionError("POST inesperado")) as post:
        assert main() == 1
        post.assert_not_called()
    output = capsys.readouterr().out
    report = json.loads(output)
    results = report["targets"]
    assert [result["status"] for result in results] == ["HEALTHY", "DEGRADED", "DOWN"]
    assert [result["notification"] for result in results] == ["not_required", "not_required", "disabled"]
    assert results[1]["latency_ms"] == 75
    assert set(results[0]) == {"name", "status", "http_status", "latency_ms", "notification"}
