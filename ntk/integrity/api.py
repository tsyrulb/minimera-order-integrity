"""Role-scoped HTTP boundary. The buyer never receives merchant action capability."""

import secrets
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from ..contracts import AppError
from .auth import Sessions
from .contracts import (
    ApprovalRequest,
    AskRequest,
    ChangeRequest,
    CompleteCheckout,
    NewWorkspace,
    Workspace,
)
from .deployment import is_local_origin
from .policy import DESTINATIONS, model_context
from .service import IntegrityService

router = APIRouter(prefix="/api/integrity")
COOKIE = "minimera_merchant"


def service(request: Request) -> IntegrityService:
    return cast(IntegrityService, request.app.state.integrity)


def sessions(request: Request) -> Sessions:
    return cast(Sessions, request.app.state.sessions)


Service = Annotated[IntegrityService, Depends(service)]
Auth = Annotated[Sessions, Depends(sessions)]


def merchant(request: Request, auth: Auth) -> str:
    if request.headers.get("x-minimera-buyer"):
        raise AppError("ROLE_REFUSED", "Buyer access cannot approve merchant actions.", 403)
    workspace = auth.verify(request.cookies.get(COOKIE, ""), "merchant")
    if request.method != "GET" and not secrets.compare_digest(
        request.headers.get("x-minimera-csrf", ""), auth.csrf(workspace)
    ):
        raise AppError("CSRF_REFUSED", "Refresh the merchant session before continuing.", 403)
    return workspace


def buyer(request: Request, auth: Auth) -> str:
    return auth.verify(request.headers.get("x-minimera-buyer", ""), "buyer")


Merchant = Annotated[str, Depends(merchant)]
Buyer = Annotated[str, Depends(buyer)]


def merchant_view(ws: Workspace, auth: Sessions) -> dict[str, Any]:
    return {
        "workspace": ws.model_dump(exclude={"checkouts"}),
        "csrf": auth.csrf(ws.id),
        "buyer_url": "/buyer/" + auth.token(ws.id, "buyer"),
        "destinations": DESTINATIONS,
        "model_context": model_context(ws.change) if ws.change else None,
    }


@router.get("/status")
async def status(current: Service) -> dict[str, Any]:
    return {
        "product": "Minimera Order Integrity",
        "sandbox_enabled": current.sandbox is not None,
        "fresh_ai_enabled": current.analyst.fresh,
        "merchant_system": "synthetic_oms",
        "publication": "local_only" if is_local_origin(current.origin) else "operator_hosted",
    }


@router.post("/workspaces")
async def create_workspace(
    body: NewWorkspace, response: Response, request: Request, current: Service, auth: Auth
) -> dict[str, Any]:
    ws = await current.create(body)
    response.set_cookie(
        COOKIE,
        auth.token(ws.id, "merchant"),
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        max_age=86400,
        path="/",
    )
    return merchant_view(ws, auth)


@router.get("/workspace")
async def workspace(workspace_id: Merchant, current: Service, auth: Auth) -> dict[str, Any]:
    return merchant_view(current.store.get(workspace_id), auth)


@router.post("/analyze")
async def analyze(workspace_id: Merchant, current: Service, auth: Auth) -> dict[str, Any]:
    return merchant_view(await current.analyze(workspace_id), auth)


@router.post("/approve")
async def approve(
    body: ApprovalRequest, workspace_id: Merchant, current: Service, auth: Auth
) -> dict[str, Any]:
    return merchant_view(await current.approve(workspace_id, body.snapshot_hash), auth)


@router.post("/resume")
async def resume(workspace_id: Merchant, current: Service, auth: Auth) -> dict[str, Any]:
    return merchant_view(await current.resume(workspace_id), auth)


@router.post("/recheck")
async def recheck(workspace_id: Merchant, current: Service, auth: Auth) -> dict[str, Any]:
    return merchant_view(await current.recheck(workspace_id), auth)


@router.post("/release")
async def release(workspace_id: Merchant, current: Service, auth: Auth) -> dict[str, Any]:
    return merchant_view(await current.release(workspace_id), auth)


