import json
from pathlib import Path

results_dir = Path('docs/rag-experiments')
latest = max(results_dir.glob('run_result_*_detailed.json'), key=lambda p: p.stat().st_mtime)

print(f'Latest file: {latest.name}')
with open(latest, 'r', encoding='utf-8') as f:
    data = json.load(f)

vo = data.get('vector_only', {})
print(f'nDCG@10: {vo.get("ndcg_at_10")}')
print(f'Recall@10: {vo.get("recall_at_10")}')
print(f'Generation success rate: {vo.get("generation_success_rate")}')
print(f'Keys: {list(vo.keys())}')
