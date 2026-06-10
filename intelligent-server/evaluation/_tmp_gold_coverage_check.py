import csv
import json
import config as cfg
from pymilvus import connections, Collection


def main() -> None:
    query_gold_ids = []
    all_gold = set()

    with open(cfg.QUERYSET_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ids = json.loads(row.get("gold_ids", "[]"))
            except Exception:
                ids = []
            ids = [str(x).strip() for x in ids if str(x).strip()]
            query_gold_ids.append(ids)
            all_gold.update(ids)

    connections.connect(alias="default", host=cfg.MILVUS_HOST, port=int(cfg.MILVUS_PORT))
    col = Collection(cfg.MILVUS_COLLECTION)
    col.load()

    rows = col.query(
        expr='modelMd5 != ""',
        limit=10000,
        output_fields=["modelMd5"],
    )
    corpus_md5 = {
        str(row.get("modelMd5", "")).strip()
        for row in rows
        if str(row.get("modelMd5", "")).strip()
    }

    missing_gold = sorted([x for x in all_gold if x not in corpus_md5])
    query_any_gold = sum(1 for ids in query_gold_ids if any(i in corpus_md5 for i in ids))
    query_all_gold = sum(1 for ids in query_gold_ids if ids and all(i in corpus_md5 for i in ids))

    print("queries=", len(query_gold_ids))
    print("unique_gold_ids=", len(all_gold))
    print("milvus_modelMd5=", len(corpus_md5))
    print("missing_gold_ids=", len(missing_gold))
    print("query_has_at_least_one_gold_in_corpus=", query_any_gold)
    print("query_all_gold_in_corpus=", query_all_gold)
    print("sample_missing=", missing_gold[:20])


if __name__ == "__main__":
    main()
