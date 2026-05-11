import config as cfg
from pymilvus import connections, Collection


def percentile(values, p):
    if not values:
        return 0
    idx = int(len(values) * p)
    idx = min(max(idx, 0), len(values) - 1)
    return values[idx]


def main() -> None:
    connections.connect(alias="default", host=cfg.MILVUS_HOST, port=int(cfg.MILVUS_PORT))
    col = Collection(cfg.MILVUS_COLLECTION)
    col.load()

    rows = col.query(
        expr='modelMd5 != ""',
        limit=10000,
        output_fields=["modelText"],
    )

    lengths = [len(str(row.get("modelText", "") or "")) for row in rows]
    lengths.sort()

    print("count=", len(lengths))
    if lengths:
        print("avg_len=", round(sum(lengths) / len(lengths), 1))
        print("p50=", percentile(lengths, 0.50))
        print("p90=", percentile(lengths, 0.90))
        print("p95=", percentile(lengths, 0.95))
        print("max=", lengths[-1])


if __name__ == "__main__":
    main()
