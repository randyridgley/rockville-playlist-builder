"""Claude calls: read the lineup poster, and pick deep cuts from Last.fm candidates."""

import base64
import io
import json
from pathlib import Path

import anthropic
from PIL import Image
from pydantic import BaseModel

from .config import CLAUDE_MODEL
from .lastfm import Candidate
from .models import Artist, Lineup

# Base64 adds ~33%; the API caps images at 5 MB encoded.
MAX_IMAGE_BYTES = 3_700_000
MAX_EDGE = 4000

# Server-side fallback re-runs a declined request on another model inside the same call.
FALLBACK_KWARGS = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}


class _ExtractedArtist(BaseModel):
    name: str
    tier: int
    day: str | None
    stage: str | None


class _Extraction(BaseModel):
    festival: str | None
    year: int | None
    artists: list[_ExtractedArtist]


class _ArtistPicks(BaseModel):
    artist: str
    titles: list[str]


class _DeepCuts(BaseModel):
    picks: list[_ArtistPicks]


EXTRACT_PROMPT = """This is a music festival lineup poster. Extract every performing act and rank how \
prominently each one is billed.

Assign each act a tier from 1 (biggest) to 4 (smallest):
- tier 1: headliners, the top-billed act(s) of the whole festival or of each day
- tier 2: sub-headliners, the next clearly-larger names or logos
- tier 3: mid-card acts
- tier 4: the smallest print

Judge prominence the way a fan reading the poster would: text or logo size, vertical position, and \
color emphasis all count. Many posters are grids (days across, stages down, or the reverse). In a grid, \
the first or main stage outranks later stages, and within each stage block the top act outranks the \
rest. A secondary stage's headliner is usually tier 2, its logo-sized acts tier 3, and its small \
text tier 4, while the main stage's headliner is tier 1 and its logo-sized acts tier 2. Keep the tiers \
roughly pyramid-shaped: few tier-1 acts and the most tier-4 acts.

Rules:
- List acts in poster order.
- Copy each name exactly as printed, but in normal capitalization (posters are often ALL CAPS: write \
"Sleep Token", not "SLEEP TOKEN"). Keep stylized spellings like "blink-182" or "$uicideboy$". Read \
stylized logos as the band's real name (for example, a logo reading "BAD OIIIENS" is "Bad Omens").
- Stylized fonts often blur the letter O and the digit 0, or I and 1. Use the band's real spelling: \
"HO99O9" is "Ho99o9" (letters O, digits 9), not "H09909".
- Drop billing extras from the name, such as "celebrating <album>" or a member's other bands written in \
small text ("Chad Gray: Mudvayne / Hellyeah" becomes "Chad Gray").
- Skip names that are blurred, redacted, or unreadable. Never guess them.
- Set `day` to the day label (e.g. "Friday") and `stage` to the stage name if the poster shows them; \
otherwise null.
- Never list sponsors, stage or day labels, hosts, "+ more", ticket info, or dates as acts.
- If the festival name or year is printed, fill them in; otherwise null."""

DEEP_CUT_PROMPT = """You are curating a festival-preview playlist. For each artist below I've listed tracks from their \
catalog (from Last.fm) with play counts. Their biggest hits are already on the playlist, so choose \
{instructions} for each artist.

A good deep cut is a fan favorite or a strong album track that a casual listener might not know, \
and that shows a different side of the band, ideally one they play live. Avoid filler, intros/interludes, \
skits, live versions, remixes, re-recordings, and near-duplicates of the hits.

Choose only from the titles listed, copying each title exactly as written.

{payload}"""


def _image_block(path: Path) -> dict:
    raw = path.read_bytes()
    img = Image.open(io.BytesIO(raw))
    media_type = Image.MIME.get(img.format or "", "")
    if len(raw) > MAX_IMAGE_BYTES or max(img.size) > MAX_EDGE or media_type not in (
        "image/jpeg", "image/png", "image/gif", "image/webp"
    ):
        img = img.convert("RGB")
        img.thumbnail((MAX_EDGE, MAX_EDGE))
        quality = 92
        while True:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            if buf.tell() <= MAX_IMAGE_BYTES or quality <= 50:
                break
            quality -= 10
        raw, media_type = buf.getvalue(), "image/jpeg"
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": base64.standard_b64encode(raw).decode()},
    }


class Claude:
    def __init__(self, client: anthropic.Anthropic | None = None):
        self.client = client or anthropic.Anthropic()

    def _parse(self, content: list | str, schema: type[BaseModel], effort: str):
        with self.client.beta.messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=64000,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            output_format=schema,
            messages=[{"role": "user", "content": content}],
            **FALLBACK_KWARGS,
        ) as stream:
            message = stream.get_final_message()
        if message.stop_reason == "refusal":
            raise RuntimeError(f"Claude declined the request: {message.stop_details}")
        if message.stop_reason == "max_tokens":
            raise RuntimeError("Claude's response was cut off (max_tokens).")
        if message.parsed_output is None:
            raise RuntimeError("Claude returned no structured output.")
        return message.parsed_output

    def extract_lineup(self, image_path: Path) -> Lineup:
        result: _Extraction = self._parse(
            [_image_block(image_path), {"type": "text", "text": EXTRACT_PROMPT}],
            _Extraction,
            effort="high",
        )
        artists = [
            Artist(name=a.name.strip(), tier=min(max(a.tier, 1), 4), day=a.day, stage=a.stage)
            for a in result.artists
            if a.name.strip()
        ]
        return Lineup(festival=result.festival, year=result.year, artists=artists)

    def pick_deep_cuts(
        self, requests: dict[str, tuple[int, list[Candidate]]], batch_size: int = 25
    ) -> dict[str, list[str]]:
        """requests maps artist -> (how many deep cuts, candidate tracks). Returns artist -> titles."""
        items = [(a, n, c) for a, (n, c) in requests.items() if n > 0 and c]
        picks: dict[str, list[str]] = {}
        for i in range(0, len(items), batch_size):
            batch = items[i : i + batch_size]
            payload = json.dumps(
                [
                    {"artist": a, "pick": n, "candidates": [{"title": c.title, "plays": c.playcount} for c in cands]}
                    for a, n, cands in batch
                ],
                indent=1,
                ensure_ascii=False,
            )
            prompt = DEEP_CUT_PROMPT.format(
                instructions="exactly the number of deep cuts given in `pick`", payload=payload
            )
            result: _DeepCuts = self._parse(prompt, _DeepCuts, effort="medium")
            for p in result.picks:
                picks[p.artist] = p.titles
        return picks
