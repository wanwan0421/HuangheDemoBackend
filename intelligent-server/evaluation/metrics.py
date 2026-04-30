"""
RAG 评测指标计算库
包含：Recall@K, MRR@K, Success@1 等
"""

from typing import List, Dict, Set


def recall_at_k(retrieved_ids: List[str], gold_ids: Set[str], k: int) -> float:
    """
    计算 Recall@K
    Args:
        retrieved_ids: 检索到的 ID 列表（已排序）
        gold_ids: 正确目标 ID 集合
        k: 截断位置
    Returns:
        Recall@K 值，范围 [0, 1]
    """
    if not gold_ids:
        return 0.0
    
    top_k_ids = set(retrieved_ids[:k])
    hits = len(top_k_ids & gold_ids)
    
    return hits / len(gold_ids)


def precision_at_k(retrieved_ids: List[str], gold_ids: Set[str], k: int) -> float:
    """计算 Precision@K"""
    if k == 0 or not retrieved_ids:
        return 0.0
    
    top_k_ids = set(retrieved_ids[:k])
    hits = len(top_k_ids & gold_ids)
    
    return hits / min(k, len(retrieved_ids))


def mrr_at_k(retrieved_ids: List[str], gold_ids: Set[str], k: int) -> float:
    """
    计算 MRR@K（Mean Reciprocal Rank）
    Args:
        retrieved_ids: 检索到的 ID 列表（已排序）
        gold_ids: 正确目标 ID 集合
        k: 截断位置
    Returns:
        MRR@K 值，范围 [0, 1]
    """
    for rank, doc_id in enumerate(retrieved_ids[:k], start=1):
        if doc_id in gold_ids:
            return 1.0 / rank
    
    return 0.0


def success_at_1(retrieved_ids: List[str], gold_ids: Set[str]) -> float:
    """
    计算 Success@1（首条是否正确）
    Returns:
        1.0 if success, 0.0 otherwise
    """
    if not retrieved_ids or not gold_ids:
        return 0.0
    
    return 1.0 if retrieved_ids[0] in gold_ids else 0.0


def compute_metrics(retrieved_ids: List[str], gold_ids: Set[str], 
                   query_id: str = "") -> Dict[str, float]:
    """
    一次性计算所有指标
    Args:
        retrieved_ids: 检索到的 ID 列表
        gold_ids: 正确目标 ID 集合
        query_id: 查询 ID（仅用于日志）
        relevance_mapping: ID 到相关度的映射
    Returns:
        指标字典
    """
    return {
        "recall_at_5": recall_at_k(retrieved_ids, gold_ids, 5),
        "recall_at_10": recall_at_k(retrieved_ids, gold_ids, 10),
        "recall_at_20": recall_at_k(retrieved_ids, gold_ids, 20),
        "precision_at_5": precision_at_k(retrieved_ids, gold_ids, 5),
        "precision_at_10": precision_at_k(retrieved_ids, gold_ids, 10),
        "mrr_at_10": mrr_at_k(retrieved_ids, gold_ids, 10),
        "success_at_1": success_at_1(retrieved_ids, gold_ids),
    }


def aggregate_metrics(all_metrics: List[Dict[str, float]]) -> Dict[str, float]:
    """
    聚合多个查询的指标（计算平均值）
    Args:
        all_metrics: 每个查询的指标字典列表
    Returns:
        平均指标
    """
    if not all_metrics:
        return {}
    
    avg_metrics = {}
    for key in all_metrics[0].keys():
        values = [m[key] for m in all_metrics]
        avg_metrics[key] = sum(values) / len(values)
    
    return avg_metrics
