"""Isolated application fixtures; no test contacts a model or payment service."""

import httpx
import pytest
from fastapi.testclient import TestClient

from ntk.app import create_app
from ntk.config import ModelSettings, PayPalSettings, Settings
from ntk.model import ModelClient
from ntk.paypal import PayPalClient
from ntk.service import Service
from ntk.storage import EvidenceStore


def offline(request):
    raise httpx.ConnectError("External services are offline in this fixture", request=request)


@pytest.fixture
def service(tmp_path):
    transport = httpx.MockTransport(offline)
    return Service(
        model=ModelClient(tmp_path, ModelSettings(), transport=transport),
        store=EvidenceStore(tmp_path),
        sandbox=PayPalClient(PayPalSettings(), transport=transport),
    )


@pytest.fixture
def client(service):
    app = create_app(Settings(runtime_dir=service.store.runtime), service=service)
    with TestClient(app) as client:
        yield client
