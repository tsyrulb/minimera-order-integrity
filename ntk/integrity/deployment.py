"""Operator-controlled origins for the local app and hosted judge simulation."""

import ipaddress
import re
from collections.abc import Mapping
from urllib.parse import urlsplit


def is_local_origin(origin: str) -> bool:
    host = urlsplit(origin).hostname
    if host == "localhost":
        return True
    try:
        return bool(host and ipaddress.ip_address(host).is_loopback)
    except ValueError:
        return False


def normalize_origin(value: str) -> str:
    """Accept a complete origin, without credentials, paths or redirect parameters."""
    try:
        parts = urlsplit(value)
        host = parts.hostname
        port = parts.port
        if (
            parts.scheme not in ("http", "https")
            or not host
            or parts.username is not None
            or parts.password is not None
            or parts.path not in ("", "/")
            or parts.query
            or parts.fragment
            or any(char.isspace() or ord(char) < 32 for char in value)
            or (port is not None and not 1 <= port <= 65535)
        ):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            labels = host.split(".")
            if not all(
                re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label)
                for label in labels
            ):
                raise ValueError from None
        origin = f"{parts.scheme}://{parts.netloc.lower()}"
        if parts.scheme == "http" and not is_local_origin(origin):
            raise ValueError
        return origin
    except ValueError:
        raise ValueError(
            "Use an HTTPS origin, or HTTP on a loopback host, without a path or credentials."
        ) from None


def resolve_origin(port: int, environ: Mapping[str, str], explicit: str | None = None) -> str:
    """Only operator configuration determines callback URLs and the canonical host."""
    configured = explicit or environ.get("NTK_PUBLIC_ORIGIN")
    if not configured and environ.get("RENDER_EXTERNAL_HOSTNAME"):
        configured = "https://" + environ["RENDER_EXTERNAL_HOSTNAME"]
    return normalize_origin(configured or f"http://127.0.0.1:{port}")
