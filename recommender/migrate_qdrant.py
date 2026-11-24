"""Copy the embedded (local-file) Qdrant store into a Qdrant server.

The embedded store keeps every point in a single ``storage.sqlite`` that the
Qdrant server cannot read, so switching to the docker-compose stack needs one
re-upload. Point ids, vectors and payloads are copied verbatim: nothing is
re-embedded and no LLM call is made.

Usage (embedded store on the host, Qdrant server in a container):

    # stop the local recommender first: the embedded store is single-process
    python -m recommender.migrate_qdrant --target http://127.0.0.1:6333
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Iterator
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from .store import COLLECTION_NAME, QDRANT_PATH, VECTOR_SIZE


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy an embedded Qdrant store into a Qdrant server"
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=QDRANT_PATH,
        help="embedded store directory (default: $QDRANT_PATH)",
    )
    parser.add_argument(
        "--target",
        default="http://127.0.0.1:6333",
        help="Qdrant server URL (default: http://127.0.0.1:6333)",
    )
    parser.add_argument("--collection", default=COLLECTION_NAME)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the collection on the server before uploading",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report how many points would be copied",
    )
    return parser.parse_args()


def iter_batches(
    client: QdrantClient,
    collection: str,
    batch_size: int,
) -> Iterator[list]:
    """Yield points with payload and vectors, ``batch_size`` at a time."""
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        if not points:
            return
        yield points
        if offset is None:
            return


def connect(url: str, attempts: int = 30, delay: float = 1.0) -> QdrantClient:
    """Open a server client, waiting for the container to accept requests."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        client = QdrantClient(url=url, timeout=60)
        try:
            client.get_collections()
        except Exception as error:  # noqa: BLE001 - any transport error means "not ready"
            last_error = error
            client.close()
            if attempt == attempts:
                break
            if attempt == 1:
                print(f"[WAIT] {url} is not ready yet, retrying...", flush=True)
            time.sleep(delay)
            continue
        return client
    raise SystemExit(f"Cannot reach the Qdrant server at {url}: {last_error}")


def main() -> int:
    args = parse_args()
    if not args.source.is_dir():
        raise SystemExit(f"Embedded store not found: {args.source}")

    local = QdrantClient(path=str(args.source))
    try:
        if not local.collection_exists(args.collection):
            raise SystemExit(
                f"Collection {args.collection!r} does not exist in {args.source}"
            )
        config = local.get_collection(args.collection).config.params.vectors
        size = getattr(config, "size", None) or VECTOR_SIZE
        distance = getattr(config, "distance", None) or Distance.COSINE
        source_count = local.count(args.collection, exact=True).count
        print(
            f"[SOURCE] {args.source} collection={args.collection} "
            f"points={source_count:,} size={size} distance={distance}",
            flush=True,
        )
        if args.dry_run:
            return 0

        remote = connect(args.target)
        try:
            if args.reset and remote.collection_exists(args.collection):
                remote.delete_collection(args.collection)
                print(f"[TARGET] dropped existing collection {args.collection!r}", flush=True)
            if not remote.collection_exists(args.collection):
                remote.create_collection(
                    collection_name=args.collection,
                    vectors_config=VectorParams(size=size, distance=distance),
                )
                print(f"[TARGET] created collection {args.collection!r}", flush=True)

            started = time.time()
            uploaded = 0
            batch_size = max(1, args.batch_size)
            for batch in iter_batches(local, args.collection, batch_size):
                remote.upsert(
                    collection_name=args.collection,
                    points=[
                        PointStruct(id=point.id, vector=point.vector, payload=point.payload)
                        for point in batch
                    ],
                    wait=True,
                )
                uploaded += len(batch)
                print(f"[UPLOAD] {uploaded:,}/{source_count:,}", flush=True)

            target_count = remote.count(args.collection, exact=True).count
        finally:
            remote.close()
    finally:
        local.close()

    elapsed = time.time() - started
    print(
        f"[DONE] source={source_count:,} target={target_count:,} in {elapsed:.1f}s "
        f"({uploaded / max(elapsed, 1e-9):,.0f} points/s)",
        flush=True,
    )
    if target_count != source_count:
        print("[FAIL] point counts differ", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
