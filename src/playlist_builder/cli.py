import json
import re
from collections import Counter
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from .config import ConfigError
from .models import DEFAULT_QUOTAS, Lineup, Track, parse_quotas
from .selection import order_tracks, select_tracks

app = typer.Typer(help="Turn a festival lineup poster into a tier-weighted Apple Music playlist.")
console = Console()

TIER_NAMES = {1: "Headliner", 2: "Sub-headliner", 3: "Mid-card", 4: "Undercard"}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "playlist"


def _show_lineup(lineup: Lineup) -> None:
    title = " ".join(str(x) for x in (lineup.festival, lineup.year) if x) or "Lineup"
    table = Table(title=f"{title}: {len(lineup.artists)} acts")
    for col in ("#", "Artist", "Tier", "Day", "Stage"):
        table.add_column(col)
    for i, a in enumerate(lineup.artists, 1):
        table.add_row(str(i), a.name, f"{a.tier} {TIER_NAMES[a.tier]}", a.day or "", a.stage or "")
    console.print(table)
    counts = Counter(a.tier for a in lineup.artists)
    console.print("Tier counts: " + ", ".join(f"{TIER_NAMES[t]} {counts.get(t, 0)}" for t in (1, 2, 3, 4)))


def _show_tracks(tracks: list[Track]) -> None:
    table = Table(title=f"Playlist: {len(tracks)} tracks")
    for col in ("#", "Artist", "Title", "Type", "Tier"):
        table.add_column(col)
    for i, t in enumerate(tracks, 1):
        table.add_row(str(i), t.artist, t.title, "deep cut" if t.kind == "deep_cut" else "hit", str(t.tier))
    console.print(table)


def _review_lineup(lineup: Lineup, path: Path, auto_yes: bool) -> Lineup:
    while True:
        _show_lineup(lineup)
        if auto_yes:
            return lineup
        choice = typer.prompt("Continue with this lineup? [y]es / [e]dit / [q]uit", default="y").strip().lower()
        if choice.startswith("q"):
            raise typer.Exit(1)
        if choice.startswith("e"):
            edited = typer.edit(lineup.model_dump_json(indent=2), extension=".json")
            if edited:
                try:
                    lineup = Lineup.model_validate_json(edited)
                    path.write_text(lineup.model_dump_json(indent=2))
                except ValueError as e:
                    console.print(f"[red]Invalid JSON, keeping previous lineup:[/red] {e}")
            continue
        return lineup


@app.command()
def extract(
    poster: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="Lineup poster image")],
    output: Annotated[Path, typer.Option("-o", "--output")] = Path("lineup.json"),
):
    """Read the artists and their billing tiers from a poster into a JSON file you can edit."""
    from .claude import Claude

    with console.status("Reading the poster with Claude…"):
        lineup = Claude().extract_lineup(poster)
    output.write_text(lineup.model_dump_json(indent=2))
    _show_lineup(lineup)
    console.print(f"Saved to [bold]{output}[/bold]")


