# FastAPI hybrid recommender (BM25 + BGE-M3 + Qdrant + DeepSeek explanations).
#
# CPU-only on purpose: CPU wheels keep the image ~2 GB smaller than the CUDA
# build, and Docker Desktop does not expose the host GPU to Linux containers
# without the NVIDIA container toolkit. Set EMBEDDING_DEVICE=cuda plus a CUDA
# torch build if you really need GPU inference inside the container.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HUB_DISABLE_XET=1

WORKDIR /app

# libgomp1 is required by the CPU PyTorch wheel; curl is only for debugging.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install the CPU torch wheel first so sentence-transformers does not pull the
# multi-gigabyte CUDA build from PyPI.
COPY recommender/requirements.txt recommender/requirements.txt
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.6.0 \
    && pip install -r recommender/requirements.txt

COPY recommender/ recommender/

# The collection lives in the qdrant service; the model cache is a volume.
ENV QDRANT_URL=http://qdrant:6333 \
    EMBEDDING_DEVICE=cpu \
    EMBEDDING_DTYPE=float32 \
    EMBEDDING_CACHE_PATH=recommender/data/embeddings-bge-m3

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=120s --retries=5 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]

CMD ["uvicorn", "recommender.service:app", "--host", "0.0.0.0", "--port", "8000"]
