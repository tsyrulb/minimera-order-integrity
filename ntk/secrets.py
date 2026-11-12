"""Read small, operator-owned credential files without following symlinks."""

import os
import stat
from pathlib import Path

MAX_SECRET_BYTES = 16_384


def read_private_env(path: Path, allowed_keys: frozenset[str]) -> dict[str, str]:
    """Reject public files, special files, duplicate keys and unexpected fields.

    The file is inspected through its open descriptor so a path replacement
    cannot separate the permission check from the bytes being read.
    """
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, encoding="utf-8") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Credential file must be an owner-only regular file")
        raw = source.read(MAX_SECRET_BYTES + 1)
    if len(raw.encode("utf-8")) > MAX_SECRET_BYTES:
        raise ValueError("Credential file exceeds its size limit")
    values: dict[str, str] = {}
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or key not in allowed_keys or key in values:
            raise ValueError("Credential file contains unexpected or duplicate keys")
        values[key] = value.strip()
    return values
