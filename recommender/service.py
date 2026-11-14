from __future__ import annotations

import json
import math
import os
import re
from collections import Counter
from dataclasses import dataclass
from difflib import get_close_matches
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .chat import chat_configured, create_json_completion, get_chat_config
from .embeddings import embed_query, embedding_info
from .store import COLLECTION_NAME, PROJECT_ROOT, all_points, get_client


load_dotenv(PROJECT_ROOT / ".env.local")
load_dotenv(PROJECT_ROOT / ".env")

app = FastAPI(title="GameCollectionHelper Hybrid Recommender", version="1.0.0")
origins = [origin.strip() for origin in os.getenv("RECOMMENDER_CORS_ORIGINS", "http://localhost:3000").split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
def close_qdrant() -> None:
    global _state
    if _state is not None:
        _state.client.close()
        _state = None

STOP_WORDS = {
    "the", "and", "for", "with", "from", "that", "this", "into", "your", "you",
    "are", "its", "game", "games", "steam", "about", "will", "can", "all",
}
ENGLISH_TOKEN = re.compile(r"[a-z0-9][a-z0-9+#.-]*")
CHINESE_RUN = re.compile(r"[\u4e00-\u9fff]+")


def tokenize(text: str) -> list[str]:
    lowered = (text or "").casefold()
    tokens = [token for token in ENGLISH_TOKEN.findall(lowered) if len(token) > 1 and token not in STOP_WORDS]
    for run in CHINESE_RUN.findall(lowered):
        if len(run) <= 4:
            tokens.append(run)
        tokens.extend(run[index:index + 2] for index in range(max(0, len(run) - 1)))
    return tokens


@dataclass
class Document:
    app_id: int
    vector: list[float]
    payload: dict[str, Any]
    tokens: list[str]


class BM25Index:
    def __init__(self, documents: list[Document], k1: float = 1.5, b: float = 0.75):
        self.documents = documents
        self.k1 = k1
        self.b = b
        self.postings: dict[str, list[tuple[int, int]]] = {}
        lengths = []
        for index, document in enumerate(documents):
            counts = Counter(document.tokens)
            lengths.append(sum(counts.values()))
            for term, frequency in counts.items():
                self.postings.setdefault(term, []).append((index, frequency))
        self.lengths = lengths
        self.average_length = sum(lengths) / max(1, len(lengths))
        total = max(1, len(documents))
        self.idf = {
            term: math.log(1 + (total - len(entries) + 0.5) / (len(entries) + 0.5))
            for term, entries in self.postings.items()
        }

    def search(self, query_tokens: list[str], limit: int) -> list[tuple[int, float]]:
        scores = [0.0] * len(self.documents)
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
        ranked = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)[:limit]
        return [(index, scores[index]) for index in ranked if scores[index] > 0]


@dataclass
class SearchState:
    client: Any
    documents: list[Document]
    bm25: BM25Index


_state: SearchState | None = None
_explanation_cache: dict[str, dict[int, str]] = {}


def load_state() -> SearchState:
    global _state
    if _state is not None:
        return _state
    client = get_client()
    if not client.collection_exists(COLLECTION_NAME):
        raise RuntimeError("Qdrant collection is empty. Run recommender.enrich_qdrant first.")
    points = all_points(client)
    documents = []
    for point in points:
        payload = dict(point.payload or {})
        vector_value = point.vector
        if isinstance(vector_value, dict):
            vector_value = next(iter(vector_value.values()), [])
        vector = [float(value) for value in (vector_value or [])]
        if not vector:
            continue
        documents.append(Document(
            app_id=int(payload.get("app_id", point.id)),
            vector=vector,
            payload=payload,
            tokens=tokenize(str(payload.get("search_text", "")))[:500],
        ))
    if not documents:
        raise RuntimeError("Qdrant collection contains no enriched vectors.")
    _state = SearchState(client=client, documents=documents, bm25=BM25Index(documents))
    return _state


def qdrant_search(client: Any, vector: list[float], limit: int) -> list[tuple[int, float]]:
    if hasattr(client, "query_points"):
        response = client.query_points(
            collection_name=COLLECTION_NAME,
            query=vector,
            limit=limit,
            with_payload=False,
        )
        points = response.points
    else:
        points = client.search(
            collection_name=COLLECTION_NAME,
            query_vector=vector,
            limit=limit,
            with_payload=False,
        )
    return [(int(point.id), float(point.score)) for point in points]


