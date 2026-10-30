"""Tiny one-shot localhost server that serves the MusicKit JS login page and receives the Music User Token."""

import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse


def wait_for_browser(
    open_url: str,
    host: str,
    port: int,
    *,
    page_html: str | None = None,
    timeout: float = 300,
) -> dict[str, str]:
    """Open `open_url` and block until the browser hits the callback.

    GET with a query string (OAuth redirect) or POST /token with a text body (MusicKit page) both
    complete the flow. If `page_html` is given it is served at GET /.
    """
    result: dict[str, str] = {}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the terminal quiet
            pass

        def _reply(self, body: str, content_type: str = "text/html") -> None:
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            url = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            if page_html is not None and url.path == "/":
                self._reply(page_html)
                return
            if query:
                result.update(query)
                self._reply("<h2>Done. You can close this tab and return to the terminal.</h2>")
                done.set()
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            result["token"] = self.rfile.read(length).decode().strip()
            self._reply("ok", "text/plain")
            done.set()

    server = HTTPServer((host, port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        print(f"Opening your browser to sign in. If nothing opens, visit:\n  {open_url}")
        webbrowser.open(open_url)
        if not done.wait(timeout):
            raise TimeoutError("Timed out waiting for browser sign-in.")
    finally:
        server.shutdown()
    return result
