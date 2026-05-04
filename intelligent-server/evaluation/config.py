"""
Configuration for the RAG evaluation scripts.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolve_path(path_value: str, default_relative: str) -> str:
    candidate = path_value or default_relative
    path = Path(candidate)
    if path.is_absolute():
        return str(path)
    return str((REPO_ROOT / path).resolve())


# LLM
AIHUBMIX_API_KEY = os.getenv("AIHUBMIX_API_KEY", "")
AIHUBMIX_BASE_URL = os.getenv("AIHUBMIX_BASE_URL", "")

LLM_CONFIG = {
    "model": "gpt-5-mini",
    "temperature": 0.7,
    "max_tokens": 1024,
    "top_p": 0.95,
}

# Embedding
EMBEDDING_CONFIG = {
    "model": "gemini-embedding-001",
}

# MongoDB
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = os.getenv("DB_NAME", "huanghe-demo")

# Milvus
MILVUS_HOST = os.getenv("MILVUS_HOST", "localhost")
MILVUS_PORT = int(os.getenv("MILVUS_PORT", "19530"))
MILVUS_COLLECTION = os.getenv("MILVUS_COLLECTION", "modelembeddings")

# Dataset and result paths
QUERYSET_PATH = _resolve_path(
    os.getenv("QUERYSET_PATH"),
    "docs/rag-experiments/queryset_template.csv",
)
RESULT_PREFIX = _resolve_path(
    os.getenv("RESULT_PREFIX"),
    "docs/rag-experiments/run_result",
)

# Retrieval
VECTOR_TOPK = 10
FINAL_TOPK = 10

# Evaluation
BATCH_SIZE = 10
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Strategy metadata and default hybrid params.
STRATEGIES = {
    "no_rag": {
        "name": "A-NoRAG",
        "description": "No retrieval, direct generation",
    },
    "vector_only": {
        "name": "B-VectorOnly",
        "description": "Dense vector retrieval only",
    },
    "sparse_only": {
        "name": "C-SparseOnly",
        "description": "BM25 sparse retrieval only",
    },
    "hybrid": {
        "name": "D-HybridAdaptive",
        "description": "Adaptive dense + BM25 hybrid retrieval",
        "dense_topk": 50,
        "keyword_topk": 50,
        "semantic_weight": 0.65,
        "keyword_weight": 0.35,
        "rrf_k": 60,
    },
    "hybrid_weighted": {
        "name": "E-HybridWeighted",
        "description": "Fixed weighted dense + BM25 hybrid retrieval",
    },
    "hybrid_rrf": {
        "name": "F-HybridRRF",
        "description": "Fixed RRF dense + BM25 hybrid retrieval",
    },
}
