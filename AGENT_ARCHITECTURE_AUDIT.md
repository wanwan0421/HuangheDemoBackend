# 智能地理建模Agent系统 - 架构审计报告

## 📋 Executive Summary

本项目采用**LangGraph + MongoDB Checkpointer**的分布式Agent系统，实现了多阶段的地理建模任务链（需求解析 → 模型推荐 → 数据对齐 → 执行计划）。核心优势是**状态管理设计完善，工具注入机制灵活**；缺陷集中在**记忆机制单薄、安全隔离不足、可观测性缺失**。

---

## 🏗️ 系统架构

### 整体数据流

```
用户输入 (NestJS前端)
    ↓
resolveCurrentUserId() 
    ↓ [sessionId, userId, query]
FastAPI /api/agent/stream?query&sessionId
    ↓
LangGraph agent.astream(config={"thread_id": sessionId})
    ↓ [MongoDBSaver从DB恢复历史state]
╔═══════════════════════════════════════════════════════╗
║                  Agent 状态机                         ║
║  parse_task_spec → recommend_model → model_contract  ║
║        ↓ (tool_calls)                                 ║
║      tool_node (Milvus/MongoDB查询)                  ║
║        ↓ (ToolMessage)                                ║
║   should_continue() → 下一节点或END                   ║
╚═══════════════════════════════════════════════════════╝
    ↓
SSE流式返回 (token/tool_call/tool_result/final events)
    ↓
NestJS解析 + 保存message到MongoDB
    ↓
前端SSE消费 → 动态渲染timeline + 结果
```

### 五层架构

| 层 | 组件 | 技术 | 职责 |
|----|------|------|------|
| **应用层** | React SPA | React Router + Zustand | UI展示、会话管理、状态恢复 |
| **网关层** | NestJS Server | Express、Session模型 | 认证、授权、会话持久化、消息记录 |
| **编排层** | LangGraph Agent | StateGraph + Reducer | 多节点状态流转、工具调度 |
| **执行层** | FastAPI + Tools | Milvus、MongoDB、Embedding | 检索、数据扫描、对齐计算 |
| **存储层** | MongoDB + Milvus | 文档存储 + 向量数据库 | 会话、消息、向量索引 |

---

## 🔍 核心模块详解

### 1️⃣ 模型推荐Agent（agents/model_recommend/graph.py）

#### 状态定义
```python
class ModelState(TypedDict):
    messages: Annotated[list, operator.add]           # 消息链（追加语义）
    Task_spec: Annotated[Dict, operator.or_]         # 任务规范（并集覆盖）
    Model_contract: Annotated[Dict, operator.or_]    # 模型契约
    recommended_model: Annotated[Dict, operator.or_] # 推荐结果
    tool_results: Annotated[Dict, operator.or_]      # 工具缓存
    selected_model_md5: str
```

**Reducer语义**：
- `operator.add`：列表追加，保留完整消息链（无删除）
- `operator.or_`：字典并集，新值覆盖旧值（增量更新）

#### 核心节点
1. **parse_task_spec_node** → LLM提取 Domain/Target_object/Spatial_scope/Temporal_scope/Resolution
2. **recommend_model_node** → LLM+工具决策：是否需要search_relevant_models/search_most_model/get_model_details
3. **model_contract_node** → 根据模型workflow生成数据输入契约
4. **tool_node** → 执行工具列表，结果包装为ToolMessage
5. **should_continue()** 路由：
   - 已完成 + 无契约 → `model_contract_node`
   - 有task_spec但无模型 → `tool_node`
   - 其他 → `END`

#### 记忆机制
```python
checkpointer = MongoDBSaver(mongo_client)
agent = agent_builder.compile(checkpointer=checkpointer)

# 恢复：agent.astream(config={"configurable": {"thread_id": sessionId}})
```
- ✅ 历史state持久化到MongoDB的`checkpoints`表
- ❌ 无摘要压缩，长对话爆炸
- ❌ 无跨会话学习

### 2️⃣ 数据扫描Agent（agents/data_scan/graph.py）

#### 设计理念：工具链优先 + LLM语义补全

