# LLM Agent (Python 版)

包含：

- `llm_agent_service.py`：与原 TypeScript `LlmAgentService` 等价的 Python 实现。
- `llm_agent_graph.py`：将服务集成到 `langgraph` 的示例（若未安装 langgraph，则导出一个简单的 runner）。
- `requirements_langgraph.txt`：可选依赖说明。

快速上手：

1. 安装依赖（可选）：

```bash
python -m pip install -r intelligent-server/requirements_langgraph.txt
```

2. 在你的程序中初始化并使用：

```python
from intelligent_server.llm_agent_service import LlmAgentService
# 假设已实现 index_service / genai_service / resource_service
service = LlmAgentService(index_service, genai_service, resource_service, index_tool_schema=..., model_tool_schema=...)
# 在 asyncio 环境中调用
result = await service.recommend_model("请推荐适合的地理模型。")
print(result)
```

3. 若使用 `langgraph`，请参考 `llm_agent_graph.py` 中的 `build_graph`。

注意：本仓库的 Python 服务实现为适配层，仍依赖你已有的索引、资源和 LLM 客户端实现。

扩展为 langgraph Agent：

- `llm_agent_graph.build_graph(...)` 返回一个已编译的 agent（若本地安装 `langgraph` 且版本匹配），或返回一个异步 `run(prompt)` 函数作为回退。
- 若你希望将工具/模型/状态严格按照官方文档配置，请将 `tools` 参数传入 `build_graph`，或直接修改 `LangGraphAgentBuilder.build_tool_defs()` 以适配你团队的 schema。

示例：

```python
from intelligent_server.llm_agent_graph import build_graph

# 初始化 index_service / genai_service / resource_service
agent_or_runner = build_graph(index_service, genai_service, resource_service)

if callable(agent_or_runner):
	# runner 回退情况
	import asyncio
	asyncio.run(agent_or_runner("请推荐适合的地理模型。"))
else:
	# 如果返回 langgraph agent，按照本地 langgraph 文档运行
	agent = agent_or_runner
	# agent.run(...) 或 agent.execute(...) 取决于具体版本
```
