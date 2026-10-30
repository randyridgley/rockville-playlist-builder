"""Last.fm top tracks: real play counts give the popularity curve that Spotify no longer exposes."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import httpx

from .config import require
from .matching import is_junk, norm_title

API_URL = "https://ws.audioscrobbler.com/2.0/"


@dataclass
class Candidate:
    title: str
    playcount: int
    rank: int


class LastFm:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or require("LASTFM_API_KEY")
        self.http = httpx.Client(timeout=20)

    def top_tracks(self, artist: str, limit: int = 50) -> list[Candidate]:
        """Top tracks with live/remix/duplicate variants filtered out, ranked by play count."""
        resp = self.http.get(API_URL, params={
            "method": "artist.gettoptracks",
            "artist": artist,
            "autocorrect": 1,
            "limit": limit,
            "api_key": self.api_key,
            "format": "json",
        })
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            return []

        seen: set[str] = set()
        out: list[Candidate] = []
        for t in data.get("toptracks", {}).get("track", []):
            title = t["name"]
            key = norm_title(title)
            if not key or key in seen or is_junk(title):
                continue
            seen.add(key)
            out.append(Candidate(title=title, playcount=int(t.get("playcount") or 0), rank=len(out) + 1))
        out.sort(key=lambda c: c.playcount, reverse=True)
        for i, c in enumerate(out, start=1):
            c.rank = i
        return out

    def top_tracks_many(self, artists: list[str], workers: int = 8) -> dict[str, list[Candidate]]:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = pool.map(self.top_tracks, artists)
        return dict(zip(artists, results))
