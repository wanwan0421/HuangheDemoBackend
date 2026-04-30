"""
RAG 评测框架

包含：
- 指标计算（Recall、MRR 等）
- 策略实现（No-RAG、Vector-only 等）
- 评测框架（数据集加载、指标聚合等）
"""

from .metrics import (
    recall_at_k,
    precision_at_k,
    mrr_at_k,
    success_at_1,
    compute_metrics,
    aggregate_metrics,
)

from .strategies import (
    RAGStrategy,
    NoRAGStrategy,
    VectorOnlyStrategy,
    create_strategy,
)

from .evaluator import (
    RAGEvaluator,
    evaluate_all_strategies,
    print_summary,
)

__version__ = "0.1.0"

__all__ = [
    "recall_at_k",
    "precision_at_k",
    "mrr_at_k",
    "success_at_1",
    "compute_metrics",
    "aggregate_metrics",
    "RAGStrategy",
    "NoRAGStrategy",
    "VectorOnlyStrategy",
    "create_strategy",
    "RAGEvaluator",
    "evaluate_all_strategies",
    "print_summary",
]
