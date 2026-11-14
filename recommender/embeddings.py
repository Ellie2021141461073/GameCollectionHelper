from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv

from .store import PROJECT_ROOT


load_dotenv(PROJECT_ROOT / ".env.local")
load_dotenv(PROJECT_ROOT / ".env")

MODEL_NAME = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
MODEL_REVISION = os.getenv(
    "EMBEDDING_REVISION",
    "b28ce2a6fcc9c75ef1c0619575d0ec19af760082",
)
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))
cache_value = os.getenv("EMBEDDING_CACHE_PATH", "recommender/data/embeddings-bge-m3")
CACHE_PATH = Path(cache_value)
if not CACHE_PATH.is_absolute():
    CACHE_PATH = PROJECT_ROOT / CACHE_PATH
local_value = os.getenv("EMBEDDING_LOCAL_PATH", "recommender/data/models/bge-m3")
LOCAL_MODEL_PATH = Path(local_value)
if not LOCAL_MODEL_PATH.is_absolute():
    LOCAL_MODEL_PATH = PROJECT_ROOT / LOCAL_MODEL_PATH
DEVICE = os.getenv("EMBEDDING_DEVICE", "cpu")
DTYPE = os.getenv("EMBEDDING_DTYPE", "float32").strip().lower()
EMBEDDING_BATCH_SIZE = max(
    1,
    int(os.getenv("EMBEDDING_BATCH_SIZE", "4" if DEVICE.startswith("cuda") else "8")),
)
MAX_SEQ_LENGTH = max(64, int(os.getenv("EMBEDDING_MAX_SEQ_LENGTH", "1024")))

_model = None
_lock = threading.Lock()


def model_kwargs() -> dict:
    if not DEVICE.startswith("cuda"):
        return {}
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("PyTorch is required for CUDA embeddings") from exc
    if not torch.cuda.is_available():
        raise RuntimeError(
            "EMBEDDING_DEVICE requests CUDA, but the installed PyTorch has no "
            "available CUDA device. Install a CUDA-enabled PyTorch build."
        )
    supported = {
        "float16": torch.float16,
        "bfloat16": torch.bfloat16,
        "float32": torch.float32,
    }
    if DTYPE not in supported:
        raise RuntimeError(
            f"Unsupported EMBEDDING_DTYPE={DTYPE}. "
            "Use float16, bfloat16, or float32."
        )
    return {
        "dtype": supported[DTYPE],
        "low_cpu_mem_usage": True,
    }


def get_embedding_model():
    global _model
    if _model is not None:
        return _model
    with _lock:
        if _model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError(
                    "Sentence Transformers is not installed. Run "
                    "`python -m pip install -r recommender/requirements.txt`."
                ) from exc
            CACHE_PATH.mkdir(parents=True, exist_ok=True)
            if (LOCAL_MODEL_PATH / "pytorch_model.bin").is_file():
                _model = SentenceTransformer(
                    str(LOCAL_MODEL_PATH),
                    device=DEVICE,
                    model_kwargs=model_kwargs(),
                )
            else:
                _model = SentenceTransformer(
                    MODEL_NAME,
                    cache_folder=str(CACHE_PATH),
                    device=DEVICE,
                    revision=MODEL_REVISION,
                    model_kwargs=model_kwargs(),
                )
            _model.max_seq_length = MAX_SEQ_LENGTH
    return _model


def embed_documents(
    texts: Iterable[str],
    batch_size: int | None = None,
) -> list[list[float]]:
    model = get_embedding_model()
    vectors = model.encode(
        list(texts),
        batch_size=batch_size or EMBEDDING_BATCH_SIZE,
        normalize_embeddings=True,
        show_progress_bar=False,
    ).tolist()
    if vectors and len(vectors[0]) != EMBEDDING_DIM:
        raise RuntimeError(
            f"Embedding dimension mismatch: {MODEL_NAME} returned {len(vectors[0])}, "
            f"but EMBEDDING_DIM={EMBEDDING_DIM}"
        )
    return vectors


def embed_query(text: str) -> list[float]:
    return embed_documents([text], batch_size=1)[0]


def embedding_info() -> dict:
    return {
        "model": MODEL_NAME,
        "revision": MODEL_REVISION,
        "dimension": EMBEDDING_DIM,
        "cache_path": str(CACHE_PATH),
        "local_path": str(LOCAL_MODEL_PATH) if LOCAL_MODEL_PATH.exists() else None,
        "device": DEVICE,
        "dtype": DTYPE,
        "batch_size": EMBEDDING_BATCH_SIZE,
        "max_seq_length": MAX_SEQ_LENGTH,
    }
