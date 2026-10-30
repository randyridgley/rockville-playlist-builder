from .base import PlaylistResult, Provider, add_to_playlist, build_playlist


def get_provider(name: str = "apple") -> Provider:
    key = name.strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    if key in ("apple", "applemusic"):
        from .apple_music import AppleMusic

        return AppleMusic()
    raise ValueError(f"Unknown platform '{name}'. Only 'apple' is supported.")


__all__ = ["PlaylistResult", "Provider", "add_to_playlist", "build_playlist", "get_provider"]
