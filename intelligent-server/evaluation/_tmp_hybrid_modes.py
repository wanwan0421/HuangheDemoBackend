import csv
import json
from collections import Counter
import config as cfg
from strategies import create_strategy
from metrics import compute_metrics


def main() -> None:
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

    strategy = create_strategy("hybrid", strategy_config)
    mode_counter = Counter()
    mode_mrr_sum = Counter()

    try:
        with open(cfg.QUERYSET_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                query_text = row.get("query_text", "")
                try:
                    gold_ids = set(json.loads(row.get("gold_ids", "[]")))
                except Exception:
                    gold_ids = set()

                docs, meta = strategy.retrieve(query_text, 10)
                mode = str(meta.get("retrieval_mode", "unknown"))
                retrieved_ids = [doc.get("modelMd5") for doc in docs if doc.get("modelMd5")]
                m = compute_metrics(retrieved_ids, gold_ids)

                mode_counter[mode] += 1
                mode_mrr_sum[mode] += m.get("mrr_at_10", 0.0)
    finally:
        strategy.cleanup()

    print("mode_counts:")
    for mode, cnt in mode_counter.items():
        avg_mrr = mode_mrr_sum[mode] / cnt if cnt else 0.0
        print(f"  {mode}: {cnt} queries, avg_mrr@10={avg_mrr:.4f}")


if __name__ == "__main__":
    main()
