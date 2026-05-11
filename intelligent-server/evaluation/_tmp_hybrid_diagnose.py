import csv
import json
import time
import config as cfg
from strategies import create_strategy
from metrics import compute_metrics, aggregate_metrics


def load_queries():
    queries = []
    with open(cfg.QUERYSET_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                gold = set(json.loads(row.get("gold_ids", "[]")))
            except Exception:
                gold = set()
            queries.append((row.get("query_text", ""), gold))
    return queries


def run_case(name: str, override: dict):
    base = {
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
    base.update(override)

    strategy_name = override.get("strategy_name", "hybrid")
    strategy = create_strategy(strategy_name, base)
    queries = load_queries()

    metrics_list = []
    total_ret = 0.0
    total_emb = 0.0

    t0 = time.time()
    try:
        for query_text, gold in queries:
            docs, meta = strategy.retrieve(query_text, 10)
            retrieved_ids = [d.get("modelMd5") for d in docs if d.get("modelMd5")]
            metrics_list.append(compute_metrics(retrieved_ids, gold))
            total_ret += float(meta.get("retrieval_time", 0.0) or 0.0)
            total_emb += float(meta.get("embedding_time", 0.0) or 0.0)
    finally:
        strategy.cleanup()

    agg = aggregate_metrics(metrics_list)
    print(f"[{name}] elapsed={time.time()-t0:.1f}s ret_avg={total_ret/len(queries):.4f}s emb_avg={total_emb/len(queries):.4f}s")
    print(
        f"  P@5={agg.get('precision_at_5',0):.3f} R@5={agg.get('recall_at_5',0):.3f} "
        f"R@10={agg.get('recall_at_10',0):.3f} MRR@10={agg.get('mrr_at_10',0):.3f} S@1={agg.get('success_at_1',0):.3f}"
    )


if __name__ == "__main__":
    run_case("vector_baseline", {"strategy_name": "vector_only"})
    run_case("hybrid_default", {"strategy_name": "hybrid"})
    run_case("hybrid_keyword_light", {
        "strategy_name": "hybrid_weighted",
        "hybrid_semantic_weight": 0.9,
        "hybrid_keyword_weight": 0.1,
    })
    run_case("hybrid_small_candidates", {
        "strategy_name": "hybrid_weighted",
        "hybrid_semantic_weight": 0.85,
        "hybrid_keyword_weight": 0.15,
        "hybrid_dense_topk": 20,
        "hybrid_keyword_topk": 20,
    })
