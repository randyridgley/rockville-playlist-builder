from typing import Literal

from pydantic import BaseModel, Field


class Artist(BaseModel):
    name: str
    tier: int = Field(ge=1, le=4, description="1 = headliner, 4 = smallest print")
    day: str | None = None
    stage: str | None = None


class Lineup(BaseModel):
    festival: str | None = None
    year: int | None = None
    artists: list[Artist]


class Track(BaseModel):
    artist: str
    title: str
    kind: Literal["hit", "deep_cut"]
    tier: int
    playcount: int | None = None


class TierQuota(BaseModel):
    hits: int
    deep_cuts: int

    @property
    def total(self) -> int:
        return self.hits + self.deep_cuts


# Headliner 4 hits + 1 deep cut, sub-headliner 2 + 1, mid 2, small 1.
DEFAULT_QUOTAS: dict[int, TierQuota] = {
    1: TierQuota(hits=4, deep_cuts=1),
    2: TierQuota(hits=2, deep_cuts=1),
    3: TierQuota(hits=2, deep_cuts=0),
    4: TierQuota(hits=1, deep_cuts=0),
}


def parse_quotas(spec: str) -> dict[int, TierQuota]:
    """Parse "4+1,2+1,2,1" into per-tier quotas (hits[+deep_cuts], tier 1 first)."""
    parts = [p.strip() for p in spec.split(",")]
    if len(parts) != 4:
        raise ValueError("Expected 4 comma-separated tier quotas, e.g. '4+1,2+1,2,1'")
    quotas = {}
    for tier, part in enumerate(parts, start=1):
        hits, _, deep = part.partition("+")
        quotas[tier] = TierQuota(hits=int(hits), deep_cuts=int(deep or 0))
    return quotas
