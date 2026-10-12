"""Contrato de ejecución aislado de red, notifier y configuración del entorno."""

import json
import socket
from unittest.mock import patch, MagicMock

import pytest
import requests

from src import checker


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setenv("ENABLE_ALERTS", "false")
    monkeypatch.setattr("dotenv.load_dotenv", lambda **kwargs: False)
    def forbidden(*args, **kwargs):
        pytest.fail("Red inesperada")
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(requests, "post", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    config = {"settings": {"timeout_seconds": 2, "max_acceptable_latency_ms": 1000},
              "targets": [{"name": name, "url": "http://localhost/" + name}
                          for name in ("A", "B", "C")]}
    path = tmp_path / "config" / "targets.json"
    path.parent.mkdir()
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return path


def assert_report(report, code):
    assert set(report) == {"schema_version", "execution_status", "summary", "targets", "not_checked", "errors", "exit_code"}
    assert report["schema_version"] == "1"
    assert report["exit_code"] == code
    summary = report["summary"]
    assert summary["checked"] == len(report["targets"])
    assert summary["not_checked"] == len(report["not_checked"])
    assert summary["checked"] == summary["healthy"] + summary["degraded"] + summary["down"]
    if summary["total"] is not None:
        assert summary["total"] == summary["checked"] + summary["not_checked"]


@pytest.mark.parametrize("statuses, durations, code, expected", [
    ([200, 200, 200], [0.1, 0.1, 0.1], 0, ["HEALTHY"] * 3),
    ([200, 200, 200], [1.000004, 2, 0.1], 0, ["DEGRADED", "DEGRADED", "HEALTHY"]),
    ([200, 503, 200], [0.1, 0.1, 0.1], 1, ["HEALTHY", "DOWN", "HEALTHY"]),
    ([200, 200, 503], [0.1, 1.000004, 2], 1, ["HEALTHY", "DEGRADED", "DOWN"]),
])
def test_completed_execution(config_file, capsys, statuses, durations, code, expected):
    with patch("requests.get", side_effect=[MagicMock(status_code=s) for s in statuses]) as get, \
            patch("time.perf_counter", side_effect=[v for d in durations for v in (0, d)]):
        actual = checker.main()
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert actual == code
    assert_report(report, code)
    assert report["execution_status"] == "completed"
    assert report["errors"] == []
    assert report["not_checked"] == []
    assert [t["status"] for t in report["targets"]] == expected
    assert [t["notification"] for t in report["targets"]] == ["disabled" if s == "DOWN" else "not_required" for s in expected]
    assert [t["name"] for t in report["targets"]] == ["A", "B", "C"]
    assert "Comprobación" in output.err
    for call in get.call_args_list:
        assert call.kwargs["allow_redirects"] is False


@pytest.mark.parametrize("count, previous_status", [(0, "HEALTHY"), (1, "HEALTHY"), (2, "DOWN")])
def test_partial_results(config_file, capsys, count, previous_status):
    results = [checker.HealthCheckResult(n, "http://localhost", previous_status,
                                        200 if previous_status == "HEALTHY" else 503, 10)
               for n in ("A", "B")[:count]]
    with patch.object(checker.ServiceChecker, "check_target", side_effect=results + [RuntimeError("SECRET_TOKEN https://private/secret")]) as check:
        assert checker.main() == 3
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert_report(report, 3)
    assert report["execution_status"] == "incomplete"
    assert check.call_count == count + 1
    assert [t["name"] for t in report["targets"]] == ["A", "B", "C"][:count]
    assert report["not_checked"] == [{"name": n} for n in ["A", "B", "C"][count:]]
    assert report["errors"] == [{"type": "internal_error", "message": "No fue posible completar las comprobaciones."}]
    assert "SECRET_TOKEN" not in output.out + output.err
    assert "https://private" not in output.out + output.err


@pytest.mark.parametrize("invalid_result", [None, "bad", checker.HealthCheckResult("A", "", "INVALID", 200, 1),
                                          checker.HealthCheckResult("A", "", "HEALTHY", 200, float("nan"))])
def test_invalid_result_is_not_a_down(config_file, capsys, invalid_result):
    with patch.object(checker.ServiceChecker, "check_target", return_value=invalid_result) as check:
        assert checker.main() == 3
    report = json.loads(capsys.readouterr().out)
    assert_report(report, 3)
    assert report["targets"] == []
    assert report["summary"]["down"] == 0
    assert len(report["not_checked"]) == 3
    assert check.call_count == 1


def test_config_error_has_unknown_total_and_no_network(config_file, capsys):
    config_file.write_text("{", encoding="utf-8")
    with patch("requests.get", side_effect=AssertionError("GET inesperado")) as get:
        assert checker.main() == 2
        get.assert_not_called()
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert_report(report, 2)
    assert report["execution_status"] == "not_started"
    assert report["summary"]["total"] is None
    assert report["targets"] == report["not_checked"] == []
    assert report["errors"][0]["type"] == "configuration_error"
    assert output.err


@pytest.mark.parametrize("env_enabled", ["true", "false"])
def test_notification_environment_controls_execution(config_file, monkeypatch, capsys, env_enabled):
    monkeypatch.setenv("ENABLE_ALERTS", env_enabled)
    monkeypatch.setenv("WEBHOOK_URL", "SECRET_WEBHOOK")
    with patch("requests.get", return_value=MagicMock(status_code=503)) as get:
        assert checker.main() == (2 if env_enabled == "true" else 1)
    output = capsys.readouterr()
    report = json.loads(output.out)
    if env_enabled == "true":
        assert report["execution_status"] == "not_started"
        get.assert_not_called()
    else:
        assert all(t["notification"] == "disabled" for t in report["targets"])
    assert "SECRET_WEBHOOK" not in output.out + output.err


def test_transport_exception_text_and_sensitive_url_are_not_emitted(config_file, capsys):
    config = json.loads(config_file.read_text(encoding="utf-8"))
    config["targets"][0]["url"] = "https://example.test/private/SECRET_TOKEN?q=SECRET_TOKEN"
    config_file.write_text(json.dumps(config), encoding="utf-8")
    with patch("requests.get", side_effect=requests.exceptions.ConnectionError("SECRET_TOKEN")):
        assert checker.main() == 1
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert_report(report, 1)
    assert all(t["http_status"] is None for t in report["targets"])
    assert "SECRET_TOKEN" not in output.out + output.err


def test_logger_handler_is_removed(config_file, capsys):
    before = list(checker.logger.handlers)
    with patch("requests.get", return_value=MagicMock(status_code=200)):
        checker.main()
        checker.main()
    assert checker.logger.handlers == before
    decoder = json.JSONDecoder()
    output = capsys.readouterr().out
    first, end = decoder.raw_decode(output)
    second = json.loads(output[end:])
    assert first["exit_code"] == second["exit_code"] == 0


@pytest.mark.parametrize("logger_name", [None, "SentinelChecker"])
def test_caller_logging_cannot_contaminate_stdout(config_file, capsys, logger_name):
    import logging
    import sys

    root = logging.getLogger(logger_name)
    handler = logging.StreamHandler(sys.stdout)
    root.addHandler(handler)
    propagation = checker.logger.propagate
    try:
        with patch("requests.get", return_value=MagicMock(status_code=503)):
            assert checker.main() == 1
        output = capsys.readouterr()
        assert json.loads(output.out)["exit_code"] == 1
        assert "Comprobación DOWN" in output.err
        assert checker.logger.propagate == propagation
    finally:
        root.removeHandler(handler)
        handler.close()


def test_checker_initialization_failure_retains_all_pending(config_file, capsys):
    with patch.object(checker, "ServiceChecker", side_effect=RuntimeError("SECRET")):
        assert checker.main() == 3
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert_report(report, 3)
    assert report["execution_status"] == "incomplete"
    assert report["not_checked"] == [{"name": n} for n in ("A", "B", "C")]
    assert "SECRET" not in output.out + output.err


@pytest.mark.parametrize("loaded", [
    {}, {"targets": None}, {"targets": "SECRET_VALUE"},
    {"targets": [None]}, {"targets": [{"name": None}]},
])
def test_loader_structure_failure_is_safe_not_started(loaded, capsys):
    with patch.object(checker, "load_targets_from_config", return_value=loaded), \
            patch("requests.get", side_effect=AssertionError("GET inesperado")) as get, \
            patch("requests.post", side_effect=AssertionError("POST inesperado")) as post:
        assert checker.main() == 3
        get.assert_not_called()
        post.assert_not_called()
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert_report(report, 3)
    assert report["execution_status"] == "not_started"
    assert report["summary"]["total"] is None
    assert report["targets"] == report["not_checked"] == []
    assert report["errors"] == [{"type": "internal_error", "message": "No fue posible preparar las comprobaciones."}]
    assert "Error interno al preparar" in output.err
    assert "SECRET_VALUE" not in output.out + output.err
    assert "Traceback" not in output.out + output.err
