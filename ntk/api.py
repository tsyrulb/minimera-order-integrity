"""HTTP handlers translate requests into calls on the application service."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, Response

from .contracts import AnalyzeRequest, AppError, JsonObject, Mode
from .dataset import ROOT, public_case
from .policy import MODES, POLICY_VERSION, PURPOSE, project
from .resources import memory_snapshot
from .service import Service
from .storage import read_json_object

router = APIRouter()


def get_service(request: Request) -> Service:
    return cast(Service, request.app.state.service)


CurrentService = Annotated[Service, Depends(get_service)]


@router.get("/")
async def index() -> FileResponse:
    return FileResponse(ROOT / "web/index.html")


@router.get("/api/health")
async def health(service: CurrentService) -> JsonObject:
    return {
        "status": "ok",
        "model": await service.model.inspect(),
        "memory": memory_snapshot(),
        "paypal": {
            "configured": service.sandbox.configured,
            "observation_available": "paypal-sandbox" in service.cases,
            "last_refresh_error": service.refresh_error,
        },
        "policy_version": POLICY_VERSION,
        "prompt_version": service.model.config.prompt_version,
        "dataset_sha256": service.dataset_sha256,
        "settings": service.model.generation_settings,
    }


@router.get("/api/cases")
async def cases(service: CurrentService) -> JsonObject:
    return {
        "cases": [
            {k: v for k, v in public_case(c).items() if k != "facts"}
            for c in service.cases.values()
        ],
        "modes": MODES,
        "purpose": PURPOSE,
    }


@router.get("/api/cases/{case_id}")
async def case(case_id: str, service: CurrentService) -> JsonObject:
    current = service.get_case(case_id)
    modes: list[Mode] = (
        ["purpose"] if current["source"]["kind"] != "synthetic" else ["full", "masked", "purpose"]
    )
    projections = {m: project(current, m) for m in modes}
    return {
        "case": public_case(current),
        "projections": {
            m: {**p, "model_request": service.model.request(p)} for m, p in projections.items()
        },
        "recorded_modes": [m for m in modes if service.cached(current, m)],
    }


@router.post("/api/analyze")
async def analyze(body: AnalyzeRequest, service: CurrentService) -> JsonObject:
    return await service.analyze(body.case_id, body.mode, body.fresh)


@router.post("/api/paypal/refresh")
async def paypal_refresh(service: CurrentService) -> JsonObject:
    return {"case": public_case(await service.refresh_paypal())}


@router.get("/api/evaluation")
async def evaluation(service: CurrentService) -> JsonObject:
    path = service.store.benchmark_path
    return (
        read_json_object(path)
        if path.exists()
        else {"status": "not_run", "summary": [], "runs": []}
    )


@router.get("/api/evaluation/download")
async def evaluation_download(service: CurrentService) -> FileResponse:
    path = service.store.benchmark_path
    if not path.exists():
        raise AppError("EVALUATION_NOT_RUN", "The benchmark has not been run yet.", 404)
    return FileResponse(path, media_type="application/json", filename="minimera-benchmark.json")


@router.get("/api/methodology")
async def methodology() -> Response:
    return Response((ROOT / "data/DATASET.md").read_text(encoding="utf-8"), media_type="text/plain")
