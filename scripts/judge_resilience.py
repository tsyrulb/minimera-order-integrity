"""Browser fault cases shared by the source and container judge walkthroughs."""

import time
from collections.abc import Callable
from urllib.parse import urlencode

from playwright.sync_api import APIResponse, BrowserContext, Route, expect


def verify_resilience(
    base: str,
    new_context: Callable[[], BrowserContext],
    check: Callable[[str, bool], None],
) -> None:
    workspace_url = base + "/api/integrity/workspace"
    merchant = new_context().new_page()
    merchant.goto(base)
    merchant.get_by_role("button", name="Explore a safe change").click()
    expect(merchant.get_by_role("button", name="Approve this plan")).to_be_enabled()
    held: list[tuple[Route, APIResponse]] = []

    def hold_first_poll(route: Route) -> None:
        if not held:
            held.append((route, route.fetch()))
        else:
            route.continue_()

    merchant.route(workspace_url, hold_first_poll)
    merchant.evaluate("() => window.dispatchEvent(new Event('focus'))")
    deadline = time.monotonic() + 5
    while not held and time.monotonic() < deadline:
        merchant.wait_for_timeout(50)
    if not held:
        raise AssertionError("Could not stage the delayed workspace poll")
    merchant.get_by_role("button", name="Approve this plan").click()
    expect(merchant.get_by_role("link", name="Continue as buyer")).to_be_visible()
    with merchant.expect_response(workspace_url) as pending:
        held[0][0].fulfill(response=held[0][1])
    pending.value.body()
    merchant.unroute(workspace_url, hold_first_poll)
    merchant.wait_for_timeout(150)
    check(
        "delayed polling cannot revert a saved merchant approval",
        merchant.get_by_role("link", name="Continue as buyer").is_visible()
        and merchant.get_by_role("button", name="Approve this plan").count() == 0,
    )

    bootstrap = new_context().new_page()
    bootstrap.route(
        workspace_url,
        lambda route: route.fulfill(
            status=503,
            json={"error": {"code": "STORAGE_UNAVAILABLE", "message": "Synthetic storage outage"}},
        ),
    )
    bootstrap.goto(base)
    expect(bootstrap.get_by_role("alert")).to_contain_text("Synthetic storage outage")
    check("startup storage errors are visible instead of silently discarded", True)
    bootstrap.close()

    view = merchant.request.get(workspace_url).json()
    token = view["buyer_url"].rsplit("/", 1)[-1]
    checkout = merchant.request.post(
        base + "/api/integrity/buyer/checkout/replacement",
        headers={"X-Minimera-Buyer": token},
    )
    if checkout.status != 200:
        raise AssertionError("Could not prepare the cancellable simulated checkout")
    details = checkout.json()
    buyer = new_context().new_page()
    buyer.goto(base + view["buyer_url"])
    expect(buyer.get_by_role("button", name="Approve replacement · Simulation")).to_be_enabled()
    buyer.goto(
        base
        + "/return?"
        + urlencode(
            {"checkout": details["checkout_id"], "state": details["state"], "cancelled": "1"}
        )
    )
    expect(buyer.get_by_text("Checkout was cancelled.", exact=False)).to_be_visible()
    saved = merchant.request.get(workspace_url).json()["workspace"]
    check(
        "checkout cancellation leaves refund and replacement capture untouched",
        saved["change"]["refund"] is None
        and saved["change"]["replacement"]["capture_id"] is None
        and saved["change"]["state"] == "awaiting_buyer",
    )
    buyer_url = base + "/api/integrity/buyer"
    buyer_poll: list[tuple[Route, APIResponse]] = []

    def hold_buyer_poll(route: Route) -> None:
        if not buyer_poll:
            buyer_poll.append((route, route.fetch()))
        else:
            route.continue_()

    buyer.route(buyer_url, hold_buyer_poll)
    deadline = time.monotonic() + 5
    while not buyer_poll and time.monotonic() < deadline:
        buyer.wait_for_timeout(50)
    if not buyer_poll:
        raise AssertionError("Could not stage the delayed buyer poll")
    buyer.get_by_role("button", name="Approve replacement · Simulation").click()
    expect(buyer.get_by_role("heading", name="Your change is confirmed.")).to_be_visible()
    with buyer.expect_response(buyer_url) as pending:
        buyer_poll[0][0].fulfill(response=buyer_poll[0][1])
    pending.value.body()
    buyer.unroute(buyer_url, hold_buyer_poll)
    buyer.wait_for_timeout(150)
    check(
        "delayed buyer polling cannot hide a confirmed replacement payment",
        buyer.get_by_role("heading", name="Your change is confirmed.").is_visible()
        and buyer.get_by_role("button", name="Approve replacement · Simulation").count() == 0,
    )
    resumed = merchant.request.get(workspace_url).json()["workspace"]
    check(
        "a cancelled checkout can continue through the same saved order",
        resumed["change"]["state"] == "complete"
        and resumed["change"]["replacement"]["order_id"]
        == saved["change"]["replacement"]["order_id"],
    )
    buyer.close()

    def disconnected(route: Route) -> None:
        route.abort()

    merchant.route(workspace_url, disconnected)
    merchant.evaluate("() => window.dispatchEvent(new Event('focus'))")
    expect(merchant.get_by_text("Connection interrupted.", exact=False)).to_be_visible()
    check("a failed refresh visibly marks the saved state as disconnected", True)
    merchant.unroute(workspace_url, disconnected)
    merchant.get_by_role("button", name="Reconnect", exact=True).click()
    expect(merchant.get_by_text("Connection interrupted.", exact=False)).to_have_count(0)
    expect(merchant.get_by_role("button", name="Release corrected order")).to_be_visible()
    check("reconnecting restores the verified current workflow", True)
    merchant.close()

    studio = new_context().new_page()
    studio.goto(base)
    studio.get_by_role("button", name="Explore a safe change").click()
    expect(studio.get_by_role("button", name="Approve this plan")).to_be_enabled()
    identity = studio.request.get(workspace_url).json()["workspace"]["id"]

    def unavailable_chunk(route: Route) -> None:
        route.abort()

    studio.route("**/integrity-assets/Studio-*.js", unavailable_chunk)
    studio.get_by_role("link", name="Operations studio", exact=True).click()
    expect(
        studio.get_by_role("heading", name="Operations studio could not load", exact=True)
    ).to_be_visible()
    studio.set_viewport_size({"width": 390, "height": 844})
    studio.evaluate(
        "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
    )
    check(
        "a failed Studio module leaves mobile navigation and recovery usable",
        studio.get_by_role("link", name="Order integrity", exact=True).is_visible()
        and studio.get_by_role("button", name="Reload workspace").evaluate(
            "e => parseFloat(getComputedStyle(e).fontSize) >= 12"
        )
        and studio.evaluate("document.documentElement.scrollWidth <= innerWidth"),
    )
    studio.set_viewport_size({"width": 1366, "height": 768})
    studio.unroute("**/integrity-assets/Studio-*.js", unavailable_chunk)
    studio.get_by_role("button", name="Reload workspace", exact=True).click()
    expect(studio.get_by_text("What needs to stay in sync?", exact=True)).to_be_visible(
        timeout=20000
    )
    check(
        "Studio can reload without replacing the saved order",
        studio.request.get(workspace_url).json()["workspace"]["id"] == identity,
    )
    studio.close()
