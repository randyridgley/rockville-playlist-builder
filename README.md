# playlist-builder

Turn a festival lineup poster into an Apple Music playlist, with more songs from the acts billed highest. Or describe the songs you want in plain English and get a playlist of those.

```
poster.png ──Claude (vision)──▶ lineup.json (artist, tier 1–4, day, stage)
                                      │  review / edit
                                      ▼
            Last.fm top tracks (play counts) ──▶ hits (top N per tier)
                                      │
                       Claude picks deep cuts from ranks ~N+5 to 50
                                      ▼
            ordered tracks.json (spread out, opens with a headliner's biggest hit)
                                      ▼
                     Apple Music playlist (in your library)
```

## Weighting

| Tier | Meaning | Default tracks |
|---|---|---|
| 1 | Headliner | 4 hits + 1 deep cut |
| 2 | Sub-headliner | 2 hits + 1 deep cut |
| 3 | Mid-card | 2 hits |
| 4 | Undercard | 1 hit |

Change it with `--tiers "5+2,3+1,2,1"` (headliner first, `hits+deep_cuts`).

On grid posters (days × stages), Claude ranks the main stage over later stages and the top of each stage block over the rest. You always see the tiers before anything is created, and you can fix them by choosing `e` to edit the JSON.

## Setup

```bash
uv sync
cp .env.example .env   # then fill it in
```

- **Anthropic API key**: reads the poster and picks deep cuts. Uses `claude-opus-5-5`; override with `CLAUDE_MODEL`.
- **Last.fm API key** (free): play counts that decide which songs are "most popular".
- **Apple Music**: create a key with MusicKit enabled in your Apple Developer account and set the team ID, key ID, and `.p8` path. On first run, a localhost page opens and you sign in with your Apple ID.

## Usage

```bash
# Full run: extract → review → build → create the Apple Music playlist
uv run playlist-builder build ~/Desktop/rockville-2027.png --name "Rockville 2027 Preview"

# Look before you leap
uv run playlist-builder build poster.png --dry-run

# Reuse an edited lineup, only certain days
uv run playlist-builder build --lineup output/rockville-2027/lineup.json --days Friday,Saturday

# Just extraction
uv run playlist-builder extract poster.png -o lineup.json

# Create the playlist from a reviewed tracks.json exactly as-is (no re-picking)
uv run playlist-builder push output/rockville-2027/tracks.json --name "Rockville 2027 Preview"

# Sign in to Apple Music ahead of time (token cached in ~/.cache/playlist-builder)
uv run playlist-builder auth
```

## Describe a playlist

Skip the poster and say what you want. Claude picks the songs, names the playlist, and writes its description:

```bash
uv run playlist-builder describe "high-energy 2000s post-hardcore for the gym, a couple of deep cuts" --count 30
uv run playlist-builder describe "rainy Sunday morning: acoustic indie, nothing after 2010" -n "Rainy Sunday" --dry-run
```

Claude also picks about 25% extra songs as spares. If a song isn't on Apple Music (or doesn't exist), the next spare takes its place, so you still get `--count` songs. The run saves `request.txt` and `tracks.json` under `output/<playlist-name>/`; to create a playlist from an edited list, run `push tracks.json --name "..." --count 30`.

Song picks come from Claude's own knowledge, so very recent releases may be missing.

Tracks that aren't found on Apple Music are listed at the end of the run. They're usually regional exclusives or very small acts.

## Playlist cover

Apple's API can't set playlist artwork, so `build` saves a square `cover.jpg` made from the poster next to `tracks.json`. Playlists created through the API are read-only in the Music app, so to add the cover:

1. Open the playlist, select all songs (⌘A), and choose File → New → Playlist from Selection.
2. Drag `cover.jpg` onto the new playlist's artwork, then delete the original.

## Tests

```bash
uv run pytest
```
