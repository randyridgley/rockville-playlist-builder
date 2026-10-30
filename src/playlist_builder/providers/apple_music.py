"""Apple Music API client.

The developer token is a short-lived ES256 JWT signed with your MusicKit private key (.p8). The
Music User Token comes from MusicKit JS: we serve a one-button page on localhost, you sign in with
your Apple ID, and the page posts the token back to the CLI.
"""

import json
import os
import time
from pathlib import Path

import httpx
import jwt

from ..config import CACHE_DIR, optional, require
from ..local_server import wait_for_browser
from ..matching import score_candidate
from ..models import Track

API = "https://api.music.apple.com/v1"
TOKEN_FILE = CACHE_DIR / "apple_music_user_token.json"
LOGIN_HOST, LOGIN_PORT = "localhost", 8889

LOGIN_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Playlist Builder: Apple Music sign-in</title>
<script src="https://js-cdn.music.apple.com/musickit/v3/musickit.js" async></script>
<style>body{font-family:-apple-system,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem}
button{font-size:1.1rem;padding:.7rem 1.4rem;border-radius:.5rem;border:0;background:#fa2d48;color:#fff;cursor:pointer}</style>
</head><body>
<h2>Connect Apple Music</h2>
<p>Sign in so Playlist Builder can create a playlist in your library.</p>
<button id="go" disabled>Loading MusicKit…</button>
<p id="status"></p>
<script>
document.addEventListener('musickitloaded', async () => {
  await MusicKit.configure({developerToken: %(token)s, app: {name: 'Playlist Builder', build: '1.0'}});
  const btn = document.getElementById('go');
  btn.disabled = false; btn.textContent = 'Sign in with Apple Music';
  btn.onclick = async () => {
    try {
      const userToken = await MusicKit.getInstance().authorize();
      const resp = await fetch('token', {method: 'POST', body: userToken});
      if (!resp.ok) throw new Error('local server rejected the token (' + resp.status + ')');
      document.getElementById('status').textContent = 'Done. You can close this tab.';
    } catch (e) {
      document.getElementById('status').textContent = 'Sign-in failed: ' + e;
    }
  };
});
</script></body></html>"""


def _write_private(path: Path, text: str) -> None:
    """Write a secret file that is owner-only from the moment it exists."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(path, 0o600)  # O_CREAT's mode doesn't apply if the file already existed


class AppleMusic:
    name = "Apple Music"

    def __init__(self):
        self.team_id = require("APPLE_TEAM_ID")
        self.key_id = require("APPLE_KEY_ID")
        self.private_key = Path(require("APPLE_PRIVATE_KEY_PATH")).expanduser().read_text()
        self.storefront = optional("APPLE_STOREFRONT")
        self.http = httpx.Client(timeout=20)
        self.developer_token = self._developer_token()
        self.user_token: str | None = None

    def _developer_token(self) -> str:
        now = int(time.time())
        return jwt.encode(
            {"iss": self.team_id, "iat": now, "exp": now + 12 * 3600},
            self.private_key,
            algorithm="ES256",
            headers={"kid": self.key_id},
        )

    def authenticate(self) -> None:
        if TOKEN_FILE.exists():
            self.user_token = json.loads(TOKEN_FILE.read_text())["token"]
            try:
                self._storefront()
                return
            except httpx.HTTPStatusError as e:
                if e.response.status_code not in (401, 403):
                    raise
        self._login()
        self._storefront()

    def _login(self) -> None:
        page = LOGIN_PAGE % {"token": json.dumps(self.developer_token)}
        self.user_token = wait_for_browser(LOGIN_HOST, LOGIN_PORT, page)
        _write_private(TOKEN_FILE, json.dumps({"token": self.user_token}))

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.developer_token}", "Music-User-Token": self.user_token or ""}
        for attempt in range(6):
            resp = self.http.request(method, API + path, headers=headers, **kwargs)
            # Apple returns sporadic 401s (notably for a newly created key while it propagates),
            # so retry those too; a genuinely bad token still fails after the last attempt.
            # Only retry 5xx on GETs: a POST that 5xx'd may have created the playlist anyway.
            retryable = (401, 429, 500, 503) if method == "GET" else (401, 429)
            if resp.status_code in retryable and attempt < 5:
                time.sleep(min(2 ** attempt * 0.5, 8))
                continue
            resp.raise_for_status()
            return resp
        resp.raise_for_status()
        return resp

    def _storefront(self) -> str:
        if not self.storefront:
            self.storefront = self._request("GET", "/me/storefront").json()["data"][0]["id"]
        else:
            self._request("GET", "/me/storefront")  # validates the user token
        return self.storefront

    def find(self, track: Track) -> str | None:
        resp = self._request("GET", f"/catalog/{self.storefront}/search", params={
            "term": f"{track.artist} {track.title}", "types": "songs", "limit": 10,
        })
        best, best_score = None, 0
        for song in resp.json().get("results", {}).get("songs", {}).get("data", []):
            attrs = song.get("attributes", {})
            score = score_candidate(
                track.artist, track.title, [attrs.get("artistName", "")],
                attrs.get("name", ""), attrs.get("albumName", ""),
            )
            if score > best_score:
                best, best_score = song["id"], score
        return best

    def create_playlist(self, name: str, description: str, track_ids: list[str]) -> str | None:
        songs = [{"id": i, "type": "songs"} for i in track_ids]
        resp = self._request("POST", "/me/library/playlists", json={
            "attributes": {"name": name, "description": description},
            "relationships": {"tracks": {"data": songs[:100]}},
        })
        playlist_id = resp.json()["data"][0]["id"]
        for i in range(100, len(songs), 100):
            self._request("POST", f"/me/library/playlists/{playlist_id}/tracks", json={"data": songs[i : i + 100]})
        # Library playlists have no public URL until shared from the Music app.
        return None
