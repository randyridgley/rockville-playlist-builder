"""Turn a lineup plus per-artist candidates into a weighted, well-spread track list."""

import random
from collections import defaultdict
from typing import Callable

from .lastfm import Candidate
from .matching import norm_title
from .models import Artist, Lineup, TierQuota, Track

# Deep cuts come from beyond this many top tracks, so they aren't just hit #6.
DEEP_CUT_MIN_RANK_OFFSET = 4

DeepCutPicker = Callable[[dict[str, tuple[int, list[Candidate]]]], dict[str, list[str]]]


def select_tracks(
    lineup: Lineup,
    candidates: dict[str, list[Candidate]],
    quotas: dict[int, TierQuota],
    pick_deep_cuts: DeepCutPicker | None,
) -> tuple[list[Track], list[str]]:
    """Returns (tracks, artists with no catalog found)."""
    tracks: list[Track] = []
    missing: list[str] = []
    deep_requests: dict[str, tuple[int, list[Candidate]]] = {}

    # An act billed twice (e.g. on two days) counts once, at its best tier.
    best: dict[str, Artist] = {}
    for artist in lineup.artists:
        if artist.name not in best or artist.tier < best[artist.name].tier:
            best[artist.name] = artist

    for artist in best.values():
        quota = quotas[artist.tier]
        cands = candidates.get(artist.name) or []
        if not cands:
            missing.append(artist.name)
            continue
        hits = cands[: quota.hits]
        tracks += [
            Track(artist=artist.name, title=c.title, kind="hit", tier=artist.tier, playcount=c.playcount)
            for c in hits
        ]
        if quota.deep_cuts:
            pool = cands[quota.hits + DEEP_CUT_MIN_RANK_OFFSET :] or cands[quota.hits :]
            if pool:
                deep_requests[artist.name] = (quota.deep_cuts, pool)

    picked = pick_deep_cuts(deep_requests) if (pick_deep_cuts and deep_requests) else {}
    for artist_name, (n, pool) in deep_requests.items():
        tier = best[artist_name].tier
        by_title = {norm_title(c.title): c for c in pool}
        chosen = [by_title[k] for k in (norm_title(t) for t in picked.get(artist_name, [])) if k in by_title]
        # Fall back to the middle of the pool if Claude skipped this artist or invented titles.
        if len(chosen) < n:
            mid = len(pool) // 3
            for c in pool[mid:] + pool[:mid]:
                if len(chosen) >= n:
                    break
                if c not in chosen:
                    chosen.append(c)
        tracks += [
            Track(artist=artist_name, title=c.title, kind="deep_cut", tier=tier, playcount=c.playcount)
            for c in chosen[:n]
        ]
    return tracks, missing


def order_tracks(tracks: list[Track], seed: int | None = None) -> list[Track]:
    """Spread artists out so no artist plays twice in a row, opening with a headliner's biggest hit."""
    rng = random.Random(seed)
    by_artist: dict[str, list[Track]] = defaultdict(list)
    for t in tracks:
        by_artist[t.artist].append(t)
    for ts in by_artist.values():
        rng.shuffle(ts)

    opener = None
    openers = [t for t in tracks if t.tier == min(x.tier for x in tracks) and t.kind == "hit"]
    if openers:
        opener = max(openers, key=lambda t: t.playcount or 0)
        by_artist[opener.artist].remove(opener)

    # Give an artist with k tracks one slot in each 1/k of the playlist (random phase), so a
    # headliner's five songs land roughly a fifth of the way apart instead of clustering.
    keyed = []
    for artist, ts in by_artist.items():
        if opener and artist == opener.artist:
            # The opener already holds this artist's first slot; space the rest after it.
            slots = len(ts) + 1
            keyed += [((j + 1 + rng.uniform(-0.25, 0.25)) / slots, rng.random(), t) for j, t in enumerate(ts)]
            continue
        phase = rng.random()
        keyed += [((j + phase) / len(ts), rng.random(), t) for j, t in enumerate(ts)]
    keyed.sort(key=lambda k: (k[0], k[1]))
    ordered = ([opener] if opener else []) + [t for _, _, t in keyed]
    return _separate_same_artist(ordered, start=1 if opener else 0)


def _separate_same_artist(seq: list[Track], start: int) -> list[Track]:
    """Move any track that directly follows the same artist to the nearest slot where it doesn't."""

    def fits(k: int, artist: str) -> bool:
        return (k == 0 or seq[k - 1].artist != artist) and (k == len(seq) or seq[k].artist != artist)

    i = max(start, 1)
    for _ in range(len(seq) * 4):  # bounded; each move resolves a conflict in practice
        if i >= len(seq):
            break
        if seq[i].artist != seq[i - 1].artist:
            i += 1
            continue
        track = seq.pop(i)
        later = [k for k in range(i + 1, len(seq) + 1) if fits(k, track.artist)]
        earlier = [k for k in range(max(start, 1), i) if fits(k, track.artist)]
        seq.insert((later or earlier or [i])[0], track)
        if not later and not earlier:
            i += 1
    return seq
