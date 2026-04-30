# RAG 评测框架快速启动指南

## 📋 文件结构

```
evaluation/
├── __init__.py
├── config.py              # 配置（LLM、MongoDB、路径等）
├── metrics.py             # 指标计算库
├── strategies.py          # 检索策略实现（No-RAG、Vector-only）
├── evaluator.py           # 主评估框架
├── run_eval.py            # 启动脚本
└── README.md              # 此文件
```

## 🚀 快速开始

### 前提条件

1. 环境变量已配置（`.env` 文件）：
   ```
   AIHUBMIX_API_KEY=xxx
   AIHUBMIX_BASE_URL=xxx
   MONGO_URI=mongodb://localhost:27017/
   DB_NAME=huanghe-demo
   ```

2. 依赖已安装：
   ```bash
   pip install openai pymongo python-dotenv
   ```

3. 查询集已准备：
   - 位置：`docs/rag-experiments/queryset_template.csv`
   - 格式：CSV，包含 query_id, query_text, gold_ids 等字段

### Step 1: 准备数据集

在 `docs/rag-experiments/queryset_template.csv` 中填入你的查询：

```csv
query_id,query_text,query_type,gold_ids,relevance_grade,notes
Q0001,黄河流域土壤侵蚀敏感性评估应优先使用哪些模型,术语,"[\"md5_a\",\"md5_b\"]",2,
Q0002,给我一个水文径流模拟模型,通用,"[\"md5_c\"]",1,
...
```

**重要**: `gold_ids` 字段必须是 JSON 数组格式。

### Step 2: 运行评测

#### 基础用法（评测 No-RAG 和 Vector-only）

```bash
cd g:\LWH\model\huanghe-demo-back\intelligent-server

python evaluation/run_eval.py \
  --strategies no_rag vector_only \
  --runs 1 \
  --queryset ../../docs/rag-experiments/queryset_template.csv
```

#### 高级用法

```bash
# 评测单个策略
python evaluation/run_eval.py --strategies no_rag --runs 3

# 评测多个策略并重复 3 次
python evaluation/run_eval.py --strategies no_rag vector_only --runs 3

# 指定输出路径
python evaluation/run_eval.py \
  --strategies no_rag vector_only \
  --output results/rag_eval
```

## 📊 输出结果

评测会生成两个文件：

### 1. CSV 结果（用于对比）
```
run_result_20260429_142530.csv
```

包含列：
- strategy
- total_queries
- recall_at_5 / recall_at_10 / recall_at_20
- mrr_at_10
- success_at_1
- avg_time_seconds

### 2. 详细结果（用于调试）
```
run_result_20260429_142530_detailed.json
```

包含：
- 每条查询的检索结果和指标
- 生成时长、Token 数量
- 错误信息（如有）

## 🧪 实验场景

### 场景 A: No-RAG vs Vector-only

对比直接提问 vs 通过向量检索提问的效果：

```bash
python evaluation/run_eval.py \
  --strategies no_rag vector_only \
  --runs 1
```

观察指标：
- **Recall@10**: Vector-only 应该显著高于 No-RAG（因为有检索）
- **Success@1**: 两者差异应不大（都看首条）
- **时延**: No-RAG 应更快（无检索开销）

### 场景 B: 参数实验

如果要测试不同的 top_k：

编辑 `config.py`：
```python
VECTOR_TOPK = 20  # 改成 20、50 等
```

然后重新运行。

## 🔧 自定义策略

如果你想添加新的策略（如 Hybrid），修改 `strategies.py`：

```python
class HybridStrategy(RAGStrategy):
    def retrieve(self, query: str, top_k: int = 10):
        # 实现你的混合检索逻辑
        pass
    
    def generate(self, query: str, context: Optional[str] = None):
        # 基于检索结果生成回答
        pass
```

然后在 `config.py` 的 `STRATEGIES` 字典中注册。

## 📈 计算指标详解

所有指标都在 `metrics.py` 中实现：

- **Recall@K**: 前 K 个结果中有多少正确（召回率）
- **Precision@K**: 前 K 个结果中正确的比例
- **MRR@K**: 首个正确结果的倒数排名
- **Success@1**: 首条是否正确

更详细说明见 `docs/rag-experiments/RAG_EXPERIMENT_PLAYBOOK.md`。

## 🐛 调试

如果评测失败，检查日志：

1. 查看控制台输出（会打印每条查询的处理状态）
2. 检查 `.env` 文件是否正确
3. 确保 MongoDB 连接正常
4. 确保 API Key 有效

如有错误，会在详细 JSON 结果中记录 `"error"` 字段。

## 📝 完整工作流

```
1. 准备数据集
   ↓
2. 运行 No-RAG & Vector-only 评测
   ↓
3. 查看 CSV 对比结果
   ↓
4. 分析详细 JSON（找出 fails 样例）
   ↓
5. 如果满足门槛 → 考虑上线
   如果不满足 → 调整参数重新测试
```

更多详情见 `docs/rag-experiments/RAG_EXPERIMENT_PLAYBOOK.md`。
