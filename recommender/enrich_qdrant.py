from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from qdrant_client.models import PointStruct

from .chat import (
    create_json_completion,
    deepseek_configured,
    get_deepseek_config,
    usage_snapshot,
)
from .clean import CleanGame, iter_games
from .embeddings import embed_documents, embedding_info
from .selection import select_new_app_ids
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
    parser.add_argument(
        "--order-by",
        choices=["file", "reviews"],
        default="file",
        help=(
            "Which candidates to enrich: 'file' keeps games.csv order (median "
            "~100 reviews), 'reviews' prefers the most-reviewed games so famous "
            "titles make it into the index"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report the selection and an estimated token budget, then exit",
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


def estimate_run(args: argparse.Namespace, known_ids: set[int]) -> None:
    """Report what this run would cost without calling any API.

    Token counts are intentionally approximate: the point is to catch an
    accidental 30k-item run before it burns the quota, not to be exact.
    """
    selected = select_new_app_ids(
        args.data,
        limit=args.limit,
        min_reviews=args.min_reviews,
        include_demos=args.include_demos,
        known_ids=known_ids,
        order=args.order_by,
    )
    wanted = set(selected)
    prompt_chars = 0
    embedding_chars = 0
    ranked: list[tuple[int, str]] = []
    games = 0
    for game in iter_games(
        args.data,
        min_reviews=args.min_reviews,
        exclude_non_games=not args.include_demos,
    ):
        if game.app_id not in wanted:
            continue
        games += 1
        metadata = {
            "name": game.name,
            "genres": game.genres,
            "source_tags": game.source_tags,
            "developers": game.developers,
            "publishers": game.publishers,
            "description": game.description[:6000],
        }
        prompt_chars += len(json.dumps(metadata, ensure_ascii=False))
        # Mirrors build_embedding_text(); the summary does not exist yet, so it
        # is left out and the estimate is slightly conservative.
        embedding_chars += len(game.name) + len(game.description[:4000])
        embedding_chars += len(", ".join(game.genres)) + len(", ".join(game.source_tags))
        ranked.append((game.review_count, game.name))
        if games == len(wanted):
            break
    ranked.sort(reverse=True)

    # ~4 chars per token for English prose; the Chinese summaries lower it, so
    # treat the prompt figure as an upper bound.
    input_tokens = prompt_chars // 4
    embedding_tokens = embedding_chars // 4
    print(f"[DRY-RUN] order={args.order_by} limit={args.limit:,} 可新增={len(selected):,}")
    print(f"[DRY-RUN] 本次将增强 {games:,} 款游戏")
    print(f"[DRY-RUN] LLM 调用 {games:,} 次")
    print(f"[DRY-RUN] prompt 约 {prompt_chars:,} 字符 ≈ {input_tokens:,} tokens")
    print(
        f"[DRY-RUN] 本地嵌入文本约 {embedding_chars:,} 字符 "
        f"≈ {embedding_tokens:,} tokens（不出网、不计费）"
    )
    print("[DRY-RUN] 按评论数排名的前 5 款：")
    for review_count, name in ranked[:5]:
        print(f"[DRY-RUN]   - {name} ({review_count:,} reviews)")
    print("[DRY-RUN] 未调用任何 API，未写入 Qdrant。")


def process_batch(
    *,
    qdrant,
    batch: list[CleanGame],
    workers: int,
) -> list[int]:
    """Enrich one batch; returns the AppIDs actually written.

    A single malformed or rate-limited LLM response must not abort a long run:
    those items are reported and left for the next run, which skips only ids
    that are really in the collection.
    """
    enriched: dict[int, tuple[list[str], str]] = {}
    failed: list[int] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(enrich_one, game): game for game in batch}
        for future in as_completed(futures):
            game = futures[future]
            try:
                enriched[game.app_id] = future.result()
            except Exception as error:  # noqa: BLE001 - report and continue
                failed.append(game.app_id)
                print(
                    f"[WARN] enrich failed for {game.app_id} ({game.name[:40]}): "
                    f"{str(error)[:120]}",
                    flush=True,
                )

    ready = [game for game in batch if game.app_id in enriched]
    if not ready:
        return []
    if failed:
        print(
            f"[WARN] {len(failed)}/{len(batch)} items skipped in this batch, "
            "rerun to pick them up",
            flush=True,
        )

    embedding_inputs = [
        build_embedding_text(game, *enriched[game.app_id])
        for game in ready
    ]
    vectors = embed_documents(embedding_inputs)
    points = []
    for game, vector in zip(ready, vectors, strict=True):
        tags, summary = enriched[game.app_id]
        search_text = build_embedding_text(game, tags, summary)
        payload = game_payload(game, llm_tags=tags, summary=summary, search_text=search_text)
        payload["enrichment_model"] = (
            f"{embedding_info()['model']}|{get_deepseek_config().model}"
        )
        points.append(PointStruct(id=game.app_id, vector=vector, payload=payload))

    qdrant.upsert(collection_name=COLLECTION_NAME, points=points, wait=True)
    return [point.id for point in points]


def main() -> int:
    args = parse_args()
    if not args.data.is_file():
        raise SystemExit(f"Dataset not found: {args.data}")
    if not deepseek_configured():
        raise SystemExit("DEEPSEEK_API_KEY is required for tags, summaries, and explanations")

    chat_config = get_deepseek_config()
    embed_info = embedding_info()
    qdrant = get_client()
    if not args.dry_run:
        ensure_collection(qdrant, reset=args.reset)
    if args.reset or not qdrant.collection_exists(COLLECTION_NAME):
        known_ids: set[int] = set()
    else:
        known_ids = existing_ids(qdrant)
    print(f"[QDRANT] collection={COLLECTION_NAME} existing={len(known_ids):,}", flush=True)
    print(
        f"[MODELS] chat={chat_config.provider}/{chat_config.model} "
        f"embedding={embed_info['model']} ({embed_info['dimension']}d)",
        flush=True,
    )

    if args.dry_run:
        try:
            estimate_run(args, known_ids)
        finally:
            qdrant.close()
        return 0

    started = time.time()
    processed = 0
    batch: list[CleanGame] = []
    batch_size = max(1, args.batch_size)

    # games.csv order is arbitrary, so "the first N rows" gives an index whose
    # median game has ~100 reviews and which misses well-known titles entirely.
    # --order-by reviews restricts the run to the most-reviewed candidates.
    wanted: set[int] | None = None
    if args.order_by == "reviews":
        wanted = set(select_new_app_ids(
            args.data,
            limit=args.limit,
            min_reviews=args.min_reviews,
            include_demos=args.include_demos,
            known_ids=known_ids,
            order="reviews",
        ))
        print(f"[SELECT] {len(wanted):,} candidates ranked by review count", flush=True)

    for game in iter_games(
        args.data,
        min_reviews=args.min_reviews,
        exclude_non_games=not args.include_demos,
    ):
        if processed >= args.limit:
            break
        if game.app_id in known_ids:
            continue
        if wanted is not None and game.app_id not in wanted:
            continue
        batch.append(game)
        target_size = min(batch_size, max(1, args.limit - processed))
        if len(batch) < target_size:
            continue
        written = process_batch(
            qdrant=qdrant,
            batch=batch,
            workers=args.workers,
        )
        processed += len(written)
        known_ids.update(written)
        batch.clear()
        print(f"[ENRICH] {processed:,}/{args.limit:,}", flush=True)
        if processed >= args.limit:
            break

    if batch and processed < args.limit:
        remaining = batch[:max(0, args.limit - processed)]
        written = process_batch(
            qdrant=qdrant,
            batch=remaining,
            workers=args.workers,
        )
        processed += len(written)
        known_ids.update(written)

    qdrant.close()
    elapsed = time.time() - started
    usage = usage_snapshot()
    print(f"[DONE] added {processed:,} games in {elapsed:.1f}s", flush=True)
    if processed:
        print(
            f"[RATE] {processed / elapsed * 60:.1f} games/min "
            f"({elapsed / processed:.2f}s per game)",
            flush=True,
        )
    print(
        f"[USAGE] llm_calls={usage['calls']:,} "
        f"prompt_tokens={usage['prompt_tokens']:,} "
        f"completion_tokens={usage['completion_tokens']:,}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
