"""Local demo sessions and order-scoped buyer capabilities; no provider credentials."""

import base64
import hashlib
import hmac
import json
import os
import secrets
import stat
import time
from pathlib import Path
from typing import Literal

from ..contracts import AppError
from .policy import canonical

Role = Literal["merchant", "buyer"]


class Sessions:
    def __init__(self, directory: Path) -> None:
        path = directory / "session.key"
        if not path.exists():
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(descriptor, "wb") as file:
                    file.write(secrets.token_bytes(32))
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or info.st_size != 32
        ):
            raise ValueError("Session key must be an owner-only regular file")
        self._key = path.read_bytes()
        if len(self._key) != 32:
            raise ValueError("Invalid local session key")

    def token(self, workspace: str, role: Role) -> str:
        payload = (
            base64.urlsafe_b64encode(
                canonical(
                    {"workspace": workspace, "role": role, "expires": int(time.time()) + 86400}
                ).encode()
            )
            .decode()
            .rstrip("=")
        )
        signature = hmac.new(self._key, payload.encode(), hashlib.sha256).hexdigest()
        return payload + "." + signature

    def verify(self, token: str, role: Role) -> str:
        try:
            if len(token) > 512:
                raise ValueError("Token too long")
            payload, signature = token.split(".")
            expected = hmac.new(self._key, payload.encode(), hashlib.sha256).hexdigest()
            value = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            if (
                not hmac.compare_digest(expected, signature)
                or value["role"] != role
                or value["expires"] <= time.time()
            ):
                raise ValueError("Invalid session")
            workspace = value["workspace"]
            if not isinstance(workspace, str) or len(workspace) != 32:
                raise ValueError("Invalid workspace")
            return workspace
        except (ValueError, KeyError, TypeError):
            raise AppError(
                "SESSION_REQUIRED", "Open this order through its authorized demo session.", 403
            ) from None

    def csrf(self, workspace: str) -> str:
        return hmac.new(self._key, ("csrf:" + workspace).encode(), hashlib.sha256).hexdigest()
