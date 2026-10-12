"""Contrato de validación sin red ni acceso a secretos locales."""

from copy import deepcopy
import json
import socket

import pytest
import requests

from src.config import ConfigurationError, load_config, validate_config


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Solicitud de red inesperada")
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


@pytest.fixture
def config():
    return {"settings": {"timeout_seconds": 5, "max_acceptable_latency_ms": 1000},
            "targets": [{"name": "Servicio", "url": "https://example.test/path"}]}


def test_valid_file_and_default_without_mutation(tmp_path, config):
    original = deepcopy(config)
    path = tmp_path / "targets.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    result = load_config(path)
    assert result["targets"][0]["expected_status"] == 200
    assert validate_config(config) == result
    result["settings"]["timeout_seconds"] = 8
    result["targets"][0]["name"] = "Otro"
    assert config == original


def test_missing_file(tmp_path):
    with pytest.raises(ConfigurationError, match="no se pudo leer"):
        load_config(tmp_path / "missing.json")


@pytest.mark.parametrize("content, message", [
    (b'{"private": "SECRET",}', "línea 1, columna"),
    (b'\xff', "UTF-8"),
    (b'{"SECRET": 1, "SECRET": 2}', "claves duplicadas"),
    (b'{"settings": {"SECRET": 1, "SECRET": 2}}', "claves duplicadas"),
    (b'{"targets": [{"name": "A", "name": "SECRET"}]}', "claves duplicadas"),
])
def test_parsing_errors_are_safe(tmp_path, content, message):
    path = tmp_path / "targets.json"
    path.write_bytes(content)
    with pytest.raises(ConfigurationError, match=message) as exc:
        load_config(path)
    assert "SECRET" not in str(exc.value)


@pytest.mark.parametrize("root", [None, [], "text", 1, True])
def test_root_type(root):
    with pytest.raises(ConfigurationError, match="config: debe ser un objeto"):
        validate_config(root)


@pytest.mark.parametrize("section", ["settings", "targets"])
@pytest.mark.parametrize("value", [None, "text", 1, True, {}])
def test_section_types(config, section, value):
    config[section] = value
    with pytest.raises(ConfigurationError):
        validate_config(config)


def test_empty_targets(config):
    config["targets"] = []
    with pytest.raises(ConfigurationError, match="targets"):
        validate_config(config)


@pytest.mark.parametrize("location, key", [
    ("root", "settings"), ("root", "targets"),
    ("settings", "timeout_seconds"), ("settings", "max_acceptable_latency_ms"),
    ("target", "name"), ("target", "url"),
])
def test_required_fields(config, location, key):
    obj = config if location == "root" else config["settings"] if location == "settings" else config["targets"][0]
    del obj[key]
    with pytest.raises(ConfigurationError, match="campo obligatorio"):
        validate_config(config)


@pytest.mark.parametrize("location", ["root", "settings", "target"])
def test_unknown_keys_are_safe(config, location):
    obj = config if location == "root" else config["settings"] if location == "settings" else config["targets"][0]
    obj["SECRET_KEY"] = "SECRET_VALUE"
    with pytest.raises(ConfigurationError, match="claves desconocidas") as exc:
        validate_config(config)
    assert "SECRET" not in str(exc.value)


@pytest.mark.parametrize("value", [None, [], "text", 3])
def test_target_is_object(config, value):
    config["targets"] = [value]
    with pytest.raises(ConfigurationError, match=r"targets\[0\]"):
        validate_config(config)


@pytest.mark.parametrize("name", ["", " \t\n", None, 2, True])
def test_name(config, name):
    config["targets"][0]["name"] = name
    with pytest.raises(ConfigurationError, match="name"):
        validate_config(config)


def test_duplicate_names(config):
    config["targets"].append(dict(config["targets"][0]))
    with pytest.raises(ConfigurationError, match=r"targets\[1\].name: nombre duplicado"):
        validate_config(config)


@pytest.mark.parametrize("key", ["timeout_seconds", "max_acceptable_latency_ms"])
@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), float("-inf"), True, False, None, "5", [], {}])
def test_invalid_numbers(config, key, value):
    config["settings"][key] = value
    with pytest.raises(ConfigurationError, match=key):
        validate_config(config)


