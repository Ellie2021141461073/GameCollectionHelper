"""HTTP contract tests for the FastAPI recommender service.

These exercise the real route handlers (validation, RRF fusion, explanation
fallback) against an in-memory document set, so they need neither Qdrant nor
BGE-M3/PyTorch. The retrieval and embedding boundaries are patched.

They are skipped automatically when the lightweight runtime deps are absent:

    python -m pip install fastapi httpx python-dotenv qdrant-client openai

Run with:  python -m unittest discover -s tests/python
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

# Disable every LLM path before importing the module: load_dotenv() does not
# override variables that already exist, so an empty value wins over .env.local.
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["RECOMMENDER_CHAT_API_KEY"] = ""

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - exercised only in the stdlib-only job
    raise unittest.SkipTest("fastapi/httpx not installed")

from recommender.ranking import BM25Index
from recommender.service import Document, SearchState, app
from recommender.text import tokenize


class FakeQdrantClient:
    """Stand-in for the local Qdrant client (only close() is used)."""

    closed = False

    def close(self) -> None:
        FakeQdrantClient.closed = True


def make_document(app_id: int, name: str, search_text: str, **payload) -> Document:
    body = {
        "app_id": app_id,
        "name": name,
        "normalized_name": name.casefold(),
        "search_text": search_text,
        "summary": f"{name} 的摘要",
        "llm_tags": search_text.split()[:3],
        "genres": ["Simulation"],
        "positive": 100,
        "negative": 5,
        "recommendations": 100,
        "header_image": f"https://cdn.example/{app_id}.jpg",
    }
    body.update(payload)
    return Document(
        app_id=app_id,
        vector=[float(app_id), 0.0],
        payload=body,
        tokens=tokenize(search_text)[:500],
    )


class ServiceContractTest(unittest.TestCase):
    documents: list[Document] = []

    @classmethod
    def setUpClass(cls) -> None:
        cls.documents = [
            make_document(1, "Alpha Farm", "cozy farming simulation"),
            make_document(2, "Beta Farm", "farming building simulation"),
            make_document(3, "Gamma Shooter", "fast action shooter"),
        ]

    def setUp(self) -> None:
        import recommender.service as service

        self.service = service
        service._state = SearchState(
            client=FakeQdrantClient(),
            documents=self.documents,
            bm25=BM25Index([document.tokens for document in self.documents]),
        )
        service._explanation_cache.clear()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.service._state = None
        self.service._explanation_cache.clear()

    def test_health(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})

    def test_status_reports_the_loaded_collection(self) -> None:
        payload = self.client.get("/status").json()
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["documents"], 3)
        self.assertEqual(payload["vector_size"], 2)
        self.assertFalse(payload["llm_explanations"])

    def test_similar_excludes_the_query_item_and_explains_every_hit(self) -> None:
        hits = [(1, 0.99), (2, 0.9), (3, 0.2)]
        with mock.patch.object(self.service, "qdrant_search", return_value=hits):
            response = self.client.get("/similar", params={"q": "Alpha Farm", "limit": 2})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["mode"], "similar")
        self.assertEqual(payload["source"]["name"], "Alpha Farm")
        app_ids = [item["app_id"] for item in payload["results"]]
        self.assertNotIn(1, app_ids)
        self.assertEqual(len(app_ids), 2)
        for item in payload["results"]:
            self.assertTrue(item["explanation"])
            self.assertGreaterEqual(item["match_percent"], 0)

    def test_similar_accepts_a_numeric_app_id(self) -> None:
        with mock.patch.object(self.service, "qdrant_search", return_value=[(2, 0.9)]):
            response = self.client.get("/similar", params={"q": "2"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"]["app_id"], 2)

    def test_similar_matches_names_case_and_punctuation_insensitively(self) -> None:
        with mock.patch.object(self.service, "qdrant_search", return_value=[(1, 0.5)]):
            response = self.client.get("/similar", params={"q": "  alpha   FARM! "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"]["app_id"], 1)

    def test_unknown_game_returns_404(self) -> None:
        response = self.client.get("/similar", params={"q": "No Such Game Anywhere"})
        self.assertEqual(response.status_code, 404)

    def test_blank_game_name_returns_400(self) -> None:
        response = self.client.get("/similar", params={"q": "   "})
        self.assertEqual(response.status_code, 400)

    def test_search_fuses_both_retrievers(self) -> None:
        with mock.patch.object(self.service, "embed_query", return_value=[1.0, 0.0]), \
                mock.patch.object(self.service, "qdrant_search", return_value=[(3, 0.8), (2, 0.7)]):
            response = self.client.get("/search", params={"q": "farming building", "limit": 3})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["mode"], "search")
        self.assertEqual(payload["query"], "farming building")
        app_ids = [item["app_id"] for item in payload["results"]]
        # 2 hits both retrievers, so RRF puts it on top.
        self.assertEqual(app_ids[0], 2)
        for item in payload["results"]:
            self.assertTrue(item["explanation"])
            self.assertIn("vector_score", item)
            self.assertIn("bm25_score", item)

    def test_search_respects_limit(self) -> None:
        with mock.patch.object(self.service, "embed_query", return_value=[1.0, 0.0]), \
                mock.patch.object(self.service, "qdrant_search", return_value=[(3, 0.8), (1, 0.7)]):
            payload = self.client.get("/search", params={"q": "farming", "limit": 1}).json()
        self.assertEqual(len(payload["results"]), 1)

    def test_limit_above_the_maximum_is_rejected(self) -> None:
        response = self.client.get("/search", params={"q": "farming", "limit": 50})
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
