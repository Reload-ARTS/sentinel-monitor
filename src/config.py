"""Carga y validación local de la configuración, sin efectos de red."""

import ipaddress
import json
import math
import re
from urllib.parse import urlsplit


class ConfigurationError(ValueError):
    """Error previsto con un diagnóstico que no contiene valores de entrada."""


def _object(data, field, required, optional=()):
    if not isinstance(data, dict):
        raise ConfigurationError(f"{field}: debe ser un objeto.")
    for key in required:
        if key not in data:
            raise ConfigurationError(f"{field}.{key}: campo obligatorio ausente.")
    if any(key not in (*required, *optional) for key in data):
        raise ConfigurationError(f"{field}: contiene claves desconocidas.")


def _positive(value, field):
    # Los enteros arbitrariamente grandes son finitos sin convertirlos a float.
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or (isinstance(value, float) and not math.isfinite(value))
            or value <= 0):
        raise ConfigurationError(f"{field}: debe ser un número finito positivo.")


def _url(value, field):
    message = f"{field}: debe ser una URL HTTP/HTTPS absoluta válida, sin credenciales ni caracteres de control."
    if not isinstance(value, str) or any(ord(c) < 33 or 127 <= ord(c) <= 159 for c in value):
        raise ConfigurationError(message)
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port  # También valida sintaxis y rango del puerto.
        if (parsed.scheme not in ("http", "https") or not host
                or parsed.username is not None or parsed.password is not None
                or parsed.netloc.endswith(":") or port == 0):
            raise ValueError
        if ":" in host:
            ipaddress.IPv6Address(host)
        elif re.fullmatch(r"[0-9.]+", host) and "." in host:
            ipaddress.IPv4Address(host)
        else:
            ascii_host = host.encode("idna").decode("ascii")
            if ascii_host.endswith("."):
                ascii_host = ascii_host[:-1]
            if not ascii_host or len(ascii_host) > 253:
                raise ValueError
            for label in ascii_host.split("."):
                if not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label):
                    raise ValueError
    except (ValueError, UnicodeError):
        raise ConfigurationError(message) from None


def validate_config(data):
    """Valida el conjunto y devuelve un diccionario nuevo; no modifica la entrada."""
    _object(data, "config", ("settings", "targets"))
    settings = data["settings"]
    _object(settings, "settings", ("timeout_seconds", "max_acceptable_latency_ms"))
    for key in ("timeout_seconds", "max_acceptable_latency_ms"):
        _positive(settings[key], f"settings.{key}")
    targets = data["targets"]
    if not isinstance(targets, list) or not targets:
        raise ConfigurationError("targets: debe ser una lista no vacía.")
    validated = []
    names = set()
    for index, target in enumerate(targets):
        field = f"targets[{index}]"
        _object(target, field, ("name", "url"), ("expected_status",))
        name = target["name"]
        if not isinstance(name, str) or not name.strip():
            raise ConfigurationError(f"{field}.name: debe ser texto no vacío.")
        if name in names:
            raise ConfigurationError(f"{field}.name: nombre duplicado.")
        names.add(name)
        _url(target["url"], f"{field}.url")
        status = target.get("expected_status", 200)
        if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
            raise ConfigurationError(f"{field}.expected_status: debe ser un entero entre 100 y 599.")
        validated.append({"name": name, "url": target["url"], "expected_status": status})
    return {"settings": dict(settings), "targets": validated}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ConfigurationError("JSON: contiene claves duplicadas en un objeto.")
        result[key] = value
    return result


def load_config(path):
    """Lee UTF-8, rechaza claves duplicadas y valida antes de devolver datos."""
    try:
        with open(path, "r", encoding="utf-8") as file:
            try:
                data = json.load(file, object_pairs_hook=_unique_object)
            except ConfigurationError:
                raise
            except json.JSONDecodeError as exc:
                raise ConfigurationError(f"JSON: sintaxis inválida en línea {exc.lineno}, columna {exc.colno}.") from None
            except UnicodeError:
                raise  # Mantener el diagnóstico específico de codificación.
            except ValueError:
                raise ConfigurationError("JSON: no se pudo convertir un valor numérico dentro de los límites del intérprete.") from None
    except UnicodeError:
        raise ConfigurationError("config: el archivo debe utilizar codificación UTF-8 válida.") from None
    except OSError:
        raise ConfigurationError("config: no se pudo leer el archivo de configuración.") from None
    return validate_config(data)
