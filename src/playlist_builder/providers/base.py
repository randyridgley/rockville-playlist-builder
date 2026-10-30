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


class AppendableProvider(Provider, Protocol):
    def find_playlist(self, name: str) -> str | None: ...

    def playlist_tracks(self, playlist_id: str) -> list[tuple[str, str, str | None]]: ...

    def add_tracks(self, playlist_id: str, track_ids: list[str]) -> None: ...


def _match(provider: Provider, tracks: list[Track], progress, limit: int | None, skip_ids=()) -> tuple[list[str], list[Track]]:
    ids, missing, skip = [], [], set(skip_ids)
    for track in tracks:
        if limit is not None and len(ids) >= limit:
            break
        track_id = provider.find(track)
        if track_id and track_id not in ids and track_id not in skip:
            ids.append(track_id)
        elif not track_id:
            missing.append(track)
        if progress:
            progress()
    return ids, missing


def add_to_playlist(
    provider: AppendableProvider, playlist_id: str, tracks: list[Track], progress=None,
    limit: int | None = None, skip_ids=(),
) -> PlaylistResult:
    """Match tracks and append them to an existing playlist, skipping songs already on it (`skip_ids`)."""
    ids, missing = _match(provider, tracks, progress, limit, skip_ids)
    if ids:
        provider.add_tracks(playlist_id, ids)
    return PlaylistResult(provider=provider.name, url=None, added=len(ids), not_found=missing)


def build_playlist(
    provider: Provider, name: str, description: str, tracks: list[Track], progress=None, limit: int | None = None
) -> PlaylistResult:
    """Match tracks in order and create the playlist. With `limit`, stop once that many have matched,
    so tracks after it act as spares for ones the catalog doesn't have."""
    ids, missing = _match(provider, tracks, progress, limit)
    url = provider.create_playlist(name, description, ids)
    return PlaylistResult(provider=provider.name, url=url, added=len(ids), not_found=missing)
