#!/usr/bin/env python3
"""Show one game going through both enrichment stages, for demos and logs.

Prints exactly what the pipeline produces for a single item:

  1. the cleaned record (what the LLM is allowed to see)
  2. the DeepSeek reply: structured tags + Chinese summary, with token usage
  3. the BGE-M3 embedding: dimension, L2 norm and wall-clock time

Nothing is written to Qdrant and no collection is touched, so this is safe to run
against the live stack.

    python scripts/pipeline_demo.py                     # first eligible game
    python scripts/pipeline_demo.py --appid 413150      # a specific game
    python scripts/pipeline_demo.py --appid 413150 --show-prompt
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Running this file directly puts scripts/ (not the repository root) on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from recommender.chat import get_deepseek_config, usage_snapshot  # noqa: E402
from recommender.clean import iter_games  # noqa: E402
from recommender.embeddings import embed_documents, embedding_info  # noqa: E402
from recommender.enrich_qdrant import (  # noqa: E402
    PROMPT,
    build_embedding_text,
    enrich_one,
)

DATA = Path(__file__).resolve().parents[1] / "games.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one game through the LLM + embedding stages")
    parser.add_argument(
        "--appid", type=int, default=0, help="Steam AppID (default: first eligible)"
    )
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--show-prompt", action="store_true", help="Print the prompt payload")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.data.is_file():
        raise SystemExit(f"games.csv not found: {args.data}")

    game = None
    for candidate in iter_games(args.data, min_reviews=20):
        if args.appid and candidate.app_id != args.appid:
            continue
        game = candidate
        break
    if game is None:
        raise SystemExit(f"AppID {args.appid} not found with >=20 reviews")

    print("=" * 74)
    print("STAGE 0 · 清洗后的记录（送入 LLM 与嵌入的原料）")
    print("=" * 74)
    print(f"  app_id           : {game.app_id}")
    print(f"  name             : {game.name}")
    print(f"  genres           : {game.genres}")
    print(f"  source_tags      : {game.source_tags[:8]}")
    print(f"  developers       : {game.developers}")
    print(f"  review_count     : {game.review_count:,}")
    print(f"  description len  : {len(game.description):,} chars")
    print(f"  preview          : {game.description[:160]}...")

    metadata = {
        "name": game.name,
        "genres": game.genres,
        "source_tags": game.source_tags,
        "developers": game.developers,
        "publishers": game.publishers,
        "description": game.description[:6000],
    }
    if args.show_prompt:
        print()
        print("=" * 74)
        print("PROMPT · system")
        print("=" * 74)
        print(PROMPT)
        print("=" * 74)
        print("PROMPT · user（metadata JSON）")
        print("=" * 74)
        print(json.dumps(metadata, ensure_ascii=False)[:1200])

    print()
    print("=" * 74)
    config = get_deepseek_config()
    print(f"STAGE 1 · DeepSeek（{config.provider} / {config.model}）生成标签与摘要")
    print("=" * 74)
    before = usage_snapshot()
    started = time.perf_counter()
    tags, summary = enrich_one(game)
    llm_seconds = time.perf_counter() - started
    after = usage_snapshot()
    print(f"  latency          : {llm_seconds:.2f}s")
    print(f"  tags ({len(tags)})         : {tags}")
    print(f"  summary          : {summary}")
    print(
        f"  tokens           : prompt={after['prompt_tokens'] - before['prompt_tokens']:,} "
        f"completion={after['completion_tokens'] - before['completion_tokens']:,}"
    )

    print()
    print("=" * 74)
    info = embedding_info()
    print(f"STAGE 2 · BGE-M3 生成向量（{info['model']} · {info['device']} · {info['dtype']}）")
    print("=" * 74)
    embedding_text = build_embedding_text(game, tags, summary)
    print(f"  input chars      : {len(embedding_text):,}")
    # Warm the model first: otherwise the timing below includes the one-off
    # weight load (~2.2 GB) and is not the per-item embedding cost.
    embed_documents(["warmup"])
    started = time.perf_counter()
    vectors = embed_documents([embedding_text])
    embed_seconds = time.perf_counter() - started
    vector = vectors[0]
    norm = sum(value * value for value in vector) ** 0.5
    print(f"  latency          : {embed_seconds:.2f}s")
    print(f"  dimension        : {len(vector)}")
    print(f"  L2 norm          : {norm:.6f}")
    print(f"  first 6 values   : {[round(value, 5) for value in vector[:6]]}")
    print()
    print(
        f"[DONE] {game.name} · tags={len(tags)} · summary={len(summary)} chars · "
        f"vector={len(vector)}d · total={llm_seconds + embed_seconds:.2f}s"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
