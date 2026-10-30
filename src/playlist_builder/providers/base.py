from dataclasses import dataclass, field
from typing import Protocol

from ..models import Track


@dataclass
class PlaylistResult:
    provider: str
    url: str | None
    added: int
    not_found: list[Track] = field(default_factory=list)


class Provider(Protocol):
    name: str

    def authenticate(self) -> None: ...

    def find(self, track: Track) -> str | None:
        """Return the provider's ID/URI for the best catalog match, or None."""
        ...

    def create_playlist(self, name: str, description: str, track_ids: list[str]) -> str | None:
        """Create the playlist and return a URL if one is available."""
        ...


def build_playlist(
    provider: Provider, name: str, description: str, tracks: list[Track], progress=None, limit: int | None = None
) -> PlaylistResult:
    """Match tracks in order and create the playlist. With `limit`, stop once that many have matched,
    so tracks after it act as spares for ones the catalog doesn't have."""
    ids, missing = [], []
    for track in tracks:
        if limit is not None and len(ids) >= limit:
            break
        track_id = provider.find(track)
        if track_id and track_id not in ids:
            ids.append(track_id)
        elif not track_id:
            missing.append(track)
        if progress:
            progress()
    url = provider.create_playlist(name, description, ids)
    return PlaylistResult(provider=provider.name, url=url, added=len(ids), not_found=missing)
