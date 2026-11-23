#!/usr/bin/env python3
"""Ablation: BM25 only vs vector only vs hybrid (RRF) on the same queries.

Relevance labels are **rule-based proxies** built from structured metadata
(genres, source tags, LLM tags, summary). They are objective and reproducible,
but they favour lexical matching because the same words appear in the metadata
BM25 indexes. Treat the numbers as "does hybrid keep the other modes' relevant
hits", not as an absolute quality score. See docs/experiments/README.md.

    python scripts/experiment_retrieval.py
    python scripts/experiment_retrieval.py --k 10 --out docs/experiments/retrieval-ablation.json
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

MODES = ("bm25", "vector", "hybrid")

#: Each query carries its own labeling rule: every group must match at least one
#: alternative, and no `forbid` term may appear anywhere in the item's metadata.
QUERIES: list[dict[str, Any]] = [
    {
        "q": "a relaxing puzzle game with beautiful art and no combat",
        "must": [["puzzle", "jigsaw", "nonogram", "solitaire"]],
        "forbid": ["action", "shooter", "horror"],
    },
    {
        "q": "cozy farming simulation to unwind",
        "must": [["farming", "farm"], ["simulation", "life sim", "casual"]],
        "forbid": ["horror"],
    },
    {
        "q": "souls-like action rpg with punishing combat",
        "must": [["souls-like", "soulslike"], ["rpg"]],
        "forbid": [],
    },
    {
        "q": "story rich visual novel with romance",
        "must": [["visual novel"], ["romance"]],
        "forbid": ["horror"],
    },
    {
        "q": "cold war military strategy wargame",
        "must": [["wargame", "strategy"], ["cold war", "military", "war"]],
        "forbid": [],
    },
    {
        "q": "roguelike deckbuilder with card battles",
        "must": [["roguelike", "rogue-like"], ["deckbuilder", "card", "cards"]],
        "forbid": [],
    },
    {
        "q": "horror exploration in a dark asylum",
        "must": [["horror"], ["exploration", "walking simulator", "adventure"]],
        "forbid": [],
    },
    {
        "q": "space simulation trading and exploration",
        "must": [["space"], ["simulation", "trading", "exploration"]],
        "forbid": [],
    },
    {
        "q": "multiplayer tactical shooter with teamwork",
        "must": [["shooter", "fps"], ["multiplayer", "team"]],
        "forbid": [],
    },
    {
        "q": "city building management with economic depth",
        "must": [["city", "city builder", "building"], ["management", "economy", "simulation"]],
        "forbid": [],
    },
]


def http_json(url: str, *, data: Any | None = None, timeout: float = 300.0) -> Any:
    headers = {"Accept": "application/json"}
    body = None
    method = "GET"
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
        method = "POST"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def load_payloads(qdrant: str, collection: str) -> list[dict[str, Any]]:
    """Scroll every payload once; the proxy labels need the full catalogue."""
    payloads: list[dict[str, Any]] = []
    offset = None
    while True:
        body: dict[str, Any] = {"limit": 1000, "with_payload": True, "with_vector": False}
        if offset is not None:
            body["offset"] = offset
        result = http_json(
            f"{qdrant}/collections/{collection}/points/scroll", data=body
        )["result"]
        points = result.get("points") or []
        if not points:
            return payloads
        payloads.extend(point.get("payload") or {} for point in points)
        offset = result.get("next_page_offset")
        if offset is None:
            return payloads


def searchable(payload: dict[str, Any]) -> str:
    parts = [
        str(payload.get("name") or ""),
        " ".join(payload.get("genres") or []),
        " ".join(payload.get("source_tags") or []),
        " ".join(payload.get("llm_tags") or []),
        str(payload.get("summary") or ""),
    ]
    return " ".join(parts).casefold()


def relevant_ids(payloads: list[dict[str, Any]], rule: dict[str, Any]) -> set[int]:
    must = rule.get("must") or []
    forbid = rule.get("forbid") or []
    hits: set[int] = set()
    for payload in payloads:
        text = searchable(payload)
        if any(term in text for term in forbid):
            continue
        if all(any(alternative in text for alternative in group) for group in must):
            try:
                hits.add(int(payload.get("app_id")))
            except (TypeError, ValueError):
                continue
    return hits


def run_query(api: str, query: str, mode: str, k: int) -> tuple[list[int], float]:
    params = urllib.parse.urlencode({"q": query, "limit": k, "retrieval": mode})
    started = time.perf_counter()
    body = http_json(f"{api}/search?{params}", timeout=300)
    elapsed = time.perf_counter() - started
    return [int(item["app_id"]) for item in body.get("results") or []], elapsed


def metrics_at_k(ranked: list[int], relevant: set[int], k: int) -> dict[str, float]:
    top = ranked[:k]
    hits = [1 if item in relevant else 0 for item in top]
    found = sum(hits)
    precision = found / k
    reachable = min(len(relevant), k) or 1
    recall = found / reachable
    reciprocal_rank = 0.0
    for index, hit in enumerate(hits, 1):
        if hit:
            reciprocal_rank = 1.0 / index
            break
    dcg = sum(hit / math.log2(index + 1) for index, hit in enumerate(hits, 1))
    ideal_hits = min(len(relevant), k)
    idcg = sum(1 / math.log2(index + 1) for index in range(1, ideal_hits + 1))
    return {
        "hit": 1.0 if found else 0.0,
        "precision": precision,
        "recall": recall,
        "mrr": reciprocal_rank,
        "ndcg": dcg / idcg if idcg else 0.0,
        "found": float(found),
    }


def jaccard(left: list[int], right: list[int]) -> float:
    a, b = set(left), set(right)
    return len(a & b) / len(a | b) if (a | b) else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description="Retrieval ablation over BM25 / vector / hybrid")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--qdrant", default="http://127.0.0.1:6333")
    parser.add_argument("--collection", default="steam_games")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("docs/experiments/retrieval-ablation.json"),
    )
    args = parser.parse_args()

    print(f"loading payloads from {args.qdrant} ...", flush=True)
    payloads = load_payloads(args.qdrant, args.collection)
    print(f"catalogue: {len(payloads):,} items\n", flush=True)

    per_query: list[dict[str, Any]] = []
    latencies: dict[str, list[float]] = {mode: [] for mode in MODES}
    for rule in QUERIES:
        relevant = relevant_ids(payloads, rule)
        row: dict[str, Any] = {"query": rule["q"], "relevant": len(relevant), "modes": {}}
        ranked_by_mode: dict[str, list[int]] = {}
        for mode in MODES:
            ranked, elapsed = run_query(args.api, rule["q"], mode, args.k)
            ranked_by_mode[mode] = ranked
            latencies[mode].append(elapsed)
            row["modes"][mode] = metrics_at_k(ranked, relevant, args.k)
            row["modes"][mode]["top"] = ranked
        row["overlap"] = {
            "bm25_vector": jaccard(ranked_by_mode["bm25"], ranked_by_mode["vector"]),
            "bm25_hybrid": jaccard(ranked_by_mode["bm25"], ranked_by_mode["hybrid"]),
            "vector_hybrid": jaccard(ranked_by_mode["vector"], ranked_by_mode["hybrid"]),
        }
        per_query.append(row)
        summary = "  ".join(
            f"{mode}:P@k={row['modes'][mode]['precision']:.2f}"
            for mode in MODES
        )
        print(f"  rel={row['relevant']:<5} {summary}  | {rule['q'][:52]}", flush=True)

    print()
    print("| metric | BM25 only | Vector only | Hybrid (RRF) |")
    print("| --- | --- | --- | --- |")
    aggregates: dict[str, dict[str, float]] = {}
    for mode in MODES:
        aggregates[mode] = {
            name: statistics.mean(row["modes"][mode][name] for row in per_query)
            for name in ("hit", "precision", "recall", "mrr", "ndcg")
        }
        aggregates[mode]["latency_p50"] = statistics.median(latencies[mode])
    for name, label in (
        ("hit", "Hit@k"),
        ("precision", "Precision@k"),
        ("recall", "Recall@k"),
        ("mrr", "MRR@k"),
        ("ndcg", "nDCG@k"),
    ):
        cells = " | ".join(f"{aggregates[mode][name]:.3f}" for mode in MODES)
        print(f"| {label} | {cells} |")
    cells = " | ".join(f"{aggregates[mode]['latency_p50']:.2f}s" for mode in MODES)
    print(f"| p50 latency | {cells} |")

    overlap = {
        key: statistics.mean(row["overlap"][key] for row in per_query)
        for key in ("bm25_vector", "bm25_hybrid", "vector_hybrid")
    }
    print("\n平均 Jaccard 重叠：")
    for key, value in overlap.items():
        print(f"  {key:<14} {value:.3f}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                "k": args.k,
                "catalogue": len(payloads),
                "aggregates": aggregates,
                "overlap": overlap,
                "per_query": per_query,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nwritten: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
