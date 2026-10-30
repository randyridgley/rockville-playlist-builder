from playlist_builder.lastfm import Candidate
from playlist_builder.matching import is_junk, norm_title, score_candidate
from playlist_builder.models import DEFAULT_QUOTAS, Artist, Lineup, parse_quotas
from playlist_builder.selection import order_tracks, select_tracks


def cands(n: int, prefix: str = "Song") -> list[Candidate]:
    return [Candidate(title=f"{prefix} {i}", playcount=1000 - i, rank=i) for i in range(1, n + 1)]


LINEUP = Lineup(artists=[
    Artist(name="Headliner", tier=1),
    Artist(name="Sub", tier=2),
    Artist(name="Mid", tier=3),
    Artist(name="Small", tier=4),
    Artist(name="Unknown", tier=4),
])
CANDS = {"Headliner": cands(30), "Sub": cands(30), "Mid": cands(30), "Small": cands(30)}


def test_parse_quotas():
    q = parse_quotas("5+2, 3+1, 2, 1")
    assert (q[1].hits, q[1].deep_cuts, q[3].deep_cuts, q[4].total) == (5, 2, 0, 1)


def test_select_weights_by_tier_and_uses_claude_picks():
    picker = lambda reqs: {"Headliner": ["Song 20"], "Sub": ["Not A Real Song"]}
    tracks, missing = select_tracks(LINEUP, CANDS, DEFAULT_QUOTAS, picker)
    by_artist = {a: [t for t in tracks if t.artist == a] for a in CANDS}
    assert [len(by_artist[a]) for a in ("Headliner", "Sub", "Mid", "Small")] == [5, 3, 2, 1]
    assert missing == ["Unknown"]
    head_deep = [t.title for t in by_artist["Headliner"] if t.kind == "deep_cut"]
    assert head_deep == ["Song 20"]
    # Invented title falls back to a real candidate beyond the hits.
    sub_deep = [t for t in by_artist["Sub"] if t.kind == "deep_cut"][0]
    assert int(sub_deep.title.split()[-1]) > DEFAULT_QUOTAS[2].hits


def test_order_never_repeats_artist_back_to_back_and_opens_with_headliner():
    tracks, _ = select_tracks(LINEUP, CANDS, DEFAULT_QUOTAS, None)
    for seed in range(20):
        ordered = order_tracks(tracks, seed)
        assert sorted(t.title + t.artist for t in ordered) == sorted(t.title + t.artist for t in tracks)
        assert ordered[0].artist == "Headliner" and ordered[0].title == "Song 1"
        assert all(a.artist != b.artist for a, b in zip(ordered, ordered[1:]))


def test_title_normalization_and_junk():
    assert norm_title("Freak On a Leash (Remastered 2019)") == norm_title("Freak on a Leash")
    assert norm_title("Down With The Sickness - 2005 Remaster") == "downwiththesickness"
    assert is_junk("Them Bones (Live)")
    assert is_junk("Chop Suey! - Acoustic Version")
    assert not is_junk("Live Wire")  # 'Live' in the title itself is fine


def test_score_candidate_prefers_studio_and_checks_artist():
    studio = score_candidate("Korn", "Blind", ["Korn"], "Blind", "Korn")
    live = score_candidate("Korn", "Blind", ["Korn"], "Blind (Live)", "MTV Unplugged")
    wrong_artist = score_candidate("Korn", "Blind", ["Someone Else"], "Blind")
    assert studio > live > 0
    assert wrong_artist == 0
    assert score_candidate("blink-182", "All the Small Things", ["blink‐182"], "All The Small Things") >= 100
    assert score_candidate("The Offspring", "Self Esteem", ["Offspring"], "Self Esteem") >= 100


def test_order_spreads_heavily_weighted_artists():
    lineup = Lineup(artists=[Artist(name=f"A{i}", tier=1 if i < 4 else 4) for i in range(80)])
    candidates = {a.name: cands(30) for a in lineup.artists}
    tracks, _ = select_tracks(lineup, candidates, DEFAULT_QUOTAS, None)
    for seed in range(10):
        ordered = order_tracks(tracks, seed)
        assert all(a.artist != b.artist for a, b in zip(ordered, ordered[1:]))
        for headliner in ("A0", "A1", "A2", "A3"):
            pos = [i for i, t in enumerate(ordered) if t.artist == headliner]
            assert min(b - a for a, b in zip(pos, pos[1:])) >= 5, (seed, headliner, pos)
