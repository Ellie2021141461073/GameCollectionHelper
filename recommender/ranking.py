"""Pure retrieval scoring: BM25, quality re-ranking and reciprocal rank fusion.

Everything here is a pure function over plain Python containers. No Qdrant
client, no LLM client, no filesystem access — which is what makes the hybrid
ranking behaviour unit-testable without installing the heavy runtime stack.

The service layer (``recommender.service``) owns all I/O and simply calls into
this module.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

#: Reciprocal rank fusion damping constant (Cormack et al., 2009).
RRF_K = 60
#: Weight of the quality prior added to the fused score.
QUALITY_WEIGHT = 0.004
#: Prior sample size and assumed mean used by the Bayesian review score.
QUALITY_PRIOR_COUNT = 40
QUALITY_PRIOR_MEAN = 0.8
#: Popularity saturates at log1p(recommendations) / POPULARITY_SCALE.
POPULARITY_SCALE = 12

BM25_K1 = 1.5
BM25_B = 0.75


class BM25Index:
    """Okapi BM25 index over pre-tokenised documents.

    Args:
        token_lists: one token list per document, in the order the caller wants
            document indexes to refer to.
    """

    def __init__(
        self,
        token_lists: Sequence[Sequence[str]],
        k1: float = BM25_K1,
        b: float = BM25_B,
    ) -> None:
        self.k1 = k1
        self.b = b
        self.document_count = len(token_lists)
        self.postings: dict[str, list[tuple[int, int]]] = {}
        lengths: list[int] = []
        for index, tokens in enumerate(token_lists):
            counts = Counter(tokens)
            lengths.append(sum(counts.values()))
            for term, frequency in counts.items():
                self.postings.setdefault(term, []).append((index, frequency))
        self.lengths = lengths
        self.average_length = sum(lengths) / max(1, len(lengths))
        total = max(1, self.document_count)
        self.idf = {
            term: math.log(1 + (total - len(entries) + 0.5) / (len(entries) + 0.5))
            for term, entries in self.postings.items()
        }

    def search(self, query_tokens: Iterable[str], limit: int) -> list[tuple[int, float]]:
        """Return ``(document_index, score)`` pairs, best first, score > 0 only."""
        scores = [0.0] * self.document_count
        for term in dict.fromkeys(query_tokens):
            entries = self.postings.get(term)
            if not entries:
                continue
            idf = self.idf[term]
            for index, frequency in entries:
                denominator = frequency + self.k1 * (
                    1 - self.b + self.b * self.lengths[index] / max(1e-9, self.average_length)
                )
                scores[index] += idf * frequency * (self.k1 + 1) / denominator
        ranked = sorted(
            range(self.document_count),
            key=lambda index: scores[index],
            reverse=True,
        )[:limit]
        return [(index, scores[index]) for index in ranked if scores[index] > 0]


def quality_score(payload: Mapping[str, Any]) -> float:
    """Blend a Bayesian review score with a damped popularity term, in [0, 1]."""
    positive = max(0, int(payload.get("positive") or 0))
    negative = max(0, int(payload.get("negative") or 0))
    bayesian = (positive + QUALITY_PRIOR_COUNT * QUALITY_PRIOR_MEAN) / (
        positive + negative + QUALITY_PRIOR_COUNT
    )
    popularity = min(
        1.0,
        math.log1p(max(0, int(payload.get("recommendations") or 0))) / POPULARITY_SCALE,
    )
    return 0.8 * bayesian + 0.2 * popularity


def merge_rankings(
    *,
    vector_results: Sequence[tuple[int, float]],
    lexical_results: Sequence[tuple[int, float]],
    lexical_ids: Sequence[int],
    payloads: Mapping[int, Mapping[str, Any]],
    limit: int,
    exclude_id: int | None = None,
    rrf_k: int = RRF_K,
    quality_weight: float = QUALITY_WEIGHT,
) -> list[dict[str, Any]]:
    """Fuse vector and BM25 rankings with RRF, then re-rank by quality.

    Args:
        vector_results: ``(app_id, similarity)`` pairs ordered best first.
        lexical_results: ``(document_index, bm25_score)`` pairs ordered best first.
        lexical_ids: ``document_index -> app_id`` mapping for ``lexical_results``.
        payloads: ``app_id -> payload`` used for the quality prior and output.
        limit: maximum number of fused items to return.
        exclude_id: ``app_id`` to drop (the query item itself, for item-item mode).
        rrf_k: RRF damping constant.
        quality_weight: weight of :func:`quality_score` in the final score.

    Returns:
        Ranked dicts carrying ``app_id``, ``rrf``, ``hybrid_score``,
        ``match_percent`` and the source payload, plus whichever per-retriever
        scores contributed.
    """
    merged: dict[int, dict[str, Any]] = {}
    for rank, (app_id, score) in enumerate(vector_results, 1):
        if app_id == exclude_id:
            continue
        item = merged.setdefault(app_id, {"app_id": app_id, "rrf": 0.0})
        item["rrf"] += 1 / (rrf_k + rank)
        item["vector_score"] = score
    for rank, (index, score) in enumerate(lexical_results, 1):
        app_id = lexical_ids[index]
        if app_id == exclude_id:
            continue
        item = merged.setdefault(app_id, {"app_id": app_id, "rrf": 0.0})
        item["rrf"] += 1 / (rrf_k + rank)
        item["bm25_score"] = score
    for item in merged.values():
        payload = payloads.get(item["app_id"])
        if payload is None:
            continue
        item["payload"] = payload
        item["hybrid_score"] = item["rrf"] + quality_weight * quality_score(payload)
    ranked = sorted(
        merged.values(),
        key=lambda item: item.get("hybrid_score", 0),
        reverse=True,
    )[:limit]
    return _with_match_percent(ranked)


def _with_match_percent(ranked: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Scale ``hybrid_score`` so the best hit reads as 100%."""
    maximum = max((item.get("hybrid_score", 0) for item in ranked), default=1)
    for item in ranked:
        item["match_percent"] = round(item.get("hybrid_score", 0) / maximum * 100, 1)
    return ranked