```
tool_node (确定性规则)          llm_node (语义增强)
├─ prepare_file                 └─ 补全Abstract/Apps/Tags
├─ detect_format
├─ analyze_dataset
└─ validate_consistency
    ↓
生成结构化profile
(Form/Spatial/Temporal/Quality/Validation/data_sources)
```

#### 优势
- 工具执行结果**100%可追溯**（手动包装ToolMessage）
- LLM仅做**后期语义增强**，不参与事实抽取
- 输出结构化且**可验证**

### 3️⃣ 会话协调器（agents/triangle_coordinator.py）

#### 设计
```python
TriangleMatchingSession:
  session_id, task_spec, model_contract, data_profiles, alignment_result
  
TriangleMatchingCoordinator:  # 全局单例
  sessions: Dict[str, TriangleMatchingSession]
```

#### 流程
1. model_recommend节点更新session → `task_spec + model_contract`
2. data_scan节点累积 → `data_profiles[]`
3. 当三者都到位 → 触发对齐Agent

#### 缺陷 ⚠️
- 内存单例，重启丢失
- 无过期清理，僵尸会话积累
- 无分布式支持（多进程/跨域问题）

### 4️⃣ 工具调用机制

#### 工具注入
```python
# 工具定义
@tool
def search_relevant_models(
    query: str,
    task_spec: Annotated[Dict, InjectedState],  # 自动注入
) -> Dict:
    pass

# 执行时
args_with_injected_state = inject_state_for_tool(
    tool, 
    tool_call.get("args", {}), 
    state  # ← 完整状态自动填充
)
observation = tool.invoke(args_with_injected_state)
```

#### 混合检索（Milvus）
```python
# 语义 + 关键词融合
query_profile = infer_query_profile(query)
# → dense_heavy (0.9/0.1) 或 keyword_aware (0.65/0.35)

dense_results = collection.search(query_embedding, limit=20)
keyword_results = collection.search(query_keywords, limit=20, using_sparse=True)

ranker = WeightedRanker(semantic_weight=0.65, keyword_weight=0.35)
hybrid_results = collection.search(
    [dense_req, keyword_req],
    ranker=ranker
)
```

---

## 🔐 安全机制

### ✅ 已实现（前端）
```typescript
// NestJS - 会话隔离
private async getOwnedSession(sessionId: string, userId: string) {
    const session = await this.sessionModel
        .findOne({ _id: sessionId, userId })  // ← 强制userId匹配
        .exec();
}

// 所有API都调用resolveCurrentUserId()
```

### ❌ 缺失（后端Agent）
```python
# ⚠️ FastAPI无认证
@app.get("/api/agent/stream")
async def stream_agent(query: str, sessionId: Optional[str] = None):
    # sessionId直接用thread_id，未校验owner
    # → 跨用户会话访问风险！
    
    agent.astream(config={"configurable": {"thread_id": sessionId}})
```

### 修复方案（见optimization_roadmap.md Priority-1）

---

## 📊 上下文管理现状

### 消息链保留（完整）
```python
messages: Annotated[list, operator.add]
# 所有消息永不删除，完整链式保留
```

### Token计数（缺失）
```python
# ❌ 当前：无token预算管理
# → 长对话会爆炸LLM context limit

# ✅ 建议：实现动态窗口
max_tokens = 4000
current = count_tokens(messages)
if current > max_tokens:
    # 压缩旧消息，保留最近N条
```

### 上下文流转（NestJS）
```typescript
async streamWithMemory(
    sessionId: string,
    query: string,
    userId: string
): Observable {
    // 1. 加载历史消息
    const history = await this.getMessages(sessionId, userId, 10);
    
    // 2. 传给Agent（通过sessionId的thread_id）
    // 3. Agent从Checkpointer恢复state + 消息链
    // 4. 流式处理SSE事件
    // 5. 保存新message到DB
}
```

---

## 🚨 当前关键问题

