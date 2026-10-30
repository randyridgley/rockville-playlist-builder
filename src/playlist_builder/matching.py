"""Title/artist normalization shared by Last.fm filtering and streaming-catalog matching."""

import re
import unicodedata

# Variants that are almost never what you want on a "best of" playlist.
JUNK_PATTERN = re.compile(
    r"\b(live|remix|mix|demo|acoustic|instrumental|karaoke|commentary|interview|"
    r"edit|version|session|rehearsal|bootleg|cover|tribute|reprise|8-bit|lullaby)\b",
    re.IGNORECASE,
)
_SUFFIX = re.compile(r"\s+[-–—]\s+.*$")
_PARENS = re.compile(r"[\(\[].*?[\)\]]")


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.casefold().replace("&", " and ")


def norm_artist(name: str) -> str:
    name = _fold(name)
    name = re.sub(r"^the\s+", "", name.strip())
    return re.sub(r"[^a-z0-9]", "", name)


def norm_title(title: str) -> str:
    """Strip '(Remastered 2011)', ' - Single Version' etc. so variants collapse together."""
    title = _SUFFIX.sub("", title)
    title = _PARENS.sub("", title)
    return re.sub(r"[^a-z0-9]", "", _fold(title))


def is_junk(title: str) -> bool:
    """True if the title's qualifiers mark it as a live cut, remix, demo, etc."""
    qualifiers = " ".join(_PARENS.findall(title)) + " ".join(_SUFFIX.findall(title))
    return bool(JUNK_PATTERN.search(qualifiers))


def artist_matches(wanted: str, candidate: str) -> bool:
    a, b = norm_artist(wanted), norm_artist(candidate)
    if not a or not b:
        return False
    return a == b or (len(a) >= 4 and a in b) or (len(b) >= 4 and b in a)


def score_candidate(artist: str, title: str, cand_artists: list[str], cand_title: str, cand_album: str = "") -> int:
    """Score a catalog search result; <= 0 means reject."""
    if not any(artist_matches(artist, ca) for ca in cand_artists):
        return 0
    want, got = norm_title(title), norm_title(cand_title)
    if want == got:
        score = 100
    elif want and (want in got or got in want):
        score = 60
    else:
        return 0
    # Penalize live/remix variants unless the requested title itself was one.
    if not is_junk(title):
        if is_junk(cand_title):
            score -= 40
        if re.search(r"\blive\b", cand_album, re.IGNORECASE):
            score -= 30
    if norm_artist(cand_artists[0]) == norm_artist(artist):
        score += 5  # primary artist rather than a feature
    return score
