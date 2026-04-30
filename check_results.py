import json

with open('docs/rag-experiments/run_result_20260430_104044_detailed.json') as f:
    data = json.load(f)

vo = data['vector_only']
print(f"Query results count: {len(vo.get('query_results', []))}")
print(f"Avg metrics keys: {list(vo.get('avg_metrics', {}).keys()) if 'avg_metrics' in vo else 'NOT FOUND'}")
print(f"Success rate: {vo.get('generation_success_rate')}")
print(f"nDCG: {vo.get('ndcg_at_10')}")

if vo.get('query_results'):
    for q in vo['query_results'][:3]:
        print(f"\nQuery {q.get('query_id')}: error={q.get('error')} metrics={list(q.get('metrics', {}).keys())}")
