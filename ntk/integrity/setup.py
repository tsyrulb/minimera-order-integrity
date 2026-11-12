"""Single-use, loopback-only credential form. Secrets never enter chat or logs."""

import html
import os
import re
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import httpx

from .payments import BASE


def credential_values(body: bytes) -> tuple[str, str]:
    fields = parse_qs(body.decode("utf-8", errors="strict"), strict_parsing=True)
    if set(fields) != {"client_id", "client_secret"} or any(len(v) != 1 for v in fields.values()):
        raise ValueError("Use the two Sandbox credential fields.")
    values = fields["client_id"][0].strip(), fields["client_secret"][0].strip()
    if any(not re.fullmatch(r"[A-Za-z0-9_-]{8,1024}", value) for value in values):
        raise ValueError("Enter the Sandbox app credentials without spaces or quotes.")
    return values


def save_credentials(path: Path, client_id: str, secret: str) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    temporary = path.with_name("." + path.name + "." + secrets.token_hex(8))
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(
                f"PAYPAL_SANDBOX_CLIENT_ID={client_id}\nPAYPAL_SANDBOX_CLIENT_SECRET={secret}\n"
            )
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _page(form_path: str, message: str = "", *, complete: bool = False) -> bytes:
    content = (
        '<div class="success">Connection verified and saved locally.</div><p>You can close this window. The credential form has stopped.</p>'
        if complete
        else f"""<p>Connect your <strong>PayPal Sandbox app</strong> for test orders and refunds.</p>
        <p class="note">Both values go directly from this local window to the local setup process. The process checks them with PayPal Sandbox and saves an owner-only file in this project's ignored private folder.</p>
        <form method="post" action="{html.escape(form_path, quote=True)}" autocomplete="off">
        <label for="client">Sandbox Client ID</label><input id="client" type="password" name="client_id" required autocomplete="off" spellcheck="false" maxlength="1024">
        <label for="secret">Sandbox Secret</label><input id="secret" type="password" name="client_secret" required autocomplete="off" spellcheck="false" maxlength="1024">
        <button type="submit">Verify and save Sandbox connection</button></form>
        <p class="note">Use test credentials from developer.paypal.com. This form accepts no production endpoint and starts no payment.</p>"""
    )
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Minimera · Local Sandbox setup</title>
    <style>body{{font:15px/1.7 system-ui,sans-serif;background:#f7f8fc;color:#343747;margin:0;padding:60px 20px}}main{{max-width:440px;margin:auto;padding:35px;background:#fff;border:1px solid #e5e6ee;border-radius:14px}}h1{{font-size:27px;letter-spacing:-1px}}small{{color:#6351bb;font-weight:600}}p{{color:#6d7183}}.note{{font-size:12px;line-height:1.8}}label{{display:block;font-size:12px;margin:20px 0 7px}}input{{width:100%;padding:13px;box-sizing:border-box;border:1px solid #d9dbe7;border-radius:7px;font:14px system-ui}}button{{margin-top:25px;background:#6051cf;border:0;color:#fff;padding:14px;width:100%;border-radius:7px;font-weight:600;cursor:pointer}}.error{{color:#946032}}.success{{padding:15px;background:#eaf6ef;color:#316e4b;border-radius:7px}}</style>
    <main><small>LOCAL SETUP · NO LIVE MONEY</small><h1>minimera.</h1><p class="error" role="status">{html.escape(message)}</p>{content}</main></html>""".encode()


def serve_setup(path: Path, *, open_browser: bool = False, duration: int = 600) -> bool:
    finished = threading.Event()
    form_path = "/connect/" + secrets.token_urlsafe(32)
    origin = ""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def respond(self, status: int, message: str = "", complete: bool = False) -> None:
            body = _page(form_path, message, complete=complete)
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.headers.get("Host") != origin.removeprefix("http://") or self.path != form_path:
                self.respond(404, "This setup link is unavailable.")
                return
            self.respond(200)

        def do_POST(self) -> None:
            if (
                self.headers.get("Origin") != origin
                or self.path != form_path
                or self.headers.get("Host") != origin.removeprefix("http://")
            ):
                self.respond(403, "Use the local setup window.")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if (
                    not 1 <= length <= 4096
                    or self.headers.get_content_type() != "application/x-www-form-urlencoded"
                ):
                    raise ValueError("Invalid form")
                client_id, secret = credential_values(self.rfile.read(length))
                with httpx.Client(
                    timeout=httpx.Timeout(25, connect=10), trust_env=False, follow_redirects=False
                ) as client:
                    response = client.post(
                        BASE + "/v1/oauth2/token",
                        auth=(client_id, secret),
                        data={"grant_type": "client_credentials"},
                    )
                    response.raise_for_status()
                    if len(response.content) > 32000 or not isinstance(
                        response.json().get("access_token"), str
                    ):
                        raise ValueError("Invalid token response")
                save_credentials(path, client_id, secret)
            except (ValueError, UnicodeError, httpx.HTTPError, OSError):
                self.respond(
                    400,
                    "The Sandbox connection could not be verified or saved. Check the app's test credentials and try again.",
                )
                return
            self.respond(200, complete=True)
            finished.set()

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        server.timeout = 0.5
        origin = f"http://127.0.0.1:{server.server_port}"
        url = origin + form_path
        print("Local Sandbox setup: " + url, flush=True)
        if open_browser:
            webbrowser.open(url, new=1)
        deadline = time.monotonic() + duration
        while not finished.is_set() and time.monotonic() < deadline:
            server.handle_request()
    return finished.is_set()