@router.post("/simulate-warehouse-change")
async def warehouse_change(workspace_id: Merchant, current: Service, auth: Auth) -> dict[str, Any]:
    return merchant_view(await current.advance_warehouse(workspace_id), auth)


@router.get("/evidence")
async def evidence(workspace_id: Merchant, current: Service) -> JSONResponse:
    return JSONResponse(
        current.evidence(current.store.get(workspace_id)),
        headers={
            "Content-Disposition": 'attachment; filename="minimera-order-integrity-evidence.json"'
        },
    )


@router.post("/assistant")
async def assistant(body: AskRequest, workspace_id: Merchant, current: Service) -> dict[str, Any]:
    ws = await current.analyze(workspace_id)
    change = current.get_change(ws)
    if body.question == "privacy":
        answer = "The AI receives seven scoped facts: payment state, fulfillment state, destination/total change flags and documented PayPal constraints. Names, full addresses, messages, payment IDs and approval tokens stay outside the model context. The server still processes the order data needed to perform the workflow."
        source = "deterministic_context_inspection"
    elif body.question == "next_step":
        answer = {
            "review": "Review the exact refund and replacement amounts, then approve this version of the plan.",
            "approved": "The buyer must approve the replacement order. Their approval does not itself complete the new charge.",
            "awaiting_buyer": "Waiting for buyer approval in the checkout flow.",
            "complete": (
                "The corrected order is already released to the synthetic warehouse queue. No further payment action is needed."
                if ws.fulfillment_order and ws.fulfillment_order.fulfillment == "released"
                else "Both payment legs are verified. Review and release the corrected order to the synthetic warehouse."
            ),
            "pending": "Check the known refund again. Do not capture the replacement while the refund is pending.",
        }.get(change.state, change.explanation)
        source = "deterministic_workflow_state"
    elif change.state in ("stale", "pending", "indeterminate", "processing", "complete"):
        answer = change.explanation
        source = "deterministic_workflow_state"
    else:
        advice = change.advice
        answer = (
            (
                advice.plan.summary
                + "\n\n"
                + "\n".join(f"{i + 1}. {step}" for i, step in enumerate(advice.plan.steps))
            )
            if advice and advice.plan
            else "No validated AI recording is available for this context. " + change.explanation
        )
        source = advice.source if advice else "unavailable"
    return {
        "answer": answer,
        "source": source,
        "state": change.state,
        "model": change.advice.model if change.advice else None,
    }


@router.get("/buyer")
async def buyer_order(workspace_id: Buyer, current: Service) -> dict[str, Any]:
    ws = current.store.get(workspace_id)
    return {
        "revision": ws.revision,
        "mode": ws.mode,
        "order": ws.order.model_dump(),
        "destinations": DESTINATIONS,
        "change": None
        if ws.change is None
        else {
            "destination": ws.change.destination,
            "remove_pouch": ws.change.remove_pouch,
            "items": [item.model_dump() for item in ws.change.items],
            "state": ws.change.state,
            "explanation": ws.change.explanation,
            "cents": ws.change.cents,
            "refund_status": ws.change.refund.status if ws.change.refund else None,
            "replacement_status": ws.change.replacement.capture_status
            if ws.change.replacement
            else None,
        },
    }


@router.post("/buyer/change")
async def change_request(
    body: ChangeRequest, workspace_id: Buyer, current: Service
) -> dict[str, str]:
    await current.request_change(workspace_id, body)
    return {"status": "received"}


@router.post("/buyer/checkout/{purpose}")
async def buyer_checkout(
    purpose: Literal["original", "replacement"], workspace_id: Buyer, current: Service
) -> dict[str, Any]:
    checkout = await current.checkout(workspace_id, purpose)
    return {
        "checkout_id": checkout.id,
        "state": checkout.state,
        "approval_url": checkout.approval_url,
        "mode": current.store.get(workspace_id).mode,
    }


@router.post("/buyer/complete")
async def buyer_complete(
    body: CompleteCheckout, workspace_id: Buyer, current: Service
) -> dict[str, str]:
    ws = await current.complete_checkout(workspace_id, body)
    return {"status": ws.change.state if ws.change else "paid"}
