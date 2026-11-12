import os

import pytest

from ntk.config import ModelSettings
from ntk.model import cloud_key
from ntk.secrets import read_private_env


@pytest.mark.parametrize(
    "content",
    [
        "KEY=first\nKEY=second\n",
        "UNEXPECTED=value\n",
        "not-an-assignment\n",
        "KEY=" + "x" * 16_384,
        "KEY=" + "я" * 9000,
    ],
)
def test_private_env_rejects_ambiguous_unknown_or_oversized_input(tmp_path, content):
    path = tmp_path / "secret.env"
    path.write_text(content)
    path.chmod(0o600)
    with pytest.raises(ValueError):
        read_private_env(path, frozenset({"KEY"}))


@pytest.mark.parametrize("kind", ["public", "symlink", "fifo"])
def test_private_env_refuses_public_or_special_files(tmp_path, kind):
    target = tmp_path / "target.env"
    target.write_text("KEY=synthetic-secret\n")
    target.chmod(0o644 if kind == "public" else 0o600)
    path = target
    if kind == "symlink":
        path = tmp_path / "alias.env"
        path.symlink_to(target)
    elif kind == "fifo":
        path = tmp_path / "pipe.env"
        os.mkfifo(path, 0o600)
    with pytest.raises((OSError, ValueError)):
        read_private_env(path, frozenset({"KEY"}))


def test_a_bad_cloud_key_file_does_not_fall_back_to_another_secret(tmp_path):
    path = tmp_path / "secret.env"
    path.write_text("NTK_OPENAI_API_KEY=synthetic-file-key\n")
    path.chmod(0o644)
    config = ModelSettings(provider="openai", api_key="synthetic-fallback-key", env_file=path)
    assert cloud_key(config) == ""
    path.chmod(0o600)
    assert cloud_key(config) == "synthetic-file-key"
