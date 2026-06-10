import csv
import json
from collections import defaultdict
import config as cfg
from strategies import create_strategy
from metrics import compute_metrics


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def main() -> None:
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

    vector = create_strategy("vector_only", dict(base))
    hybrid = create_strategy("hybrid", dict(base))

    by_profile = defaultdict(lambda: {"v_mrr": [], "h_mrr": [], "v_s1": [], "h_s1": [], "count": 0})

    try:
        with open(cfg.QUERYSET_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                query_text = row.get("query_text", "")
                try:
                    gold_ids = set(json.loads(row.get("gold_ids", "[]")))
                except Exception:
                    gold_ids = set()

                v_docs, _ = vector.retrieve(query_text, 10)
                h_docs, h_meta = hybrid.retrieve(query_text, 10)
                profile = str(h_meta.get("retrieval_mode", "unknown"))

                v_ids = [doc.get("modelMd5") for doc in v_docs if doc.get("modelMd5")]
                h_ids = [doc.get("modelMd5") for doc in h_docs if doc.get("modelMd5")]

                v_m = compute_metrics(v_ids, gold_ids)
                h_m = compute_metrics(h_ids, gold_ids)

                by_profile[profile]["count"] += 1
                by_profile[profile]["v_mrr"].append(v_m.get("mrr_at_10", 0.0))
                by_profile[profile]["h_mrr"].append(h_m.get("mrr_at_10", 0.0))
                by_profile[profile]["v_s1"].append(v_m.get("success_at_1", 0.0))
                by_profile[profile]["h_s1"].append(h_m.get("success_at_1", 0.0))
    finally:
        vector.cleanup()
        hybrid.cleanup()

    for profile, data in by_profile.items():
        print(
            f"{profile}: n={data['count']} "
            f"MRR vector={mean(data['v_mrr']):.4f} hybrid={mean(data['h_mrr']):.4f} "
            f"S@1 vector={mean(data['v_s1']):.4f} hybrid={mean(data['h_s1']):.4f}"
        )


if __name__ == "__main__":
    main()
