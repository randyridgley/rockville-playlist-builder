from pathlib import Path

from PIL import Image

COVER_SIZE = 1600


def make_cover(poster: Path, out: Path, size: int = COVER_SIZE) -> Path:
    """Square cover from the poster, padded rather than cropped so no names are cut off.

    Apple's API can't set playlist artwork, so this is saved for dragging onto the playlist in Music.
    """
    src = Image.open(poster).convert("RGB")
    side = max(src.size)
    # Pad with the poster's own corner color so the bars blend in.
    canvas = Image.new("RGB", (side, side), src.getpixel((0, 0)))
    canvas.paste(src, ((side - src.width) // 2, (side - src.height) // 2))
    canvas.resize((size, size), Image.LANCZOS).save(out, quality=92)
    return out
