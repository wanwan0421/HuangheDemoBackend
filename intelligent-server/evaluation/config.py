"""
评测框架配置
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

# ======================== LLM 配置 ========================
AIHUBMIX_API_KEY = os.getenv("AIHUBMIX_API_KEY", "")
AIHUBMIX_BASE_URL = os.getenv("AIHUBMIX_BASE_URL", "")

LLM_CONFIG = {
    "model": "gpt-5-mini",
    "temperature": 0.7,
    "max_tokens": 1024,
    "top_p": 0.95,
}

# ======================== 嵌入模型配置 ========================
EMBEDDING_CONFIG = {
    "model": "gemini-embedding-001",
}

# ======================== MongoDB 配置 ========================
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = os.getenv("DB_NAME", "huanghe-demo")

# ======================== 数据集配置 ========================
# 数据集 CSV 路径（相对或绝对）
QUERYSET_PATH = os.getenv("QUERYSET_PATH")
QUERYSET_PATH = _resolve_path(
    QUERYSET_PATH,
    "docs/rag-experiments/queryset_template.csv",
)

# 结果输出路径
RESULT_PREFIX = os.getenv("RESULT_PREFIX")
RESULT_PREFIX = _resolve_path(
    RESULT_PREFIX,
    "docs/rag-experiments/run_result",
)

# ======================== 检索配置 ========================
VECTOR_TOPK = 10  # 向量检索返回 top-k
FINAL_TOPK = 10   # 最终输出 top-k

# ======================== 评测配置 ========================
BATCH_SIZE = 10  # 批量处理的查询数

# 日志级别
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ======================== 策略标志 ========================
# 用于运行时选择策略
STRATEGIES = {
    "no_rag": {
        "name": "A-NoRAG",
        "description": "不使用RAG，直接大模型生成",
    },
    "vector_only": {
        "name": "B-VectorOnly",
        "description": "仅向量检索",
    },
    "hybrid": {
        "name": "C-Hybrid",
        "description": "关键词+语义混合",
        "dense_topk": 50,
        "keyword_topk": 50,
        "fusion": "rrf",
        "fusion_param": {"k": 60},
    }
}
