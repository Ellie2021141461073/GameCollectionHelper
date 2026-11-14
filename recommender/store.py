from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from .clean import CleanGame


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env.local")
load_dotenv(PROJECT_ROOT / ".env")

COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "steam_games")
VECTOR_SIZE = int(os.getenv("EMBEDDING_DIM", "1024"))
QDRANT_PATH = Path(os.getenv("QDRANT_PATH", str(PROJECT_ROOT / "recommender" / "data" / "qdrant")))


def get_client() -> QdrantClient:
    remote_url = os.getenv("QDRANT_URL", "").strip()
    if remote_url:
        return QdrantClient(
            url=remote_url,
            api_key=os.getenv("QDRANT_API_KEY") or None,
        )
    QDRANT_PATH.mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=str(QDRANT_PATH))


def ensure_collection(client: QdrantClient, *, reset: bool = False) -> None:
    exists = client.collection_exists(COLLECTION_NAME)
    if reset:
        client.recreate_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        return
    if not exists:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )


def game_payload(game: CleanGame, *, llm_tags: list[str], summary: str, search_text: str) -> dict:
    return {
        "app_id": game.app_id,
        "name": game.name,
        "normalized_name": game.normalized_name,
        "release_date": game.release_date.isoformat() if game.release_date else None,
        "estimated_owners_min": game.estimated_owners_min,
        "estimated_owners_max": game.estimated_owners_max,
        "peak_ccu": game.peak_ccu,
        "price": game.price,
        "discount": game.discount,
        "dlc_count": game.dlc_count,
        "description": game.description,
        "header_image": game.header_image,
        "website": game.website,
        "developers": game.developers,
        "publishers": game.publishers,
        "categories": game.categories,
        "genres": game.genres,
        "source_tags": game.source_tags,
        "llm_tags": llm_tags,
        "summary": summary,
        "search_text": search_text,
        "positive": game.positive,
        "negative": game.negative,
        "review_count": game.review_count,
        "recommendations": game.recommendations,
        "achievements": game.achievements,
        "windows": game.windows,
        "mac": game.mac,
        "linux": game.linux,
        "average_playtime_forever": game.average_playtime_forever,
        "median_playtime_forever": game.median_playtime_forever,
    }


def existing_ids(client: QdrantClient) -> set[int]:
    ids: set[int] = set()
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=COLLECTION_NAME,
            limit=512,
            offset=offset,
            with_payload=False,
            with_vectors=False,
        )
        ids.update(int(point.id) for point in points)
        if offset is None:
            return ids


def all_points(client: QdrantClient) -> list:
    points = []
    offset = None
    while True:
        batch, offset = client.scroll(
            collection_name=COLLECTION_NAME,
            limit=512,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        points.extend(batch)
        if offset is None:
            return points
