"""Sample-selection helpers for the enrichment pipeline.

``iter_games`` preserves the order of ``games.csv``, which is essentially
arbitrary. Enriching the first N rows therefore produces an index with a median
of ~105 reviews and leaves famous titles out: as of the current 20,000-point
collection, Stardew Valley (413150) and Cyberpunk 2077 (1091500) are absent
while Dota 2 (570) and Counter-Strike 2 (730) are present.

Selecting by review count instead makes a 20,000-item sample look like a game
catalogue that a user recognises. Standard library only, like ``clean``.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .clean import iter_games


def rank_by_review_count(
    candidates: Iterable[tuple[int, int]],
    limit: int | None = None,
) -> list[int]:
    """Return AppIDs ordered by review count, descending.

    Args:
        candidates: ``(review_count, app_id)`` pairs.
        limit: keep at most this many entries; ``None`` keeps all.

    Ties keep their input order, so the result is deterministic for a given CSV.
    """
    ranked = sorted(candidates, key=lambda pair: pair[0], reverse=True)
    app_ids = [app_id for _, app_id in ranked]
    return app_ids if limit is None else app_ids[:max(0, limit)]


def select_new_app_ids(
    path: str | Path,
    *,
    limit: int,
    min_reviews: int = 20,
    include_demos: bool = False,
    known_ids: Iterable[int] = (),
    order: str = "reviews",
) -> list[int]:
    """Choose which games a single enrichment run should process.

    Args:
        path: path to ``games.csv``.
        limit: maximum number of AppIDs to return.
        min_reviews: review threshold applied by :func:`iter_games`.
        include_demos: keep demos and playtests (dropped by default).
        known_ids: AppIDs already present in the Qdrant collection.
        order: ``"reviews"`` ranks by review count, ``"file"`` keeps CSV order.

    Returns:
        AppIDs in processing priority order.
    """
    if order not in {"reviews", "file"}:
        raise ValueError(f"Unsupported order: {order!r}")

    known = set(known_ids)
    candidates: list[tuple[int, int]] = []
    for game in iter_games(
        path,
        min_reviews=min_reviews,
        exclude_non_games=not include_demos,
    ):
        if game.app_id in known:
            continue
        candidates.append((game.review_count, game.app_id))
        if order == "file" and len(candidates) >= limit:
            break

    if order == "file":
        return [app_id for _, app_id in candidates[:limit]]
    return rank_by_review_count(candidates, limit)
