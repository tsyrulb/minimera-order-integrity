import os
import subprocess
import sys
from dataclasses import FrozenInstanceError

import pytest

from ntk.config import DEFAULT_CLOUD_MODEL, ModelSettings, Settings
from ntk.dataset import ROOT, load_dataset
from ntk.model import ModelClient, request_body
from ntk.policy import project


def test_settings_are_frozen_and_do_not_display_credentials():
    config = Settings.from_env(
        {
            "NTK_PROVIDER": "openai",
            "NTK_OPENAI_API_KEY": "synthetic-api-secret",
            "PAYPAL_SANDBOX_CLIENT_ID": "synthetic-client-id",
            "PAYPAL_SANDBOX_CLIENT_SECRET": "synthetic-paypal-secret",
        }
    )
    assert config.model.model == DEFAULT_CLOUD_MODEL
    assert "synthetic-" not in repr(config)
    with pytest.raises(FrozenInstanceError):
        config.model.provider = "ollama"


def test_model_configuration_is_per_instance_and_requests_are_repeatable(tmp_path, monkeypatch):
    projection = project(load_dataset()[0]["cases"][0], "purpose")
    local = ModelClient(tmp_path / "local", Settings.from_env({}).model)
    cloud = ModelClient(tmp_path / "cloud", Settings.from_env({"NTK_PROVIDER": "openai"}).model)
    before = local.request(projection)
    monkeypatch.setenv("NTK_PROVIDER", "openai")
    monkeypatch.setenv("NTK_MODEL", "different-model")
    assert local.request(projection) == before == request_body(projection)
    assert cloud.request(projection)["model"] == DEFAULT_CLOUD_MODEL
    assert "messages" in before and "input" in cloud.request(projection)
    assert not (tmp_path / "local").exists()
    assert not (tmp_path / "cloud").exists()


@pytest.mark.parametrize(
    "url",
    [
        "http://remote.example",
        "http://user:password@localhost",
        "https://host/path",
        "https://host?key=secret",
        "https://",
        "http://localhost:99999",
    ],
)
def test_invalid_model_origins_are_refused(url):
    with pytest.raises(ValueError):
        ModelSettings(ollama_url=url)


def test_importing_asgi_app_does_not_create_runtime_or_start_integrations(tmp_path):
    runtime = tmp_path / "must-not-exist"
    env = dict(
        os.environ,
        NTK_RUNTIME_DIR=str(runtime),
        NTK_PROVIDER="ollama",
        NTK_MODEL="qwen2.5:3b",
        NTK_OLLAMA_URL="http://127.0.0.1:11434",
    )
    subprocess.run(
        [sys.executable, "-c", "import ntk.app"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        timeout=15,
    )
    assert not runtime.exists()
