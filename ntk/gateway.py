"""Model operations, output validation and a shared cross-process generation lock."""

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from .config import ModelSettings
from .contracts import Analysis, AppError, JsonObject, Projection


class ModelGateway(Protocol):
    """The operations used by the service and CLI, independent of HTTP transport."""

    @property
    def config(self) -> ModelSettings: ...

    @property
    def generation_settings(self) -> JsonObject: ...

    def request(self, projection: Projection) -> JsonObject: ...

    async def inspect(self) -> JsonObject: ...

    async def analyze(self, projection: Projection) -> JsonObject: ...

    async def unload(self) -> None: ...


@contextmanager
def generation_lock(runtime: Path) -> Iterator[None]:
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / "model.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise AppError(
                "MODEL_BUSY", "Another analysis is running. Please retry after it finishes.", 429
            ) from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def validate_analysis(content: str, projection: Projection) -> Analysis:
    analysis = Analysis.model_validate_json(content)
    fact_ids = {f["id"] for f in projection["payload"]["facts"]}
    if not set(analysis.citations) <= fact_ids:
        raise AppError(
            "INVALID_CITATION", "The model cited a fact outside its context. Draft withheld.", 502
        )
    return analysis