def find_source(state: SearchState, query: str) -> Document:
    value = query.strip()
    if not value:
        raise HTTPException(status_code=400, detail="请输入游戏名称或 AppID")
    if value.isdigit():
        app_id = int(value)
        for document in state.documents:
            if document.app_id == app_id:
                return document
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", value.casefold()).strip()
    exact = [doc for doc in state.documents if doc.payload.get("normalized_name") == normalized]
    if exact:
        return exact[0]
    contains = [
        doc for doc in state.documents
        if normalized and normalized in str(doc.payload.get("normalized_name", ""))
    ]
    if contains:
        return min(contains, key=lambda doc: len(str(doc.payload.get("name", ""))))
    names = [str(doc.payload.get("normalized_name", "")) for doc in state.documents]
    matches = get_close_matches(normalized, names, n=1, cutoff=0.72)
    if matches:
        match = matches[0]
        return next(doc for doc in state.documents if doc.payload.get("normalized_name") == match)
    raise HTTPException(status_code=404, detail=f"未找到游戏：{query}")


def quality_score(payload: dict[str, Any]) -> float:
    positive = max(0, int(payload.get("positive") or 0))
    negative = max(0, int(payload.get("negative") or 0))
    bayesian = (positive + 40 * 0.8) / (positive + negative + 40)
    popularity = min(1.0, math.log1p(max(0, int(payload.get("recommendations") or 0))) / 12)
    return 0.8 * bayesian + 0.2 * popularity


def merge_rankings(
    vector_results: list[tuple[int, float]],
    bm25_results: list[tuple[int, float]],
    state: SearchState,
    limit: int,
    exclude_id: int | None = None,
) -> list[dict[str, Any]]:
    by_id = {document.app_id: document for document in state.documents}
    merged: dict[int, dict[str, Any]] = {}
    for rank, (app_id, score) in enumerate(vector_results, 1):
        if app_id == exclude_id:
            continue
        item = merged.setdefault(app_id, {"app_id": app_id, "rrf": 0.0})
        item["rrf"] += 1 / (60 + rank)
        item["vector_score"] = score
    for rank, (index, score) in enumerate(bm25_results, 1):
        app_id = state.documents[index].app_id
        if app_id == exclude_id:
            continue
        item = merged.setdefault(app_id, {"app_id": app_id, "rrf": 0.0})
        item["rrf"] += 1 / (60 + rank)
        item["bm25_score"] = score
    for item in merged.values():
        document = by_id.get(item["app_id"])
        if not document:
            continue
        item["payload"] = document.payload
        item["hybrid_score"] = item["rrf"] + 0.004 * quality_score(document.payload)
    ranked = sorted(merged.values(), key=lambda item: item.get("hybrid_score", 0), reverse=True)[:limit]
    maximum = max((item["hybrid_score"] for item in ranked), default=1)
    for item in ranked:
        item["match_percent"] = round(item["hybrid_score"] / maximum * 100, 1)
    return ranked


def fallback_reason(source: dict[str, Any], result: dict[str, Any]) -> str:
    source_tags = {
        str(tag).casefold()
        for tag in (source.get("llm_tags") or []) + (source.get("genres") or []) + (source.get("source_tags") or [])
    }
    result_tags = list(result.get("llm_tags") or []) + list(result.get("genres") or [])
    shared = [tag for tag in result_tags if str(tag).casefold() in source_tags]
    if shared:
        return f"与当前游戏共享 {', '.join(shared[:3])} 等特征，并同时命中词法与语义检索。"
    return "游戏内容在向量空间中较为接近，并通过质量与热度重排进入推荐结果。"


