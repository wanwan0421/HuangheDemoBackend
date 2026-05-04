"""
主评估框架
读取数据集，执行策略，计算指标，汇总结果
"""

import csv
import json
import logging
import time
from typing import List, Dict, Any, Tuple, Set
from datetime import datetime
import traceback

from metrics import compute_metrics, aggregate_metrics
from strategies import create_strategy
import config as cfg

logging.basicConfig(
    level=getattr(logging, cfg.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class RAGEvaluator:
    """RAG 评估器"""
    
    def __init__(self, queryset_path: str):
        self.queryset_path = queryset_path
        self.queries = []
        self.load_queryset()
    
    def load_queryset(self):
        """从 CSV 加载查询集"""
        try:
            with open(self.queryset_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # 解析 gold_ids（JSON 格式）
                    gold_ids_str = row.get("gold_ids", "[]")
                    try:
                        gold_ids = json.loads(gold_ids_str)
                    except json.JSONDecodeError:
                        gold_ids = []
                    
                    self.queries.append({
                        "query_id": row.get("query_id", ""),
                        "query_text": row.get("query_text", ""),
                        "query_type": row.get("query_type", "unknown"),
                        "gold_ids": set(gold_ids) if gold_ids else set(),
                        "relevance_grade": int(row.get("relevance_grade", 0)),
                    })
            
            logger.info(f"加载查询集: {len(self.queries)} 条")
        
        except Exception as e:
            logger.error(f"加载查询集失败: {str(e)}")
            raise
    
    def evaluate_strategy(self, strategy_name: str, runs: int = 1) -> Dict[str, Any]:
        """
        评测单个策略
        Args:
            strategy_name: 策略名称 ("no_rag" 或 "vector_only")
            runs: 重复运行次数
        Returns:
            评测结果字典
        """
        logger.info(f"开始评测策略: {strategy_name} (运行 {runs} 次)")
        
        all_run_results = []
        
        for run_idx in range(runs):
            logger.info(f"  --- 第 {run_idx + 1} 次运行 ---")
            
            run_result = self._evaluate_single_run(strategy_name)
            all_run_results.append(run_result)
        
        # 合并多次运行的结果
        merged_result = self._merge_runs(all_run_results, strategy_name)
        
        logger.info(f"策略 {strategy_name} 评测完成")
        logger.info(f"  Recall@10: {merged_result['recall_at_10']:.4f}")
        logger.info(f"  Success@1: {merged_result['success_at_1']:.4f}")
        
        return merged_result
    
    def _evaluate_single_run(self, strategy_name: str) -> Dict[str, Any]:
        """执行单次评测"""
        
        # 创建策略
        strategy_config = {
            "aihubmix_api_key": cfg.AIHUBMIX_API_KEY,
            "aihubmix_base_url": cfg.AIHUBMIX_BASE_URL,
            "mongo_uri": cfg.MONGO_URI,
            "db_name": cfg.DB_NAME,
            "milvus_host": cfg.MILVUS_HOST,
            "milvus_port": cfg.MILVUS_PORT,
            "milvus_collection": cfg.MILVUS_COLLECTION,
            "llm_model": cfg.LLM_CONFIG["model"],
            "llm_temperature": cfg.LLM_CONFIG["temperature"],
            "llm_max_tokens": cfg.LLM_CONFIG["max_tokens"],
            "embedding_model": cfg.EMBEDDING_CONFIG["model"],
            "hybrid_dense_topk": cfg.STRATEGIES["hybrid"].get("dense_topk", 50),
            "hybrid_keyword_topk": cfg.STRATEGIES["hybrid"].get("keyword_topk", 50),
            "hybrid_semantic_weight": cfg.STRATEGIES["hybrid"].get("semantic_weight", 0.65),
            "hybrid_keyword_weight": cfg.STRATEGIES["hybrid"].get("keyword_weight", 0.35),
            "hybrid_rrf_k": cfg.STRATEGIES["hybrid"].get("rrf_k", 60),
        }
        
        strategy = create_strategy(strategy_name, strategy_config)
        
        # 评测结果
        query_results = []
        all_metrics = []
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_tokens = 0
        total_retrieval_time = 0.0
        total_generation_time = 0.0
        successful_generation_count = 0
        successful_retrieval_count = 0
        
        start_time = time.time()
        
        try:
            for i, query_info in enumerate(self.queries):
                logger.info(f"  处理 [{i+1}/{len(self.queries)}] {query_info['query_id']}")
                
                try:
                    query_text = query_info["query_text"]
                    gold_ids = query_info["gold_ids"]
                    
                    # 执行检索
                    retrieved_docs, retrieval_meta = strategy.retrieve(query_text, cfg.VECTOR_TOPK)
                    
                    # 生成context
                    context = strategy.build_context(retrieved_docs)

                    # 执行生成
                    answer, generation_meta = strategy.generate(query_text, context)

                    # 提取检索到的 ID 列表
                    retrieved_ids = [doc.get("modelMd5") for doc in retrieved_docs]
                    
                    # 计算指标
                    metrics = compute_metrics(retrieved_ids, gold_ids, query_info["query_id"])
                    all_metrics.append(metrics)

                    retrieval_time = float(retrieval_meta.get("retrieval_time", 0.0) or 0.0)
                    generation_time = float(generation_meta.get("generation_time", 0.0) or 0.0)
                    prompt_tokens = int(generation_meta.get("input_tokens", 0) or 0)
                    completion_tokens = int(generation_meta.get("output_tokens", 0) or 0)
                    query_total_tokens = prompt_tokens + completion_tokens

                    total_retrieval_time += retrieval_time
                    total_generation_time += generation_time
                    total_prompt_tokens += prompt_tokens
                    total_completion_tokens += completion_tokens
                    total_tokens += query_total_tokens

                    if retrieved_ids:
                        successful_retrieval_count += 1
                    if answer:
                        successful_generation_count += 1
                    
                    # 记录结果
                    query_results.append({
                        "query_id": query_info["query_id"],
                        "query_text": query_text,
                        "query_type": query_info["query_type"],
                        "gold_ids": list(gold_ids),
                        "retrieved_ids": retrieved_ids,
                        "metrics": metrics,
                        "retrieval_meta": retrieval_meta,
                        "generation_meta": generation_meta,
                        "total_tokens": query_total_tokens,
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "retrieval_time": retrieval_time,
                        "generation_time": generation_time,
                        "answer_preview": answer[:200] if answer else "",
                    })
                
                except Exception as e:
                    logger.error(f"    评测 {query_info['query_id']} 失败: {str(e)}")
                    logger.error(traceback.format_exc())
                    
                    # 记录失败
                    query_results.append({
                        "query_id": query_info["query_id"],
                        "error": str(e),
                    })
        
        finally:
            strategy.cleanup()
        
        elapsed = time.time() - start_time
        
        # 聚合指标
        avg_metrics = aggregate_metrics(all_metrics) if all_metrics else {}
        
        return {
            "strategy": strategy_name,
            "run_time": datetime.now().isoformat(),
            "total_queries": len(self.queries),
            "successful_queries": len(query_results),
            "elapsed_seconds": elapsed,
            "avg_retrieval_time_seconds": total_retrieval_time / len(self.queries) if self.queries else 0.0,
            "avg_generation_time_seconds": total_generation_time / len(self.queries) if self.queries else 0.0,
            "avg_prompt_tokens": total_prompt_tokens / len(self.queries) if self.queries else 0.0,
            "avg_completion_tokens": total_completion_tokens / len(self.queries) if self.queries else 0.0,
            "avg_total_tokens": total_tokens / len(self.queries) if self.queries else 0.0,
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "total_tokens": total_tokens,
            "retrieval_success_rate": successful_retrieval_count / len(self.queries) if self.queries else 0.0,
            "generation_success_rate": successful_generation_count / len(self.queries) if self.queries else 0.0,
            "avg_metrics": avg_metrics,
            "query_results": query_results,
        }
    
    def _merge_runs(self, run_results: List[Dict[str, Any]], strategy_name: str) -> Dict[str, Any]:
        """合并多次运行的结果（计算均值和标准差）"""
        
        if not run_results:
            return {}
        
        # 取第一次运行的结果作为基准
        merged = {
            "strategy": strategy_name,
            "runs": len(run_results),
            "total_queries": run_results[0]["total_queries"],
            "successful_queries": int(sum(r.get("successful_queries", 0) for r in run_results) / len(run_results)),
        }
        
        # 聚合指标
        # 定义默认指标键，即使没有成功的查询也要包含这些键
        default_metric_keys = ["recall_at_5", "recall_at_10", "recall_at_20", 
                      "precision_at_5", "precision_at_10", "mrr_at_10", 
                      "success_at_1"]
        
        metric_keys = list(run_results[0]["avg_metrics"].keys()) if run_results[0]["avg_metrics"] else default_metric_keys
        # 确保至少包含默认键
        metric_keys = list(set(metric_keys) | set(default_metric_keys))
        
        for key in metric_keys:
            values = [r["avg_metrics"].get(key, 0) for r in run_results]
            avg_value = sum(values) / len(values) if values else 0
            merged[key] = avg_value
        
        # 聚合时延
        total_times = [r["elapsed_seconds"] for r in run_results]
        merged["avg_time_seconds"] = sum(total_times) / len(total_times)

        merged["avg_retrieval_time_seconds"] = sum(
            r.get("avg_retrieval_time_seconds", 0.0) for r in run_results
        ) / len(run_results)
        merged["avg_generation_time_seconds"] = sum(
            r.get("avg_generation_time_seconds", 0.0) for r in run_results
        ) / len(run_results)

        merged["avg_prompt_tokens"] = sum(
            r.get("avg_prompt_tokens", 0.0) for r in run_results
        ) / len(run_results)
        merged["avg_completion_tokens"] = sum(
            r.get("avg_completion_tokens", 0.0) for r in run_results
        ) / len(run_results)
        merged["avg_total_tokens"] = sum(
            r.get("avg_total_tokens", 0.0) for r in run_results
        ) / len(run_results)

        merged["total_prompt_tokens"] = sum(
            r.get("total_prompt_tokens", 0) for r in run_results
        )
        merged["total_completion_tokens"] = sum(
            r.get("total_completion_tokens", 0) for r in run_results
        )
        merged["total_tokens"] = sum(
            r.get("total_tokens", 0) for r in run_results
        )

        merged["retrieval_success_rate"] = sum(
            r.get("retrieval_success_rate", 0.0) for r in run_results
        ) / len(run_results)
        merged["generation_success_rate"] = sum(
            r.get("generation_success_rate", 0.0) for r in run_results
        ) / len(run_results)
        
        return merged


def evaluate_all_strategies(strategies_list: List[str], runs: int = 1) -> Dict[str, Any]:
    """
    评测所有指定的策略
    Args:
        strategies_list: 策略名称列表，如 ["no_rag", "vector_only"]
        runs: 每个策略的重复运行次数
    Returns:
        所有策略的评测结果
    """
    evaluator = RAGEvaluator(cfg.QUERYSET_PATH)
    
    all_results = {}
    
    for strategy_name in strategies_list:
        result = evaluator.evaluate_strategy(strategy_name, runs)
        all_results[strategy_name] = result
    
    return all_results


def print_summary(results: Dict[str, Any]):
    """打印评测总结"""
    print("\n" + "="*80)
    print("RAG 评测总结")
    print("="*80)
    
    for strategy_name, result in results.items():
        print(f"\n策略: {strategy_name}")
        print(f"  样本数: {result.get('total_queries', 0)}")
        print(f"  成功数: {result.get('successful_queries', 0)}")
        print(f"  平均时间: {result.get('avg_time_seconds', 0):.2f}s")
        print(f"  平均检索时间: {result.get('avg_retrieval_time_seconds', 0):.4f}s")
        print(f"  平均生成时间: {result.get('avg_generation_time_seconds', 0):.4f}s")
        print(f"  平均 Prompt Tokens: {result.get('avg_prompt_tokens', 0):.2f}")
        print(f"  平均 Completion Tokens: {result.get('avg_completion_tokens', 0):.2f}")
        print(f"  平均总 Tokens: {result.get('avg_total_tokens', 0):.2f}")
        print(f"  总 Tokens: {result.get('total_tokens', 0)}")
        
        metrics = result.get("avg_metrics", {})
        if metrics:
            print(f"  Recall@5:  {metrics.get('recall_at_5', 0):.4f}")
            print(f"  Recall@10: {metrics.get('recall_at_10', 0):.4f}")
            print(f"  Recall@20: {metrics.get('recall_at_20', 0):.4f}")
            print(f"  MRR@10:    {metrics.get('mrr_at_10', 0):.4f}")
            print(f"  Success@1: {metrics.get('success_at_1', 0):.4f}")
    
    print("\n" + "="*80)
