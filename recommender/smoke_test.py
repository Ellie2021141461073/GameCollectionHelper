import os
import tempfile

from fastapi.testclient import TestClient
from qdrant_client.models import PointStruct


def main():
    with tempfile.TemporaryDirectory() as directory:
        os.environ["QDRANT_PATH"] = directory
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ["DEEPSEEK_API_KEY"] = ""
        os.environ["RECOMMENDER_CHAT_API_KEY"] = ""
        # A card-page OpenAI key must never switch the recommender to a provider
        # the user did not select.
        os.environ["OPENAI_API_KEY"] = "card-page-key-must-not-be-reused"

        from recommender.store import COLLECTION_NAME, ensure_collection, get_client
        from recommender.chat import chat_configured, deepseek_configured
        from recommender.service import app

        assert not deepseek_configured()
        assert not chat_configured()

        client = get_client()
        ensure_collection(client, reset=True)
        client.upsert(COLLECTION_NAME, [
            PointStruct(id=1, vector=[1.0] + [0.0] * 1023, payload={
                "app_id": 1, "name": "Alpha Farm", "normalized_name": "alpha farm",
                "search_text": "cozy farming simulation", "summary": "cozy farming game",
                "llm_tags": ["farming", "cozy"], "genres": ["Simulation"],
                "positive": 100, "negative": 5, "recommendations": 100,
            }),
            PointStruct(id=2, vector=[0.9, 0.1] + [0.0] * 1022, payload={
                "app_id": 2, "name": "Beta Farm", "normalized_name": "beta farm",
                "search_text": "farming building simulation", "summary": "building and farming game",
                "llm_tags": ["farming", "building"], "genres": ["Simulation"],
                "positive": 80, "negative": 4, "recommendations": 80,
            }),
            PointStruct(id=3, vector=[0.0, 0.0, 1.0] + [0.0] * 1021, payload={
                "app_id": 3, "name": "Gamma Shooter", "normalized_name": "gamma shooter",
                "search_text": "action shooter", "summary": "fast action game",
                "llm_tags": ["shooter"], "genres": ["Action"],
                "positive": 50, "negative": 10, "recommendations": 20,
            }),
        ], wait=True)
        client.close()

        with TestClient(app) as test:
            status = test.get("/status").json()
            similar = test.get("/similar?q=Alpha%20Farm&limit=2")
            search = test.get("/search?q=farming%20building&limit=2")
            assert status["ready"] is True
            assert status["documents"] == 3
            assert status["vector_size"] == 1024
            assert status["llm_explanations"] is False
            assert similar.status_code == 200
            assert search.status_code == 200
            assert similar.json()["source"]["name"] == "Alpha Farm"
            assert all(item["explanation"] for item in search.json()["results"])
            print({
                "status": {
                    "ready": status["ready"],
                    "documents": status["documents"],
                    "vector_size": status["vector_size"],
                    "llm_explanations": status["llm_explanations"],
                },
                "similar": similar.status_code,
                "source": similar.json().get("source", {}).get("name"),
                "similar_results": [item["name"] for item in similar.json().get("results", [])],
                "search": search.status_code,
                "search_results": [item["name"] for item in search.json().get("results", [])],
                "explanations": [bool(item["explanation"]) for item in search.json().get("results", [])],
            })


if __name__ == "__main__":
    main()