@app.command()
def build(
    poster: Annotated[Optional[Path], typer.Argument(exists=True, dir_okay=False, help="Lineup poster image")] = None,
    lineup_file: Annotated[Optional[Path], typer.Option("--lineup", exists=True, help="Use a saved lineup.json instead of a poster")] = None,
    name: Annotated[Optional[str], typer.Option("--name", "-n", help="Playlist name")] = None,
    tiers: Annotated[str, typer.Option(help="Tracks per tier, headliner first: hits[+deep_cuts]")] = "4+1,2+1,2,1",
    days: Annotated[Optional[str], typer.Option(help="Only include these days, e.g. 'Friday,Saturday'")] = None,
    seed: Annotated[Optional[int], typer.Option(help="Random seed for track order")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Build the track list but don't create playlists")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation prompts")] = False,
    out_dir: Annotated[Path, typer.Option("--out", help="Where to save lineup.json and tracks.json")] = Path("output"),
):
    """Poster to lineup to weighted track list to an Apple Music playlist."""
    if not poster and not lineup_file:
        raise typer.BadParameter("Pass a poster image or --lineup lineup.json")
    quotas = parse_quotas(tiers) if tiers else DEFAULT_QUOTAS

    from .claude import Claude
    from .lastfm import LastFm
    from .providers import get_provider

    try:
        # Construct the provider up front so missing credentials fail before any API spend.
        provider = None if dry_run else get_provider("apple")
        claude, lastfm = Claude(), LastFm()
    except ConfigError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    # 1. Lineup
    if lineup_file:
        lineup = Lineup.model_validate_json(lineup_file.read_text())
        run_dir = lineup_file.parent
        lineup_path = lineup_file
    else:
        with console.status("Reading the poster with Claude…"):
            lineup = claude.extract_lineup(poster)
        run_dir = out_dir / _slug(name or " ".join(str(x) for x in (lineup.festival, lineup.year) if x) or poster.stem)
        run_dir.mkdir(parents=True, exist_ok=True)
        lineup_path = run_dir / "lineup.json"
        lineup_path.write_text(lineup.model_dump_json(indent=2))
        console.print(f"Saved lineup to [bold]{lineup_path}[/bold] (re-run with --lineup to skip extraction)")
        from .cover import make_cover

        cover = make_cover(poster, run_dir / "cover.jpg")
        console.print(f"Saved playlist cover to [bold]{cover}[/bold] (drag it onto the playlist in Music)")

    if days:
        wanted = {d.strip().casefold() for d in days.split(",")}
        lineup.artists = [a for a in lineup.artists if (a.day or "").casefold() in wanted]
    lineup = _review_lineup(lineup, lineup_path, yes)

    # 2. Candidates and selection
    names = [a.name for a in lineup.artists]
    with console.status(f"Fetching top tracks for {len(names)} artists from Last.fm…"):
        candidates = lastfm.top_tracks_many(names)
    with console.status("Picking deep cuts with Claude…"):
        tracks, missing = select_tracks(lineup, candidates, quotas, claude.pick_deep_cuts)
    tracks = order_tracks(tracks, seed)

    _show_tracks(tracks)
    if missing:
        console.print(f"[yellow]No Last.fm catalog found for:[/yellow] {', '.join(missing)}")
    # A name read wrong off the poster usually still matches *some* obscure Last.fm artist.
    obscure = sorted(a for a, cs in candidates.items() if cs and cs[0].playcount < 1000)
    if obscure:
        console.print(
            f"[yellow]Very few Last.fm plays (check the spelling in lineup.json):[/yellow] {', '.join(obscure)}"
        )
    (run_dir / "tracks.json").write_text(json.dumps([t.model_dump() for t in tracks], indent=2))
    console.print(f"Saved track list to [bold]{run_dir / 'tracks.json'}[/bold]")

    if dry_run:
        return
    if not yes and not typer.confirm(f"Create this playlist on {provider.name}?", default=True):
        raise typer.Exit(1)

    # 3. Playlist
    playlist_name = name or " ".join(str(x) for x in (lineup.festival, lineup.year, "Preview") if x)
    description = (
        f"{len(tracks)} tracks from the {lineup.festival or 'festival'} lineup, weighted by billing: "
        "hits from the headliners down, plus a few deep cuts. Built with playlist-builder."
    )
    _create_playlist(provider, playlist_name, description, tracks)


def _create_playlist(provider, playlist_name: str, description: str, tracks: list[Track]) -> None:
    from .providers import build_playlist

    provider.authenticate()
    with Progress(console=console) as progress:
        task = progress.add_task(f"Matching on {provider.name}", total=len(tracks))
        result = build_playlist(provider, playlist_name, description, tracks, lambda: progress.advance(task))
    console.print(
        f"[green]{provider.name}:[/green] added {result.added}/{len(tracks)} tracks"
        + (f": {result.url}" if result.url else " (check your library)")
    )
    for t in result.not_found:
        console.print(f"  [dim]not found: {t.artist} - {t.title}[/dim]")


@app.command()
def push(
    tracks_file: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="A tracks.json from a previous build")],
    name: Annotated[str, typer.Option("--name", "-n", help="Playlist name")],
):
    """Create the playlist from a saved tracks.json exactly as reviewed (no re-picking)."""
    from .providers import get_provider

    tracks = [Track.model_validate(t) for t in json.loads(tracks_file.read_text())]
    description = (
        f"{len(tracks)} tracks weighted by festival billing: hits from the headliners down, "
        "plus a few deep cuts. Built with playlist-builder."
    )
    _create_playlist(get_provider("apple"), name, description, tracks)


@app.command()
def auth():
    """Sign in to Apple Music ahead of time (the token is cached)."""
    from .providers import get_provider

    provider = get_provider("apple")
    provider.authenticate()
    console.print(f"[green]Signed in to {provider.name}.[/green]")
