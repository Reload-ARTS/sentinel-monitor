"""Discord simulado: validación y envío sin secretos ni red real."""

import importlib
import json
import socket
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.config import ConfigurationError
from src.notifier import AlertNotifier, validate_alert_settings
from src import checker, notifier
from dotenv import load_dotenv as real_load_dotenv

WEBHOOK = "https://discord.com/api/webhooks/123/test_token"


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv("ENABLE_ALERTS", "false")
    monkeypatch.delenv("WEBHOOK_URL", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda **kwargs: False)
    def forbidden(*args, **kwargs):
        pytest.fail("Red real inesperada")
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


@pytest.mark.parametrize("flag", ["false", "FALSE", " false "])
def test_disabled_needs_no_webhook(flag):
    assert validate_alert_settings({"ENABLE_ALERTS": flag, "WEBHOOK_URL": "IGNORED"}) == (False, None)


@pytest.mark.parametrize("flag", [None, "true", "TRUE", " true "])
def test_enabled_and_current_default(flag):
    env = {"WEBHOOK_URL": WEBHOOK}
    if flag is not None:
        env["ENABLE_ALERTS"] = flag
    assert validate_alert_settings(env) == (True, WEBHOOK)


@pytest.mark.parametrize("flag", ["", "1", "yes", "tru", "SECRET_FLAG"])
def test_bad_flag_is_safe(flag):
    with pytest.raises(ConfigurationError) as error:
        validate_alert_settings({"ENABLE_ALERTS": flag})
    assert str(error.value) == "ENABLE_ALERTS: debe ser true o false."


@pytest.mark.parametrize("url", ["", " ", "http://discord.com/api/webhooks/123/test_token",
    "https://evil.test/api/webhooks/123/test_token", "https://discord.com.evil.test/api/webhooks/123/test_token",
    "https://user:SECRET@discord.com/api/webhooks/123/test_token", "https://discord.com/api/webhooks/TU_WEBHOOK_AQUI",
    WEBHOOK + "?token=SECRET", WEBHOOK + "#SECRET", WEBHOOK + "\n", "https://discord.com:bad/api/webhooks/123/test_token",
    "https://discord.com:80/api/webhooks/123/test_token", "https://discord.com/other/SECRET"])
def test_invalid_webhook_safe(url):
    with pytest.raises(ConfigurationError) as error:
        validate_alert_settings({"ENABLE_ALERTS": "true", "WEBHOOK_URL": url})
    assert "SECRET" not in str(error.value)
    assert "test_token" not in str(error.value)


@pytest.mark.parametrize("status, expected", [(200, "accepted"), (204, "accepted"), (400, "failed"),
                                           (429, "failed"), (500, "failed"), (302, "failed")])
def test_http_notification(status, expected):
    sender = AlertNotifier(WEBHOOK)
    payload = sender.prepare_alert("API", 503)
    response = MagicMock(status_code=status)
    with patch("requests.post", return_value=response) as post:
        assert sender.send_alert(payload) == expected
    post.assert_called_once_with(WEBHOOK, json=payload, timeout=5, allow_redirects=False)
    response.close.assert_called_once()
    assert "test_token" not in json.dumps(payload)
    assert "url" not in json.dumps(payload).lower()
    assert payload["allowed_mentions"] == {"parse": []}


@pytest.mark.parametrize("error", [requests.exceptions.Timeout, requests.exceptions.ConnectionError])
def test_transport_failure_no_secret_logs(error, caplog):
    with patch("requests.post", side_effect=error("SECRET_WEBHOOK")):
        assert AlertNotifier(WEBHOOK).send_alert({}) == "failed"
    assert "SECRET_WEBHOOK" not in caplog.text


def test_import_has_no_dotenv_or_http_side_effects(monkeypatch):
    with patch("dotenv.load_dotenv", side_effect=AssertionError("Carga implícita")), \
            patch("requests.post", side_effect=AssertionError("POST inesperado")):
        importlib.reload(notifier)


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    config = {"settings": {"timeout_seconds": 2, "max_acceptable_latency_ms": 1000},
              "targets": [{"name": n, "url": "https://example.test/private/SECRET_URL", "expected_status": 200}
                          for n in ("A", "B", "C")]}
    path = tmp_path / "config" / "targets.json"
    path.parent.mkdir()
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENABLE_ALERTS", "true")
    monkeypatch.setenv("WEBHOOK_URL", WEBHOOK)
    return path


