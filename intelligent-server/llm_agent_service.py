import asyncio
from typing import Any, Dict, List, Optional


class LlmAgentService:
    """Python 版本的 LLM agent service。

    说明：本实现尽量保持与 TypeScript 代码逻辑一致，但依赖外部的
    `index_service`, `genai_service`, `resource_service` 实例，它们需提供：
      - index_service.find_relevant_index(user_vector)
      - index_service.find_relevant_model(user_vector, model_ids)
      - index_service.get_indicator_by_names(names)
      - genai_service.generate_embedding(text)
      - genai_service.generate_content(contents, tool_schema)
      - resource_service.get_model_details(md5)

    这份文件不强依赖具体 LLM 客户端或 langgraph — 在 `llm_agent_graph.py`
    中会展示如何把它接入 langgraph（若安装）。
    """

    def __init__(
        self,
        index_service: Any,
        genai_service: Any,
        resource_service: Any,
        index_tool_schema: Optional[Dict] = None,
        model_tool_schema: Optional[Dict] = None,
    ):
        self.index_service = index_service
        self.genai_service = genai_service
        self.resource_service = resource_service
        self.index_tool_schema = index_tool_schema
        self.model_tool_schema = model_tool_schema

    async def recommend_index(self, prompt: str, user_query_vector: List[float]) -> Optional[Dict]:
        """使用 LLM（结构化输出 + tool-calling）推荐 5 个指标。

        返回格式示例：{"recommendations": [{"name": "xxx", "reason": "..."}, ...]}
        """
        relevant_index = await self.index_service.find_relevant_index(user_query_vector)

        contents = [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            "You are a professional expert in recommendation of geographical index.\n\n"
                            "IMPORTANT RULES (MUST FOLLOW):\n"
                            "    1. You can ONLY choose index names that appear exactly in the Candidate Index Library.\n"
                            "    2. The \"name\" field in your response must be name_en from the candidates.\n"
                            "    3. Don't translate, summarize, rename, or invent new index names.\n"
                            "    4. If no suitable index exists, do not use the tool.\n"
                            "    5. If and only if you can confidently select 5 different index names, use the \"recommend_index\" tool. Otherwise, do not use any tool.\n\n"
                            "Candidate Index Library:\n"
                        ) + str(relevant_index)
                    }
                ],
            },
            {"role": "user", "parts": [{"text": prompt}]},
        ]

        try:
            response = await self.genai_service.generate_content(contents, self.index_tool_schema)

            function_calls = response.get("function_calls") if isinstance(response, dict) else None
            if function_calls and len(function_calls) > 0:
                fc = function_calls[0]
                if fc.get("name") == "recommend_index":
                    args = fc.get("args", {})
                    recommendations = args.get("recommendations")
                    if isinstance(recommendations, list) and len(recommendations) > 0:
                        return {
                            "recommendations": [
                                {"name": it.get("name"), "reason": it.get("reason")} for it in recommendations
                            ]
                        }
            return None
        except Exception as e:
            print("推荐指标信息错误：", e)
            return None

    async def recommend_model(self, prompt: str) -> Optional[Dict]:
        """综合指标与模型候选，使用 LLM 推荐最终模型，返回模型详情与工作流描述。"""
        # 1. embedding
        user_query_vector = await self.genai_service.generate_embedding(prompt)

        # 2. 推荐指标
        index_recommendation = await self.recommend_index(prompt, user_query_vector)
        if not index_recommendation or not index_recommendation.get("recommendations"):
            print("未获取到推荐指标信息！")
            return None

        index_names = [r["name"] for r in index_recommendation["recommendations"]]
        indicators = await self.index_service.get_indicator_by_names(index_names)

        model_id_set = set()
        for ind in indicators:
            for m in ind.get("models", []) if ind else []:
                mid = m.get("model_id")
                if mid:
                    model_id_set.add(mid)

        model_ids = list(model_id_set)
        if not model_ids:
            return None

        # 3. 向量搜索模型候选（取 top5）
        relevant_models = await self.index_service.find_relevant_model(user_query_vector, model_ids)

        # 4. 获取模型详情
        fetches = [self.resource_service.get_model_details(r.get("modelMd5") or r.get("md5")) for r in relevant_models]
        model_details_results = await asyncio.gather(*fetches)

        # 5. 精简候选
        simple_model_list = []
        for mdl in model_details_results:
            if not mdl:
                continue
            simple_model_list.append(
                {
                    "name": mdl.get("name"),
                    "md5": mdl.get("md5"),
                    "description": mdl.get("description"),
                    "mdl": mdl.get("mdl"),
                }
            )

        contents = [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            "You are a professional expert in recommendation of geographical model.\n\n"
                            "IMPORTANT RULES (MUST FOLLOW):\n"
                            "    1. You can only choose model md5 that appear exactly in the Candidate Model Library.\n"
                            "    2. The \"md5\" field in your response must be md5 from the candidates.\n"
                            "    3. Don't translate, summarize, rename, or invent new model md5.\n"
                            "    4. If no suitable model exists, do not use the tool.\n"
                            "    5. You need to compare their descriptions and mdl and use the \"recommend_model\" tool to select the most relevant model.\n\n"
                            "Candidate Models Library:\n"
                        ) + str(simple_model_list)
                    }
                ],
            },
            {"role": "user", "parts": [{"text": prompt}]},
        ]

        try:
            response = await self.genai_service.generate_content(contents, self.model_tool_schema)
            function_calls = response.get("function_calls") if isinstance(response, dict) else None
            if function_calls and len(function_calls) > 0:
                fc = function_calls[0]
                if fc.get("name") == "recommend_model":
                    args = fc.get("args", {})
                    recommend_md5 = args.get("md5")
                    recommend_reason = args.get("reason")

                    final_model = await self.resource_service.get_model_details(recommend_md5)
                    if final_model and final_model.get("data") and final_model["data"].get("input"):
                        workflow_steps = []
                        for state in final_model["data"]["input"]:
                            events_out = []
                            for event in state.get("events", []):
                                event_data = event.get("eventData", {})
                                inputs = []
                                if event_data.get("eventDataType") == "internal" and event_data.get("nodeList"):
                                    for node in event_data.get("nodeList", []):
                                        inputs.append(
                                            {
                                                "name": node.get("name"),
                                                "key": f"{state.get('stateName')}_{event.get('eventName')}_{node.get('name')}",
                                                "type": node.get("dataType"),
                                                "description": node.get("description"),
                                            }
                                        )
                                if event_data.get("eventDataType") == "external":
                                    inputs.append(
                                        {
                                            "name": event_data.get("eventDataName") or event.get("eventName"),
                                            "key": f"{state.get('stateName')}_{event.get('eventName')}_{event_data.get('eventDataName')}",
                                            "type": "FILE",
                                            "description": event_data.get("exentDataDesc"),
                                        }
                                    )
                                events_out.append(
                                    {
                                        "eventName": event.get("eventName"),
                                        "eventDescription": event.get("eventDescription"),
                                        "inputs": inputs,
                                    }
                                )
                            workflow_steps.append(
                                {
                                    "stateName": state.get("stateName"),
                                    "stateDescription": state.get("stateDescription"),
                                    "events": events_out,
                                }
                            )

                        return {
                            "name": final_model.get("name"),
                            "description": final_model.get("description"),
                            "reason": recommend_reason,
                            "workflow": workflow_steps,
                        }
            return None
        except Exception as e:
            print("推荐模型信息错误：", e)
            return None
