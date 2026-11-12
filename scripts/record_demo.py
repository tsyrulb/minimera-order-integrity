"""Record the functioning local app, with honest recorded-run captions. No publication."""

import asyncio
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from playwright.async_api import async_playwright, expect

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ntk.dataset import ROOT
from ntk.resources import memory_snapshot


def stamp(seconds):
    millis = round(seconds * 1000)
    return f"{millis // 3600000:02d}:{millis // 60000 % 60:02d}:{millis // 1000 % 60:02d},{millis % 1000:03d}"


async def main():
    async with httpx.AsyncClient(trust_env=False, timeout=30) as client:
        response = await client.get("http://127.0.0.1:8765/api/evaluation")
        report = response.raise_for_status().json()
    dataset = json.loads((ROOT / "data/cases.json").read_text())
    if report["status"] != "complete" or len(report["runs"]) != 90:
        raise SystemExit("Finish the real benchmark before recording the final demonstration.")
    if report.get("experiment_id") != "qwen3-next-bedrock-20261104":
        raise SystemExit(
            "Select the recorded Bedrock experiment for this version's video captions."
        )
    available = memory_snapshot()["available_mib"]
    if available is None or available < 2200:
        raise SystemExit(
            "Not enough memory headroom for a browser recording. Close an unused app and retry."
        )
    out = ROOT / "runtime" / datetime.now(timezone.utc).strftime("minimera-demo-%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True, exist_ok=False)
    scenes = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True, args=["--disable-dev-shm-usage", "--renderer-process-limit=1"]
        )
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            record_video_dir=str(out),
            record_video_size={"width": 1440, "height": 900},
        )
        page = await context.new_page()
        began = time.monotonic()

        async def scene(text, seconds):
            start = time.monotonic() - began
            print(json.dumps({"scene": text, "at": round(start)}), flush=True)
            await page.wait_for_timeout(seconds * 1000)
            scenes.append((start, time.monotonic() - began, text))

        await page.goto("http://127.0.0.1:8765/#method", wait_until="networkidle")
        await scene(
            "Minimera runs inside a merchant's backend; the buyer installs nothing.\nQwen3 Next on Amazon Bedrock receives only the selected context.",
            12,
        )
        await page.goto("http://127.0.0.1:8765/", wait_until="networkidle")
        await page.select_option("#case-select", "NTK-003")
        case_story = next(c["story"] for c in dataset["cases"] if c["id"] == "NTK-003")
        await expect(page.locator("#case-story")).to_have_text(case_story)
        await scene(
            "A synthetic item-not-received case contains customer identifiers\nand internal commercial fields that this task does not need.",
            12,
        )
        await page.click('[data-mode="full"]')
        await page.click("#analyze")
        await page.locator("#answer-content .recommendation").wait_for()
        await scene(
            "Full context sends all 30 synthetic fields.\nThis is a recorded real model run, labelled with its original timestamp.",
            12,
        )
        await page.click('[data-mode="masked"]')
        await scene(
            "The known-field masking baseline hides five personal fields.\nCommercial fields and the untrusted support note remain.",
            10,
        )
        await page.click('[data-mode="purpose"]')
        await page.click("#analyze")
        await page.locator("#answer-content .recommendation").wait_for()
        await scene(
            "Minimera retains 22 structured task facts and excludes eight unrelated fields.\nNo AI receives the raw profile to decide what to remove.",
            12,
        )
        await page.click('[data-context-tab="json"]')
        await scene(
            "Inspect the exact model request, including the task instructions and selected facts.\nReference labels are kept outside the model context.",
            10,
        )
        await page.click('[data-context-tab="ledger"]')
        await scene(
            "Every field decision has a reason. Unknown business facts remain unknown.\nThe policy covers this workflow, not arbitrary documents or every privacy risk.",
            10,
        )
        await page.click('[data-context-tab="facts"]')
        await page.click("#compare")
        await page.locator(".compare-card").nth(2).wait_for()
        await scene(
            "Compare the same task and model across all three inputs.\nActual recommendations, evidence checks and errors stay visible.",
            12,
        )
        await page.select_option("#case-select", "paypal-sandbox")
        await page.locator("#case-origin").filter(has_text="PayPal").wait_for()
        if await page.locator("#refresh-paypal").is_visible():
            await page.click("#refresh-paypal")
            await expect(page.locator("#refresh-paypal")).to_be_enabled(timeout=60000)
        await page.click("#analyze")
        await page.locator("#answer-content .recommendation").wait_for()
        await scene(
            "The PayPal adapter verifies the order, capture and dispute link.\nBedrock analyzes 17 normalized business facts; profiles and messages stay out.",
            12,
        )
        await page.goto("http://127.0.0.1:8765/#evaluation", wait_until="networkidle")
        await page.locator(".evaluation-cards").wait_for()
        await scene(
            "Thirty synthetic fixtures: 20 development, 10 reused reporting cases.\nMinimera matches 5 of 10 reporting actions; full context matches 3 of 10.",
            12,
        )
        await page.locator(".method-note").first.scroll_into_view_if_needed()
        await scene(
            "The model makes mistakes. Failed workflow gates are reported explicitly.\nThese labels and checks are not independent validation or compliance certification.",
            10,
        )
        await page.goto("http://127.0.0.1:8765/", wait_until="networkidle")
        await page.click("#analyze")
        await page.locator("#answer-content .recommendation").wait_for()
        await page.locator(".run-details").click()
        await page.locator(".answer-actions").scroll_into_view_if_needed()
        async with page.expect_download() as pending:
            await page.get_by_role("button", name="Export evidence").click()
        download = await pending.value
        await download.save_as(str(out / "example-evidence.json"))
        await scene(
            "Export purpose, field decisions, exact requests, hashes and model versions.\nThe goal: repeatable evidence when a policy, prompt or model changes.",
            12,
        )
        video = page.video
        await context.close()
        source = Path(await video.path())
        await browser.close()
    raw = out / "demo.webm"
    source.rename(raw)
    subtitles = "\n\n".join(
        f"{i}\n{stamp(start)} --> {stamp(end)}\n{text}"
        for i, (start, end, text) in enumerate(scenes, 1)
    )
    (out / "demo.en.srt").write_text(subtitles + "\n")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        import imageio_ffmpeg

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    command = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-n",
        "-threads",
        "1",
        "-i",
        "demo.webm",
        "-filter_threads",
        "1",
        "-vf",
        "subtitles=demo.en.srt:force_style='FontName=DejaVu Sans,FontSize=9,Outline=1,Shadow=0,MarginV=8,BackColour=&H90000000,BorderStyle=3'",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-threads",
        "1",
        "-an",
        "demo.mp4",
    ]
    subprocess.run(command, cwd=out, check=True)
    if shutil.which("ffprobe"):
        duration = float(
            subprocess.check_output(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    "demo.mp4",
                ],
                cwd=out,
                text=True,
            )
        )
    else:
        info = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", "demo.mp4"], cwd=out, capture_output=True, text=True
        )
        matched = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", info.stderr)
        if not matched:
            raise SystemExit("Could not verify the generated video's duration.")
        duration = int(matched[1]) * 3600 + int(matched[2]) * 60 + float(matched[3])
    if duration >= 180:
        raise SystemExit(
            "Recording exceeds the hackathon limit; review the recording before publication."
        )
    (out / "PROVENANCE.json").write_text(
        json.dumps(
            {
                "application": "Minimera",
                "model": report["model"],
                "provider": report.get("provider"),
                "experiment_id": report.get("experiment_id"),
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "duration_seconds": duration,
                "source": "Actual local application interaction; recorded model outputs explicitly labelled; no fake responses or network mocks",
                "captions": "English captions, no music or narration",
                "published": False,
                "scene_count": len(scenes),
            },
            indent=2,
        )
    )
    print(
        json.dumps(
            {
                "video": str(out / "demo.mp4"),
                "subtitles": str(out / "demo.en.srt"),
                "duration_seconds": duration,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
