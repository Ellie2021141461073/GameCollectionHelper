from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from qdrant_client.models import PointStruct

from .chat import create_json_completion, deepseek_configured, get_deepseek_config
from .clean import CleanGame, iter_games
from .embeddings import embed_documents, embedding_info
from .store import (
    COLLECTION_NAME,
    PROJECT_ROOT,
    ensure_collection,
    existing_ids,
    game_payload,
    get_client,
)

PROMPT = """You enrich Steam game catalogue records for a recommendation engine.
Use only the supplied metadata. Return strict JSON:
{
  "tags": ["6-12 concise normalized English discovery tags"],
  "summary": "60-120 Chinese characters, factual and useful for game discovery"
}
Do not mention review scores or marketing language. Do not invent mechanics."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LLM-enrich games.csv into a local Qdrant collection"
    )
    parser.add_argument("--data", type=Path, default=PROJECT_ROOT / "games.csv")
    parser.add_argument("--limit", type=int, default=100, help="Maximum new games for this run")
    parser.add_argument("--min-reviews", type=int, default=20)
    parser.add_argument("--include-demos", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the existing Qdrant collection",
    )
    return parser.parse_args()


def extract_json(text: str) -> tuple[list[str], str]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    payload = json.loads(text)
    tags = payload.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    clean_tags = list(dict.fromkeys(str(tag).strip()[:60] for tag in tags if str(tag).strip()))[:12]
    return clean_tags, str(payload.get("summary", "")).strip()[:600]


def enrich_one(game: CleanGame) -> tuple[list[str], str]:
    metadata = {
        "name": game.name,
        "genres": game.genres,
        "source_tags": game.source_tags,
        "developers": game.developers,
        "publishers": game.publishers,
        "description": game.description[:6000],
    }
    content = create_json_completion(
        PROMPT,
        json.dumps(metadata, ensure_ascii=False),
    )
    return extract_json(content)


def build_embedding_text(game: CleanGame, tags: list[str], summary: str) -> str:
    return "\n".join([
        game.name,
        summary,
        "Tags: " + ", ".join(tags),
        "Genres: " + ", ".join(game.genres),
        "Source tags: " + ", ".join(game.source_tags),
        "Description: " + game.description[:4000],
    ])


def process_batch(
    *,
    qdrant,
    batch: list[CleanGame],
    workers: int,
) -> int:
    enriched: dict[int, tuple[list[str], str]] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(enrich_one, game): game for game in batch}
        for future in as_completed(futures):
            game = futures[future]
            enriched[game.app_id] = future.result()

    embedding_inputs = [
        build_embedding_text(game, *enriched[game.app_id])
        for game in batch
    ]
    vectors = embed_documents(embedding_inputs)
    points = []
    for game, vector in zip(batch, vectors, strict=True):
        tags, summary = enriched[game.app_id]
        search_text = build_embedding_text(game, tags, summary)
        payload = game_payload(game, llm_tags=tags, summary=summary, search_text=search_text)
        payload["enrichment_model"] = (
            f"{embedding_info()['model']}|{get_deepseek_config().model}"
        )
        points.append(PointStruct(id=game.app_id, vector=vector, payload=payload))

    qdrant.upsert(collection_name=COLLECTION_NAME, points=points, wait=True)
    return len(points)


def main() -> int:
    args = parse_args()
    if not args.data.is_file():
        raise SystemExit(f"Dataset not found: {args.data}")
    if not deepseek_configured():
        raise SystemExit("DEEPSEEK_API_KEY is required for tags, summaries, and explanations")

    chat_config = get_deepseek_config()
    embed_info = embedding_info()
    qdrant = get_client()
    ensure_collection(qdrant, reset=args.reset)
    known_ids = set() if args.reset else existing_ids(qdrant)
    print(f"[QDRANT] collection={COLLECTION_NAME} existing={len(known_ids):,}", flush=True)
    print(
        f"[MODELS] chat={chat_config.provider}/{chat_config.model} "
        f"embedding={embed_info['model']} ({embed_info['dimension']}d)",
        flush=True,
    )

    started = time.time()
    processed = 0
    batch: list[CleanGame] = []
    batch_size = max(1, args.batch_size)
    for game in iter_games(
        args.data,
        min_reviews=args.min_reviews,
        exclude_non_games=not args.include_demos,
    ):
        if processed >= args.limit:
            break
        if game.app_id in known_ids:
            continue
        batch.append(game)
        target_size = min(batch_size, max(1, args.limit - processed))
        if len(batch) < target_size:
            continue
        processed += process_batch(
            qdrant=qdrant,
            batch=batch,
            workers=args.workers,
        )
        known_ids.update(game.app_id for game in batch)
        batch.clear()
        print(f"[ENRICH] {processed:,}/{args.limit:,}", flush=True)
        if processed >= args.limit:
            break

    if batch and processed < args.limit:
        remaining = batch[:max(0, args.limit - processed)]
        processed += process_batch(
            qdrant=qdrant,
            batch=remaining,
            workers=args.workers,
        )

    qdrant.close()
    print(f"[DONE] added {processed:,} games in {time.time() - started:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
