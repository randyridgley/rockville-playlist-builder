from playlist_builder.models import Track
from playlist_builder.providers.base import build_playlist


class FakeProvider:
    name = "Fake"

    def __init__(self, catalog):
        self.catalog = catalog
        self.created = None

    def find(self, track):
        return self.catalog.get(track.title)

    def create_playlist(self, name, description, track_ids):
        self.created = track_ids
        return None


def test_limit_uses_spares_for_missing_tracks():
    tracks = [Track(artist="A", title=t, kind="hit", tier=1) for t in ("one", "gone", "two", "three", "four")]
    provider = FakeProvider({"one": "1", "two": "2", "three": "3", "four": "4"})
    result = build_playlist(provider, "x", "y", tracks, limit=3)
    assert provider.created == ["1", "2", "3"]
    assert result.added == 3
    assert [t.title for t in result.not_found] == ["gone"]


def test_add_to_playlist_skips_songs_already_on_it():
    from playlist_builder.providers.base import add_to_playlist

    class Appendable(FakeProvider):
        added = None

        def add_tracks(self, playlist_id, track_ids):
            self.added = (playlist_id, track_ids)

    tracks = [Track(artist="A", title=t, kind="hit", tier=1) for t in ("one", "two", "three")]
    provider = Appendable({"one": "1", "two": "2", "three": "3"})
    result = add_to_playlist(provider, "p.1", tracks, limit=2, skip_ids={"1"})
    assert provider.added == ("p.1", ["2", "3"])
    assert result.added == 2