@pytest.mark.parametrize("value", [0.001, 1, 1.5])
def test_positive_numbers(config, value):
    config["settings"] = {"timeout_seconds": value, "max_acceptable_latency_ms": value}
    assert validate_config(config)["settings"] == config["settings"]


@pytest.mark.parametrize("url", [
    "http://localhost:8080/health", "https://service.internal/path?q=1",
    "http://127.0.0.1:1/", "http://[::1]:65535/health", "https://example.test:443/path",
])
def test_valid_urls(config, url):
    config["targets"][0]["url"] = url
    assert validate_config(config)["targets"][0]["url"] == url


@pytest.mark.parametrize("url", [
    None, 5, "", "/relative", "ftp://example.test", "http:///path",
    "http://example.test:abc", "http://example.test:65536", "http://example.test:0",
    "http://example.test:", "http://[bad]/", "http://bad_host/", "http://-bad.test/",
    "http://999.1.1.1/", "http://example.test../", "https://user:SECRET@example.test/", "https://user@example.test/",
    "http://example.test/\nSECRET", "http://example.test/\x7f", "http://example.test/with space",
])
def test_invalid_urls_are_safe(config, url):
    config["targets"][0]["url"] = url
    with pytest.raises(ConfigurationError, match=r"targets\[0\].url") as exc:
        validate_config(config)
    assert "SECRET" not in str(exc.value)


@pytest.mark.parametrize("status", [100, 200, 599])
def test_http_boundaries(config, status):
    config["targets"][0]["expected_status"] = status
    assert validate_config(config)["targets"][0]["expected_status"] == status


@pytest.mark.parametrize("status", [99, 600, True, False, None, "200", 200.0])
def test_invalid_http_status(config, status):
    config["targets"][0]["expected_status"] = status
    with pytest.raises(ConfigurationError, match="expected_status"):
        validate_config(config)


def test_stable_first_error(config):
    config["settings"]["timeout_seconds"] = 0
    config["targets"][0]["url"] = "invalid"
    with pytest.raises(ConfigurationError, match="settings.timeout_seconds"):
        validate_config(config)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_json(tmp_path, constant):
    path = tmp_path / "targets.json"
    path.write_text('{"settings":{"timeout_seconds":' + constant + ',"max_acceptable_latency_ms":1000},"targets":[{"name":"A","url":"http://localhost"}]}', encoding="utf-8")
    with pytest.raises(ConfigurationError, match="timeout_seconds"):
        load_config(path)


def test_integer_conversion_limit_is_configuration_error(tmp_path):
    import sys

    get_limit = getattr(sys, "get_int_max_str_digits", None)
    if get_limit is None or get_limit() == 0:
        pytest.skip("Intérprete sin límite activo de conversión de enteros")
    number = "9" * (get_limit() + 1)
    path = tmp_path / "targets.json"
    path.write_text('{"settings":{"timeout_seconds":' + number + '}}', encoding="utf-8")
    with pytest.raises(ConfigurationError, match="valor numérico") as exc:
        load_config(path)
    assert number not in str(exc.value)
    assert "999999" not in str(exc.value)
    assert sys.get_int_max_str_digits() == get_limit()


def test_simulated_numeric_parsing_error_is_safe(tmp_path, monkeypatch):
    path = tmp_path / "targets.json"
    path.write_text("{}", encoding="utf-8")

    def failed_parsing(*args, **kwargs):
        raise ValueError("SECRET 999999")

    monkeypatch.setattr("src.config.json.load", failed_parsing)
    with pytest.raises(ConfigurationError, match="valor numérico") as exc:
        load_config(path)
    assert "SECRET" not in str(exc.value)
    assert "999999" not in str(exc.value)


def test_existing_configuration_error_is_preserved(tmp_path, monkeypatch):
    path = tmp_path / "targets.json"
    path.write_text("{}", encoding="utf-8")
    original = ConfigurationError("JSON: contiene claves duplicadas en un objeto.")

    def duplicate_keys(*args, **kwargs):
        raise original

    monkeypatch.setattr("src.config.json.load", duplicate_keys)
    with pytest.raises(ConfigurationError) as exc:
        load_config(path)
    assert exc.value is original