| 问题 | 影响 | 优先级 |
|------|------|--------|
| **后端Agent无认证** | 跨用户会话访问 | 🔴 HIGH |
| **工具参数无验证** | 运行时crash | 🔴 HIGH |
| **Coordinator内存持久化** | 重启丢失、无灾难恢复 | 🟠 MEDIUM |
| **无token计数策略** | 长对话爆炸 | 🟠 MEDIUM |
| **无对话摘要** | 记忆管理缺失 | 🟠 MEDIUM |
| **无链路追踪** | 调试困难、问题诊断难 | 🟡 LOW |
| **无错误重试** | 工具偶发失败无恢复 | 🟡 LOW |
| **无用户学习** | 无跨会话推荐优化 | 🟡 LOW |

---

## 💡 快速优化方案

### 1️⃣ 安全加固（1-2天）
```python
# fastapi认证middleware
from fastapi import HTTPException

async def verify_session_owner(sessionId: str, userId: str) -> bool:
    session_doc = db.sessions.find_one({"_id": ObjectId(sessionId), "userId": userId})
    return session_doc is not None

@app.get("/api/agent/stream")
async def stream_agent(query: str, sessionId: str, userId: str):
    if not await verify_session_owner(sessionId, userId):
        raise HTTPException(status_code=403, detail="Unauthorized")
    # 继续处理...
```

### 2️⃣ 对话压缩（1周）
```python
from langchain_text_splitters import RecursiveCharacterTextSplitter

async def compress_messages(messages, max_tokens=2000):
    """超过token预算时，用LLM摘要旧消息"""
    total = sum(count_tokens(m.content) for m in messages)
    if total <= max_tokens:
        return messages
    
    # 保留最后5条，压缩前面的
    to_compress = messages[:-5]
    prompt = f"总结对话:\n{to_compress}"
    summary = await llm.invoke(prompt)
    
    return [
        SystemMessage(f"[历史摘要] {summary}"),
        *messages[-5:]
    ]
```

### 3️⃣ 动态上下文窗口（3-5天）
```python
import tiktoken

class ContextManager:
    def __init__(self, max_tokens=4000):
        self.max_tokens = max_tokens
        self.enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
    
    def fit_to_budget(self, messages, system_prompt):
        """自适应调整消息数量满足token预算"""
        system_tokens = len(self.enc.encode(system_prompt))
        remaining = self.max_tokens - system_tokens
        
        # 保留最后1条完整，向后扩展
        fitted = [messages[-1]] if messages else []
        for msg in reversed(messages[:-1]):
            msg_tokens = len(self.enc.encode(str(msg.content)))
            if remaining >= msg_tokens:
                fitted.insert(0, msg)
                remaining -= msg_tokens
        return fitted
```

---

## 📈 性能指标

### 当前测试结果（docs/rag-experiments/）
- Success@1：73%（模型推荐）
- Recall@5：83.5%（模型检索）
- 平均延迟：2-5s（SSE流式）

### 优化后目标
- ✅ 对话摘要：减少30%的token消耗
- ✅ 动态窗口：支持200+轮长对话
- ✅ 知识图谱：Success@1 +5-10%
- ✅ 链路追踪：问题诊断时间-40%

---

## 📚 文件导引

| 文件 | 职责 |
|------|------|
| `agents/model_recommend/graph.py` | 模型推荐Agent |
| `agents/model_recommend/tools.py` | 工具定义（Milvus混合检索等） |
| `agents/data_scan/graph.py` | 数据扫描Agent |
| `agents/alignment/graph.py` | 对齐Agent |
| `agents/triangle_coordinator.py` | 会话协调器 |
| `src/chat/chat.service.ts` | NestJS会话管理 + SSE代理 |
| `main.py` | FastAPI 入口 + SSE流式处理 |

---

## 🎯 下一步行动

### 本周
- [ ] 审阅此报告
- [ ] 新建branch `feature/agent-optimization`
- [ ] 实现Priority-1（后端认证）

### 第2-3周
- [ ] 对话摘要系统
- [ ] 动态上下文窗口
- [ ] Coordinator持久化

### 第4周+
- [ ] 知识图谱 + 用户学习
- [ ] 链路追踪 + Jaeger集成
- [ ] Prometheus指标收集

详见 `/memories/session/optimization_roadmap.md`

---

**报告日期**：2026年5月7日  
**审计人**：GitHub Copilot  
**范围**：智能体系统完整架构（前后端 + Agent编排 + 存储）
