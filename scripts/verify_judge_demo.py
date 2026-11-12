"""Replay the judge walkthrough with an owned local server and isolated demo state."""

import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener
from uuid import uuid4

from judge_resilience import verify_resilience
from playwright.sync_api import BrowserContext, Page, Route, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ntk.resources import memory_snapshot


def fingerprint(value: object) -> str:
    wire = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(wire.encode()).hexdigest()


def verify(base: str, output: Path, restart: Callable[[], None]) -> bool:
    report: dict[str, Any] = {
        "scope": "Local payment simulator, synthetic merchant/warehouse and recorded Bedrock.",
        "checks": {},
        "screens": {},
        "page_errors": [],
        "external_hosts": [],
    }
    axe_path = ROOT / "ui/node_modules/axe-core/axe.min.js"
    axe = axe_path.read_text() if axe_path.exists() else None
    report["accessibility_engine"] = "axe-core" if axe else "unavailable"

    def check(name: str, condition: bool) -> None:
        available = memory_snapshot()["available_mib"]
        if available is not None and available < 750:
            raise RuntimeError("Stopping owned browser checks to preserve host memory")
        report["checks"][name] = bool(condition)
        if not condition:
            raise AssertionError(name)
        print("PASS " + name, flush=True)

    def audit(page: Page, name: str) -> None:
        page.evaluate("document.fonts.ready")
        # Viewport changes can resolve before responsive layout has painted.
        page.evaluate(
            "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve(null))))"
        )
        screen = {
            "horizontal_overflow": page.evaluate(
                "document.documentElement.scrollWidth > innerWidth"
            ),
            "viewport": page.viewport_size,
        }
        if screen["horizontal_overflow"]:
            screen["overflow_elements"] = page.locator("body *").evaluate_all("""els =>
                els.filter(e => e.getBoundingClientRect().right > innerWidth + 1)
                   .slice(0, 12).map(e => ({tag: e.tagName, class: String(e.className),
                       right: e.getBoundingClientRect().right}))
            """)
        if axe:
            page.evaluate(axe)
            screen["accessibility_violations"] = page.evaluate("""async () => {
                const r = await axe.run(document, {runOnly: {type: 'tag',
                    values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']}});
                return r.violations.map(v => ({id: v.id, impact: v.impact,
                    targets: v.nodes.map(n => n.target)}));
            }""")
        page.screenshot(path=str(output / (name + ".png")), full_page=True)
        report["screens"][name] = screen
        check(
            name + " layout and automated accessibility",
            not screen["horizontal_overflow"] and not screen.get("accessibility_violations"),
        )

    def workspace(page: Page) -> dict[str, Any]:
        response = page.request.get(base + "/api/integrity/workspace")
        if response.status != 200:
            raise AssertionError("Merchant workspace unavailable")
        return response.json()

    def evidence_checks(evidence: dict[str, Any]) -> None:
        order, change, corrected = (
            evidence["order"],
            evidence["change"],
            evidence["fulfillment_order"],
        )
        check(
            "original fully refunded and replacement separately completed",
            order["payment"]["capture_status"] == "REFUNDED"
            and change["refund"]["status"] == "COMPLETED"
            and change["refund"]["cents"] == order["payment"]["cents"] == 12000
            and change["replacement"]["capture_status"] == "COMPLETED"
            and change["replacement"]["cents"] == 8400
            and change["refund"]["capture_id"] == order["payment"]["capture_id"]
            and change["replacement"]["capture_id"] != order["payment"]["capture_id"],
        )
        check(
            "corrected warehouse order matches approved destination and items",
            corrected["destination"] == change["destination"] == "office"
            and corrected["items"] == change["items"]
            and [item["sku"] for item in corrected["items"]] == ["TOTE"]
            and corrected["fulfillment"] == "released",
        )
        previous = "0" * 64
        for sequence, event in enumerate(evidence["events"], 1):
            body = {key: value for key, value in event.items() if key != "hash"}
            if (
                body["previous_hash"] != previous
                or body["sequence"] != sequence
                or fingerprint(body) != event["hash"]
            ):
                raise AssertionError("Exported event chain failed independent recomputation")
            previous = event["hash"]
        check(
            "downloaded event chain independently recomputed",
            previous == evidence["event_chain_hash"],
        )
        check(
            "export excludes buyer capabilities and labels simulation",
            "checkouts" not in evidence
            and "buyer_url" not in json.dumps(evidence)
            and evidence["mode"] == "simulation"
            and evidence["hardware_verified"] is False,
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-dev-shm-usage", "--disable-gpu", "--renderer-process-limit=2"],
        )
        contexts: list[BrowserContext] = []

        def context() -> BrowserContext:
            current = browser.new_context(
                viewport={"width": 1366, "height": 768}, reduced_motion="reduce"
            )
            contexts.append(current)

            def route(request: Route) -> None:
                parsed = urlsplit(request.request.url)
                if parsed.scheme in ("http", "https") and parsed.netloc != urlsplit(base).netloc:
                    report["external_hosts"].append(parsed.hostname)
                    request.abort()
                else:
                    request.continue_()

            current.route("**/*", route)
            current.on(
                "page",
                lambda page: page.on(
                    "pageerror", lambda error: report["page_errors"].append(type(error).__name__)
                ),
            )
            return current

        merchant = context().new_page()
        try:
            check("automated accessibility engine is available", axe is not None)
            status = merchant.request.get(base + "/api/integrity/status").json()
            check(
                "default mode requires no PayPal or model credentials",
                not status["sandbox_enabled"] and not status["fresh_ai_enabled"],
            )
            verify_resilience(base, context, check)
            merchant.goto(base)
            expect(merchant.get_by_role("button", name="Explore a safe change")).to_be_visible()
            audit(merchant, "01-welcome")
            merchant.get_by_role("button", name="Explore a safe change").click()
            expect(merchant.get_by_role("button", name="Approve this plan")).to_be_enabled()
            expect(merchant.get_by_text("Recorded Bedrock response", exact=True)).to_be_visible()
            initial = workspace(merchant)
            first_id = initial["workspace"]["id"]
            check(
                "customer request holds fulfillment before any refund",
                initial["workspace"]["order"]["fulfillment"] == "on_hold"
                and initial["workspace"]["change"]["refund"] is None,
            )
            check(
                "AI is a validated actual recording",
                initial["workspace"]["change"]["advice"]["source"] == "recorded_bedrock"
                and initial["workspace"]["change"]["advice"]["policy_agrees"] is True,
            )
            audit(merchant, "02-review")
            check(
                "review does not announce a verified financial outcome",
                merchant.locator(".outcome-verified").count() == 0,
            )
            merchant.get_by_role("button", name="See the 7 facts sent to the model").click()
            check(
                "model context shows exactly seven scoped facts",
                merchant.locator(".context-fact").count()
                == len(initial["model_context"]["facts"])
                == 7,
            )
            check(
                "model context excludes payment IDs and buyer capability",
                all(
                    value not in json.dumps(initial["model_context"])
                    for value in [
                        initial["workspace"]["order"]["payment"]["capture_id"],
                        initial["buyer_url"],
                    ]
                ),
            )
            merchant.get_by_role("button", name="Show cited fact F5").click()
            check(
                "citation leads to the cited fact",
                merchant.evaluate("document.activeElement.id === 'fact-F5'"),
            )
            merchant.keyboard.press("Escape")
            buyer_context = context()
            buyer = buyer_context.new_page()
            token = initial["buyer_url"].rsplit("/", 1)[-1]
            buyer_headers = {"X-Minimera-Buyer": token}
            denied = buyer.request.post(
                base + "/api/integrity/buyer/checkout/replacement", headers=buyer_headers
            )
            check("buyer cannot start payment before merchant approval", denied.status == 409)
            denied = buyer.request.post(
                base + "/api/integrity/approve",
                headers=buyer_headers,
                data={"snapshot_hash": initial["workspace"]["change"]["snapshot_hash"]},
            )
            check("separate buyer session cannot approve as merchant", denied.status == 403)
            merchant.get_by_role("link", name="Operations studio", exact=True).click()
            expect(merchant.get_by_text("What needs to stay in sync?", exact=True)).to_be_visible(
                timeout=20000
            )
            check(
                "Studio renders both custom widgets and event grid",
                merchant.locator(".studio-comparison").is_visible()
                and merchant.locator(".studio-decision").is_visible()
                and merchant.get_by_role("grid").count() > 0,
            )
            merchant.get_by_role("button", name="Explain this decision", exact=True).click()
            expect(merchant.get_by_text("Source: Recorded bedrock.", exact=False)).to_be_visible(
                timeout=15000
            )
            assistant_requests = []
            merchant.on(
                "request",
                lambda request: assistant_requests.append(request.post_data_json)
                if request.method == "POST"
                and urlsplit(request.url).path == "/api/integrity/assistant"
                else None,
            )
            question = merchant.get_by_placeholder("Ask the AI Assistant...")
            question.fill("What data does the model receive? judge-probe@example.test")
            merchant.get_by_role("button", name="Send message", exact=True).click()
            expect(
                merchant.get_by_text("Source: Deterministic context inspection.", exact=False)
            ).to_be_visible(timeout=15000)
            question.fill("What is the next step?")
            merchant.get_by_role("button", name="Send message", exact=True).click()
            expect(
                merchant.get_by_text("Source: Deterministic workflow state.", exact=False)
            ).to_be_visible(timeout=15000)
            check(
                "Studio sends only allowlisted intents and keeps free text in the browser",
                assistant_requests == [{"question": "privacy"}, {"question": "next_step"}],
            )
            merchant.get_by_role("button", name="Arrange dashboard", exact=True).click()
            expect(
                merchant.get_by_role("button", name="Finish arranging", exact=True)
            ).to_be_visible()
            merchant.get_by_role("button", name="Finish arranging", exact=True).click()
            transcript = merchant.get_by_role("region", name="Analyst conversation", exact=True)
            expect(transcript).to_have_attribute("tabindex", "0")
            transcript.focus()
            expect(transcript).to_be_focused()
            transcript.press("End")
            expect(transcript).not_to_have_js_property("scrollTop", 0)
            transcript.press("Home")
            expect(transcript).to_have_js_property("scrollTop", 0)
            check("long Studio conversation supports keyboard focus and scrolling", True)
            audit(merchant, "03-studio-analyst")
            merchant.get_by_role("link", name="Order integrity", exact=True).click()
            merchant.get_by_role("button", name="Approve this plan").click()
            expect(merchant.get_by_role("link", name="Continue as buyer")).to_be_visible()
            approved = workspace(merchant)["workspace"]["change"]
            check(
                "merchant approval binds the exact snapshot without moving money",
                approved["approved_hash"] == approved["snapshot_hash"]
                and approved["refund"] is None
                and approved["replacement"] is None,
            )
            buyer.goto(base + initial["buyer_url"])
            expect(
                buyer.get_by_role("button", name="Approve replacement · Simulation")
            ).to_be_enabled()
            check(
                "buyer browser has no merchant cookie",
                all(cookie["name"] != "minimera_merchant" for cookie in buyer_context.cookies()),
            )
            audit(buyer, "04-independent-buyer")
            completions = []
            buyer.on(
                "request",
                lambda request: completions.append(request.post_data_json)
                if request.method == "POST"
                and urlsplit(request.url).path == "/api/integrity/buyer/complete"
                else None,
            )
            buyer.get_by_role("button", name="Approve replacement · Simulation").click()
            expect(buyer.get_by_role("heading", name="Your change is confirmed.")).to_be_visible(
                timeout=15000
            )
            merchant.bring_to_front()
            expect(merchant.get_by_role("button", name="Release corrected order")).to_be_visible(
                timeout=10000
            )
            paid = workspace(merchant)["workspace"]
            check(
                "merchant observes buyer result while fulfillment remains held",
                paid["change"]["state"] == "complete"
                and paid["fulfillment_order"]["fulfillment"] == "ready",
            )
            duplicate = buyer.request.post(
                base + "/api/integrity/buyer/complete", headers=buyer_headers, data=completions[-1]
            )
            repeated = workspace(merchant)["workspace"]
            check(
                "duplicate checkout return keeps the same refund and capture",
                duplicate.status == 200
                and repeated["change"]["refund"]["refund_id"]
                == paid["change"]["refund"]["refund_id"]
                and repeated["change"]["replacement"]["capture_id"]
                == paid["change"]["replacement"]["capture_id"],
            )
            merchant.get_by_role("button", name="Release corrected order").click()
            expect(merchant.get_by_text("Corrected order queued", exact=True)).to_be_visible()
            check(
                "verified outcome presents both completed legs and customer difference",
                merchant.locator(".outcome-verified dd > span").all_text_contents()
                == ["$120.00", "$84.00", "$36.00"],
            )
            audit(merchant, "05-corrected-order-released")
            restart()
            merchant.reload()
            expect(merchant.get_by_text("Corrected order queued", exact=True)).to_be_visible()
            after_restart = workspace(merchant)["workspace"]
            check(
                "server restart preserves session, payment IDs and released order",
                after_restart["id"] == first_id
                and after_restart["change"]["refund"]["refund_id"]
                == paid["change"]["refund"]["refund_id"]
                and after_restart["change"]["replacement"]["capture_id"]
                == paid["change"]["replacement"]["capture_id"]
                and after_restart["fulfillment_order"]["fulfillment"] == "released",
            )
            merchant.get_by_role("link", name="Operations studio", exact=True).click()
            merchant.get_by_role("button", name="What is the next step?", exact=True).click()
            expect(
                merchant.get_by_text(
                    "The corrected order is already released to the synthetic warehouse queue.",
                    exact=False,
                )
            ).to_be_visible(timeout=15000)
            check("Studio analyst reflects the completed workflow", True)
            merchant.get_by_role("link", name="Evidence trail", exact=True).click()
            with merchant.expect_download() as pending:
                merchant.get_by_role("link", name="Download evidence").click()
            evidence = json.loads(Path(pending.value.path()).read_text())
            evidence_checks(evidence)
            (output / "completed-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
            audit(merchant, "06-exported-evidence")
            buyer_context.close()
            second = context().new_page()
            second.goto(base)
            expect(second.get_by_role("button", name="Explore a safe change")).to_be_visible()
            second.get_by_role("button", name="Explore a safe change").click()
            expect(second.get_by_role("button", name="Approve this plan")).to_be_enabled()
            check(
                "another visitor gets an independent workspace",
                workspace(second)["workspace"]["id"] != first_id
                and workspace(merchant)["workspace"]["id"] == first_id,
            )
            second.close()
            merchant.get_by_role("button", name="Explore scenarios", exact=True).click()
            merchant.get_by_role(
                "button", name="Start scenario: Already shipped", exact=True
            ).click()
            expect(
                merchant.get_by_role("heading", name="Order already shipped", exact=True)
            ).to_be_visible()
            shipped = workspace(merchant)["workspace"]
            check(
                "already-shipped scenario blocks approval without refund",
                merchant.get_by_role("button", name="Approve this plan").count() == 0
                and shipped["change"]["refund"] is None,
            )
            audit(merchant, "07-already-shipped")
            merchant.get_by_role("button", name="Explore scenarios", exact=True).click()
            merchant.get_by_role(
                "button", name="Start scenario: The order changed", exact=True
            ).click()
            expect(merchant.get_by_role("button", name="Approve this plan")).to_be_enabled()
            merchant.get_by_role("button", name="Approve this plan").click()
            expect(merchant.get_by_role("link", name="Continue as buyer")).to_be_visible()
            challenge = merchant.get_by_role(
                "button", name="What if the warehouse ships now?", exact=True
            )
            challenge_box = challenge.bounding_box()
            check(
                "warehouse challenge is visible after approval without scrolling",
                challenge.is_enabled()
                and challenge_box is not None
                and 0 <= challenge_box["y"]
                and challenge_box["y"] + challenge_box["height"]
                <= merchant.viewport_size["height"],
            )
            merchant.get_by_role(
                "button", name="What if the warehouse ships now?", exact=True
            ).click()
            expect(
                merchant.get_by_role("heading", name="Approval no longer valid", exact=True)
            ).to_be_visible()
            stale = workspace(merchant)["workspace"]
            check(
                "warehouse change invalidates approval before any payment",
                stale["change"]["state"] == "stale"
                and stale["change"]["refund"] is None
                and stale["change"]["replacement"] is None
                and merchant.get_by_role("link", name="Continue as buyer").count() == 0,
            )
            check(
                "stale outcome explains the changed warehouse and untouched payment legs",
                merchant.locator(".outcome-stopped h2").inner_text()
                == "Warehouse changed after approval."
                and merchant.locator(".outcome-stopped dd > span").all_text_contents()
                == ["Not sent", "Not captured", "Already shipped"],
            )
            merchant.set_viewport_size({"width": 390, "height": 844})
            audit(merchant, "08-mobile-stale-approval")
            merchant.get_by_role("button", name="Explore scenarios", exact=True).click()
            merchant.get_by_role("button", name="Start scenario: A safe change", exact=True).click()
            expect(merchant.get_by_role("button", name="Approve this plan")).to_be_enabled()
            check(
                "a judge can restart the example without deleting state",
                workspace(merchant)["workspace"]["id"]
                not in [first_id, stale["id"], shipped["id"]],
            )
            audit(merchant, "09-mobile-new-example")
            check("no browser JavaScript errors", not report["page_errors"])
            check("walkthrough needs no external browser requests", not report["external_hosts"])
        except Exception as error:
            message = str(error).split("Call log:")[0]
            report["failure"] = re.sub(r"/buyer/[A-Za-z0-9_.-]+", "/buyer/<redacted>", message)[
                :1600
            ]
            merchant.screenshot(path=str(output / "failure.png"), full_page=True)
            print("FAIL " + report["failure"], flush=True)
        finally:
            report["success"] = not report.get("failure") and all(report["checks"].values())
            report["external_hosts"] = sorted(set(report["external_hosts"]))
            (output / "browser-report.json").write_text(json.dumps(report, indent=2) + "\n")
            for current in contexts:
                current.close()
            browser.close()
    return bool(report["success"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    if not 1024 <= args.port <= 65535:
        parser.error("Use a local port between 1024 and 65535.")
    if not (ROOT / "ui/dist/index.html").exists():
        parser.error("Build the interface first: npm ci --prefix ui && npm run build --prefix ui")
    available = memory_snapshot()["available_mib"]
    if available is not None and available < 1800:
        parser.error("Browser verification needs at least 1800 MiB available host memory.")
    try:
        with socket.socket() as probe:
            # Allow an immediate repeat after our previous server closes its connections.
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", args.port))
    except OSError:
        parser.error(f"Port {args.port} is in use. Choose another, for example --port 8768.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]
    output = args.output_dir or ROOT / "runtime/judge-demo" / stamp
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    base = f"http://127.0.0.1:{args.port}"
    with (
        TemporaryDirectory(prefix="minimera-judge-") as state,
        (output / "server.log").open("w") as log,
    ):
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("NTK_", "AWS_", "PAYPAL_", "VITE_"))
        }
        env["NTK_RUNTIME_DIR"] = state
        process: subprocess.Popen[bytes] | None = None

        def stop() -> None:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

        def start() -> None:
            nonlocal process
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(ROOT / "scripts/serve_order_integrity.py"),
                    "--port",
                    str(args.port),
                ],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            opener = build_opener(ProxyHandler({}))
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("Owned demo server exited; inspect server.log.")
                try:
                    with opener.open(base + "/api/integrity/status", timeout=1) as response:
                        if response.status == 200:
                            return
                except (URLError, TimeoutError):
                    time.sleep(0.1)
            raise RuntimeError("Owned demo server did not become ready.")

        def restart() -> None:
            stop()
            start()

        try:
            start()
            success = verify(base, output, restart)
        finally:
            stop()
    print("Report: " + str(output / "browser-report.json"), flush=True)
    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()
