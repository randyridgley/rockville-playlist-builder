"""Tiny one-shot localhost server that serves the MusicKit JS login page and receives the Music User Token."""

import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse


def wait_for_browser(host: str, port: int, page_html: str, *, timeout: float = 300) -> str:
    """Serve `page_html` and block until it POSTs the token back. Returns the token.

    The page lives under a random one-time path, and the page must POST to `token` relative to
    it. Requests with any other Host header are rejected, which blocks DNS-rebinding pages from
    reading the page (it embeds the developer token), and the unguessable path stops other sites
    from posting a forged token.
    """
    nonce = secrets.token_urlsafe(24)
    page_path, token_path = f"/{nonce}/", f"/{nonce}/token"
    allowed_hosts = {f"{host}:{port}", f"127.0.0.1:{port}", f"localhost:{port}"}
    result: dict[str, str] = {}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the terminal quiet
            pass

        def _reply(self, status: int, body: str = "", content_type: str = "text/plain") -> None:
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _host_ok(self) -> bool:
            return self.headers.get("Host", "") in allowed_hosts

        def do_GET(self):
            if self._host_ok() and urlparse(self.path).path == page_path:
                self._reply(200, page_html, "text/html")
            else:
                self._reply(404)

        def do_POST(self):
            origin = self.headers.get("Origin")
            if not self._host_ok() or self.path != token_path or (origin and urlparse(origin).netloc not in allowed_hosts):
                self._reply(403)
                return
            length = min(int(self.headers.get("Content-Length", 0)), 16_384)
            token = self.rfile.read(length).decode(errors="replace").strip()
            if not token:
                self._reply(400)
                return
            result["token"] = token
            self._reply(200, "ok")
            done.set()

    server = HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    open_url = f"http://{host}:{port}{page_path}"
    try:
        print(f"Opening your browser to sign in. If nothing opens, visit:\n  {open_url}")
        webbrowser.open(open_url)
        if not done.wait(timeout):
            raise TimeoutError("Timed out waiting for browser sign-in.")
    finally:
        server.shutdown()
    return result["token"]
