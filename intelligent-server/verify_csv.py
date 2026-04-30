import csv
from pathlib import Path
import json

csv_path = Path('g:\\LWH\\model\\huanghe-demo-back\\docs\\rag-experiments\\queryset_template.csv')
with open(csv_path, 'r', encoding='utf-8-sig', newline='') as f:
    reader = csv.DictReader(f)
    rows = list(reader)

print(f'Total rows: {len(rows)}')
print(f'\nFirst row:')
print(f'  ID: {rows[0]["query_id"]}')
print(f'  Gold IDs: {rows[0]["gold_ids"]}')

print(f'\nRow 69 (Q069 - multi-gold):')
print(f'  ID: {rows[68]["query_id"]}')
print(f'  Gold IDs: {rows[68]["gold_ids"]}')
try:
    gold_ids = json.loads(rows[68]["gold_ids"])
    print(f'  Parsed: {gold_ids}')
except Exception as e:
    print(f'  Parse error: {e}')

print(f'\nRow 93 (Q093 - multi-gold):')
print(f'  ID: {rows[92]["query_id"]}')
print(f'  Gold IDs: {rows[92]["gold_ids"]}')
try:
    gold_ids = json.loads(rows[92]["gold_ids"])
    print(f'  Parsed: {gold_ids}')
except Exception as e:
    print(f'  Parse error: {e}')

print('\n✓ CSV verification complete')