@pytest.mark.parametrize("missing", [True, False])
def test_validation_blocks_all_requests(config_file, monkeypatch, capsys, missing):
    if missing:
        monkeypatch.delenv("WEBHOOK_URL")
    else:
        config_file.write_text("{}", encoding="utf-8")
    with patch("requests.get", side_effect=AssertionError("GET")) as get, \
            patch("requests.post", side_effect=AssertionError("POST")) as post:
        assert checker.main() == 2
        get.assert_not_called()
        post.assert_not_called()
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["execution_status"] == "not_started"
    assert report["targets"] == []
    assert "test_token" not in output.out + output.err


@pytest.mark.parametrize("post_failure", [400, requests.exceptions.Timeout("SECRET"), requests.exceptions.ConnectionError("SECRET")])
def test_independent_attempts_continue_after_failure(config_file, capsys, post_failure):
    first = MagicMock(status_code=post_failure) if isinstance(post_failure, int) else post_failure
    with patch("requests.get", return_value=MagicMock(status_code=503)) as get, \
            patch("requests.post", side_effect=[first, MagicMock(status_code=204), MagicMock(status_code=200)]) as post:
        assert checker.main() == 1
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["execution_status"] == "completed"
    assert report["summary"]["down"] == 3
    assert [r["notification"] for r in report["targets"]] == ["failed", "accepted", "accepted"]
    assert all(r["status"] == "DOWN" and r["http_status"] == 503 for r in report["targets"])
    assert get.call_count == post.call_count == 3
    assert "SECRET" not in output.out + output.err
    for call in post.call_args_list:
        assert "SECRET_URL" not in json.dumps(call.kwargs["json"])


def test_healthy_and_degraded_no_notifications(config_file, capsys):
    with patch("requests.get", return_value=MagicMock(status_code=200)), \
            patch("time.perf_counter", side_effect=[0, 0.1, 0, 1.000004, 0, 0.5]), \
            patch("requests.post", side_effect=AssertionError("POST")) as post:
        assert checker.main() == 0
        post.assert_not_called()
    report = json.loads(capsys.readouterr().out)
    assert [r["status"] for r in report["targets"]] == ["HEALTHY", "DEGRADED", "HEALTHY"]
    assert all(r["notification"] == "not_required" for r in report["targets"])


def test_internal_before_notification_keeps_down_not_attempted(config_file, capsys):
    with patch("requests.get", return_value=MagicMock(status_code=503)) as get, \
            patch.object(checker.AlertNotifier, "prepare_alert", side_effect=RuntimeError("SECRET")), \
            patch("requests.post", side_effect=AssertionError("POST")) as post:
        assert checker.main() == 3
        assert get.call_count == 1
        post.assert_not_called()
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["execution_status"] == "incomplete"
    assert report["targets"][0]["status"] == "DOWN"
    assert report["targets"][0]["notification"] == "not_attempted"
    assert report["summary"]["checked"] == 1
    assert report["summary"]["not_checked"] == 2
    assert report["not_checked"] == [{"name": "B"}, {"name": "C"}]
    assert "SECRET" not in output.out + output.err


def test_partial_results_after_accepted_notification(config_file, capsys):
    with patch("requests.get", side_effect=[MagicMock(status_code=503), RuntimeError("SECRET")]), \
            patch("requests.post", return_value=MagicMock(status_code=204)) as post:
        assert checker.main() == 3
        assert post.call_count == 1
    report = json.loads(capsys.readouterr().out)
    assert report["targets"][0]["notification"] == "accepted"
    assert report["not_checked"] == [{"name": "B"}, {"name": "C"}]


def test_unexpected_post_error_is_internal_after_attempt(config_file, capsys):
    with patch("requests.get", return_value=MagicMock(status_code=503)), \
            patch("requests.post", side_effect=RuntimeError("SECRET")) as post:
        assert checker.main() == 3
        assert post.call_count == 1
    report = json.loads(capsys.readouterr().out)
    assert report["execution_status"] == "incomplete"
    assert report["targets"][0]["notification"] == "failed"


def test_internal_in_sender_before_attempt_is_not_attempted(config_file, capsys):
    with patch("requests.get", return_value=MagicMock(status_code=503)), \
            patch.object(checker.AlertNotifier, "send_alert", side_effect=RuntimeError("SECRET")), \
            patch("requests.post", side_effect=AssertionError("POST")) as post:
        assert checker.main() == 3
        post.assert_not_called()
    report = json.loads(capsys.readouterr().out)
    assert report["targets"][0]["notification"] == "not_attempted"


