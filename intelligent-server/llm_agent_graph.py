"""LangGraph 风格的 Agent Builder。

实现目标：
 - 按 langgraph 概念组织：定义工具（tools）、模型（model）、状态（states）、模型/工具节点、终端逻辑并编译代理。
 - 当系统安装真实 `langgraph` 库时，尝试用其 API 构建；若未安装则返回一个功能等效的异步 runner。

注意：不同版本的 `langgraph` API 可能有差别，下面的实现对真实 API 做了保护性判断并提供了可运行的 fallback。
"""

from typing import Any, Callable, Dict, Optional
import asyncio

from llm_agent_service import LlmAgentService


class LangGraphAgentBuilder:
    def __init__(self, index_service: Any, genai_service: Any, resource_service: Any, tools: Optional[Dict] = None):
        self.index_service = index_service
        self.genai_service = genai_service
        self.resource_service = resource_service
        self.tools = tools or {}
        self.service = LlmAgentService(index_service, genai_service, resource_service,
                                       index_tool_schema=self.tools.get("index"),
                                       model_tool_schema=self.tools.get("model"))

    def build_tool_defs(self) -> Dict[str, Dict]:
        """返回工具定义（供 langgraph 使用或作为 runner 的 schema 传递）。"""
        recommend_index_tool = {
            "name": "recommend_index",
            "description": "Select 5 index names from candidates",
            "args": {"recommendations": "array"},
        }

        recommend_model_tool = {
            "name": "recommend_model",
            "description": "Return md5 and reason for chosen model",
            "args": {"md5": "string", "reason": "string"},
        }

        return {"index": recommend_index_tool, "model": recommend_model_tool}

    def _try_import_langgraph(self):
        try:
            import langgraph as lg  # type: ignore
            return lg
        except Exception:
            return None

    def compile(self) -> Any:
        """尝试构建并编译一个 langgraph 风格的 agent。

        返回：
          - 如果 `langgraph` 可用：返回构建好的 graph/agent（具体类型取决于安装版本）；
          - 否则返回一个异步 `run(prompt)` 函数，表现与 agent 等效。
        """
        lg = self._try_import_langgraph()
        tool_defs = self.build_tool_defs()

        if lg:
            # 以下为基于常见 Graph/Node API 的示意构建，可能需根据你本地 langgraph 版本调整
            try:
                graph = lg.Graph(name="llm_agent_graph")

                # 定义模型（wrap genai 服务）
                model_node = lg.nodes.ModelNode(
                    func=lambda prompt: asyncio.run(self.service.recommend_model(prompt)),
                    name="recommend_model_node",
                )

                # 工具节点（示例）
                tool_index = lg.nodes.ToolNode(func=lambda *args, **kw: None, name="recommend_index_tool")
                tool_model = lg.nodes.ToolNode(func=lambda *args, **kw: None, name="recommend_model_tool")

                # 终端节点: 输出结果
                def terminal_fn(result):
                    print("Agent result:\n", result)
                    return result

                terminal_node = lg.nodes.FunctionNode(func=terminal_fn, name="terminal")

                graph.add_nodes([model_node, tool_index, tool_model, terminal_node])
                graph.add_edge(model_node, terminal_node)

                # 把工具 schema 注入 graph（若 API 有方法）
                if hasattr(graph, "register_tool"):
                    graph.register_tool(tool_defs.get("index"))
                    graph.register_tool(tool_defs.get("model"))

                # 编译/返回 agent（视实现而定）
                if hasattr(graph, "compile"):
                    agent = graph.compile()
                    return agent
                return graph
            except Exception:
                # 如果 langgraph API 与示例不匹配，退回到 fallback runner
                pass

        # fallback: 返回一个直接按步骤执行的异步 runner
        async def run(prompt: str) -> Any:
            # 1. embedding（lang graph 中作为模型节点的一部分）
            _ = await self.genai_service.generate_embedding(prompt)
            # 2. run recommend_model (内部会调用 recommend_index)
            result = await self.service.recommend_model(prompt)
            # 3. 终端逻辑
            print("Agent result:\n", result)
            return result

        return run


def build_graph(index_service: Any, genai_service: Any, resource_service: Any, tools: dict = None):
    """兼容旧接口：直接返回 `compile()` 的结果。"""
    builder = LangGraphAgentBuilder(index_service, genai_service, resource_service, tools=tools)
    return builder.compile()