def explain_results(
    source: dict[str, Any],
    results: list[dict[str, Any]],
    query_text: str | None = None,
) -> dict[int, str]:
    if not results:
        return {}
    cache_key = json.dumps([
        query_text,
        source.get("app_id"),
        [item["app_id"] for item in results],
    ], ensure_ascii=False, sort_keys=True)
    if cache_key in _explanation_cache:
        return _explanation_cache[cache_key]
    fallback = {item["app_id"]: fallback_reason(source, item["payload"]) for item in results}
    if not chat_configured():
        _explanation_cache[cache_key] = fallback
        return fallback
    try:
        payload = {
            "query": query_text,
            "source": {
                "name": source.get("name"),
                "summary": source.get("summary"),
                "tags": source.get("llm_tags"),
            },
            "recommendations": [
                {
                    "app_id": item["app_id"],
                    "name": item["payload"].get("name"),
                    "summary": item["payload"].get("summary"),
                    "tags": item["payload"].get("llm_tags"),
                }
                for item in results
            ],
        }
        content = create_json_completion(
            (
                "Explain why each Steam game is recommended. Use only supplied metadata. "
                'Return JSON: {"items":[{"app_id":123,"reason":"one concise Chinese sentence"}]}'
            ),
            json.dumps(payload, ensure_ascii=False),
        )
        data = json.loads(content)
        reasons = {
            int(item["app_id"]): str(item["reason"])[:220]
            for item in data.get("items", [])
            if item.get("app_id") is not None and item.get("reason")
        }
        resolved = {item["app_id"]: reasons.get(item["app_id"], fallback[item["app_id"]]) for item in results}
        _explanation_cache[cache_key] = resolved
        return resolved
    except Exception:
        _explanation_cache[cache_key] = fallback
        return fallback


def response_items(source: dict[str, Any], ranked: list[dict[str, Any]], query_text: str | None = None):
    explanations = explain_results(source, ranked, query_text)
    return [
        {
            "app_id": item["app_id"],
            "name": item["payload"].get("name"),
            "summary": item["payload"].get("summary"),
            "header_image": item["payload"].get("header_image"),
            "release_date": item["payload"].get("release_date"),
            "price": item["payload"].get("price"),
            "genres": item["payload"].get("genres") or [],
            "tags": item["payload"].get("llm_tags") or item["payload"].get("source_tags") or [],
            "match_percent": item["match_percent"],
            "vector_score": round(float(item.get("vector_score") or 0), 5),
            "bm25_score": round(float(item.get("bm25_score") or 0), 5),
            "explanation": explanations.get(item["app_id"], ""),
        }
        for item in ranked
    ]


@app.get("/status")
def status():
    try:
        state = load_state()
        return {
            "ready": True,
            "collection": COLLECTION_NAME,
            "documents": len(state.documents),
            "vector_size": len(state.documents[0].vector) if state.documents else 0,
            "llm_explanations": chat_configured(),
            "chat_model": get_chat_config().model if chat_configured() else None,
            "embedding": embedding_info(),
        }
    except Exception as exc:
        return {"ready": False, "error": str(exc)}


@app.get("/similar")
def similar(q: str = Query(..., min_length=1), limit: int = Query(8, ge=1, le=20)):
    state = load_state()
    source = find_source(state, q)
    query_tokens = tokenize(
        " ".join([
            str(source.payload.get("name", "")),
            str(source.payload.get("summary", "")),
            " ".join(source.payload.get("llm_tags") or []),
            " ".join(source.payload.get("genres") or []),
        ])
    )[:100]
    vector_results = qdrant_search(state.client, source.vector, 50)
    lexical_results = state.bm25.search(query_tokens, 50)
    ranked = merge_rankings(vector_results, lexical_results, state, limit, source.app_id)
    return {
        "mode": "similar",
        "source": {
            "app_id": source.app_id,
            "name": source.payload.get("name"),
            "summary": source.payload.get("summary"),
        },
        "results": response_items(source.payload, ranked),
    }


@app.get("/search")
def search(q: str = Query(..., min_length=1), limit: int = Query(8, ge=1, le=20)):
    state = load_state()
    vector = embed_query(q)
    vector_results = qdrant_search(state.client, vector, 50)
    lexical_results = state.bm25.search(tokenize(q)[:100], 50)
    ranked = merge_rankings(vector_results, lexical_results, state, limit)
    source = {"app_id": None, "name": "智能搜索", "summary": q, "llm_tags": tokenize(q)[:8]}
    return {
        "mode": "search",
        "query": q,
        "results": response_items(source, ranked, q),
    }


@app.get("/health")
def health():
    return {"ok": True}