def test_attempt_tracking_resets_for_each_down(config_file, capsys):
    sender = checker.AlertNotifier(WEBHOOK)
    with patch.object(checker, "AlertNotifier", return_value=sender), \
            patch("requests.get", return_value=MagicMock(status_code=503)), \
            patch.object(sender, "prepare_alert", side_effect=[{}, RuntimeError("SECRET")]), \
            patch("requests.post", return_value=MagicMock(status_code=204)) as post:
        assert checker.main() == 3
        assert post.call_count == 1
    report = json.loads(capsys.readouterr().out)
    assert [r["notification"] for r in report["targets"]] == ["accepted", "not_attempted"]


def test_explicit_temporary_dotenv_loading(config_file, monkeypatch, capsys):
    monkeypatch.delenv("ENABLE_ALERTS")
    monkeypatch.delenv("WEBHOOK_URL")
    monkeypatch.setattr("dotenv.load_dotenv", real_load_dotenv)
    (config_file.parent.parent / ".env").write_text("ENABLE_ALERTS=true\nWEBHOOK_URL=" + WEBHOOK + "\n", encoding="utf-8")
    with patch("requests.get", return_value=MagicMock(status_code=503)), \
            patch("requests.post", return_value=MagicMock(status_code=204)) as post:
        assert checker.main() == 1
        assert post.call_count == 3
    output = capsys.readouterr()
    assert "test_token" not in output.out + output.err


def test_environment_has_priority_over_dotenv(config_file, monkeypatch, capsys):
    monkeypatch.setenv("ENABLE_ALERTS", "false")
    monkeypatch.setattr("dotenv.load_dotenv", real_load_dotenv)
    (config_file.parent.parent / ".env").write_text("ENABLE_ALERTS=true\nWEBHOOK_URL=" + WEBHOOK + "\n", encoding="utf-8")
    with patch("requests.get", return_value=MagicMock(status_code=503)), \
            patch("requests.post", side_effect=AssertionError("POST")) as post:
        assert checker.main() == 1
        post.assert_not_called()
    report = json.loads(capsys.readouterr().out)
    assert all(r["notification"] == "disabled" for r in report["targets"])


@pytest.mark.parametrize("error", [OSError("SECRET"), UnicodeError("SECRET")])
def test_dotenv_read_failure_is_safe_configuration_error(config_file, monkeypatch, capsys, error):
    def fail(**kwargs):
        raise error
    monkeypatch.setattr("dotenv.load_dotenv", fail)
    with patch("requests.get", side_effect=AssertionError("GET")) as get, \
            patch("requests.post", side_effect=AssertionError("POST")) as post:
        assert checker.main() == 2
        get.assert_not_called()
        post.assert_not_called()
    output = capsys.readouterr()
    assert json.loads(output.out)["execution_status"] == "not_started"
    assert "SECRET" not in output.out + output.err


def test_dotenv_warning_cannot_contaminate_stdout(config_file, monkeypatch, capsys):
    import logging
    import sys
    monkeypatch.setattr("dotenv.load_dotenv", real_load_dotenv)
    (config_file.parent.parent / ".env").write_text('BAD="unterminated\n', encoding="utf-8")
    root = logging.getLogger()
    handler = logging.StreamHandler(sys.stdout)
    root.addHandler(handler)
    env_logger = logging.getLogger("dotenv.main")
    previous = (env_logger.level, env_logger.propagate, env_logger.handlers[:])
    try:
        with patch("requests.get", return_value=MagicMock(status_code=200)), \
                patch("requests.post", side_effect=AssertionError("POST")) as post:
            assert checker.main() == 0
            post.assert_not_called()
        output = capsys.readouterr()
        assert json.loads(output.out)["execution_status"] == "completed"
        assert "could not parse" in output.err
        assert "unterminated" not in output.out + output.err
        assert (env_logger.level, env_logger.propagate, env_logger.handlers) == previous
    finally:
        root.removeHandler(handler)
        handler.close()


@pytest.mark.parametrize("fails", [False, True])
def test_transport_debug_does_not_expose_webhook(fails, caplog):
    import logging
    loggers = [logging.getLogger(name) for name in ("urllib3.connectionpool", "urllib3.util.retry")]
    before = [item.disabled for item in loggers]
    def transport(*args, **kwargs):
        for item in loggers:
            item.warning("SECRET_WEBHOOK /api/webhooks/123/test_token")
        if fails:
            raise requests.exceptions.ConnectionError("SECRET_WEBHOOK")
        return MagicMock(status_code=204)
    with patch("requests.post", side_effect=transport):
        assert AlertNotifier(WEBHOOK).send_alert({}) == ("failed" if fails else "accepted")
    assert "SECRET_WEBHOOK" not in caplog.text
    assert "test_token" not in caplog.text
    assert [item.disabled for item in loggers] == before
