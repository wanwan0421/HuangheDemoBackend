# RAG 检索策略对比实验手册

## 1. 目标
对比以下策略在同一数据集、同一模型、同一提示词条件下的效果与成本：

- `A`: No-RAG（不检索，直接生成）
- `B`: Vector-only（仅向量检索）
- `C`: Hybrid（关键词 + 语义 + 融合）

可选消融（推荐）：

- `D`: Hybrid-wo-keyword（混合但去掉关键词）
- `E`: Hybrid-wo-semantic（混合但去掉语义）
- `F`: Hybrid-Weighted（加权融合）对比 `Hybrid-RRF`

## 2. 公平性约束（必须满足）

- 相同测试集：同一批 query，不新增不删除。
- 相同 LLM：同版本、同温度、同 system prompt。
- 相同生成参数：`max_tokens`、`top_p` 等一致。
- 相同 topK：先固定为 `10`（可再做参数实验）。
- 每组至少重复 `3` 次，记录均值和标准差。
- 每次实验保存 commit id 与配置快照。

## 3. 数据集规范

建议规模：`100~300` 条真实查询（第一轮最小可先做 80 条）。

覆盖类别（每类建议至少 15 条）：

- 通用描述型问题
- 专业术语/缩写型问题
- 多条件约束问题（时间+地区+主题）
- 长尾或低频问题
- 易混淆问题（同义词/近义词）

标注要求：

- `gold_ids`: 正确目标文档/模型 ID（可多值）
- `relevance_grade`: 0/1/2（不相关/相关/高度相关）
- `query_type`: 通用/术语/约束/长尾/混淆

## 4. 指标定义（离线）

检索质量：

- `Recall@5/10/20`
- `MRR@10`
- `nDCG@10`
- `Success@1`

端到端质量（可人工+模型评审）：

- `Answer Accuracy`（答案正确性）
- `Faithfulness`（是否基于证据）
- `Citation Support Rate`（关键结论可追溯比例）

性能与成本：

- `P50/P95` 端到端时延
- `Retrieval Latency` 检索时延
- `Generation Latency` 生成时延
- `Prompt Tokens / Completion Tokens / Total Tokens`
- `Token Cost`（输入/输出）
- `Error Rate`（超时/异常）

## 5. 通过门槛（建议值，可按业务微调）

设 `B=Vector-only`，`C=Hybrid`，上线门槛建议：

- 检索效果门槛：
  - `Recall@10(C) - Recall@10(B) >= +3%`
  - `nDCG@10(C) - nDCG@10(B) >= +2%`
  - `Success@1(C) - Success@1(B) >= +2%`
- 稳定性门槛：
  - `Error Rate(C) <= Error Rate(B) + 0.2%`
- 性能门槛：
  - `P95(C) <= 1.25 * P95(B)`
- 成本门槛：
  - `Total Tokens(C) <= 1.20 * Total Tokens(B)`
- 成本门槛：
  - `Cost(C) <= 1.20 * Cost(B)`

若效果提升明显（如 Recall@10 提升 >= 5% 且 Success@1 提升 >= 4%），可适度放宽时延到 `1.35x`。

## 6. 参数实验（Hybrid 必做）

第一轮粗扫建议：

- Dense topK: `20, 50`
- Keyword topK: `20, 50`
- 融合器：
  - `RRF(k=20,60,100)`
  - `Weighted(alpha=0.3,0.5,0.7)`
- 最终输出 topK: `5, 10`

第二轮细调：在最优组合周围做小范围网格搜索。

## 7. 统计显著性建议

- 对关键指标（Recall@10、nDCG@10、Success@1）做 bootstrap 置信区间。
- 或用配对 t 检验/符号检验（同 query 对比）。
- 若差异不显著，不建议直接结论“Hybrid 更优”。

## 8. 在线 A/B（灰度）

建议分桶：

- A: 10%
- B: 10%
- C: 10%
- 其余流量保持当前生产策略

观察至少 7 天，关注：

- 用户追问率（越低越好）
- 会话完成率（越高越好）
- 人工兜底率（越低越好）
- 超时率与异常率

## 9. 结果判定模板

使用 `results_summary.md` 记录最终结论，至少包含：

- 最优策略与配置
- 相比基线提升幅度（含置信区间）
- 成本/时延变化
- 是否达到上线门槛
- 风险与回滚策略

## 10. 最小执行清单（两周）

- D1-D2：准备并冻结测试集 + 标注
- D3-D5：离线检索评测（A/B/C + 消融）
- D6-D8：端到端质量评测
- D9-D10：参数调优 + 候选方案锁定
- D11-D14：线上小流量 A/B + 上线决策
