from typing import List, Dict, Any, Optional
from .store import Store
import tiktoken
from langchain.messages import HumanMessage, AnyMessage

class ContextManager:
    def __init__(self, max_tokens: int = 4000, model: str = "gpt-3.5-turbo"):
        self.max_tokens = max_tokens
        try:
            self.enc = tiktoken.encoding_for_model(model)
        except Exception:
            # fallback
            self.enc = None
        self.store = Store()

    def _count_tokens(self, text: str) -> int:
        if not text:
            return 0
        if self.enc:
            return len(self.enc.encode(text))
        return len(text.split())

    def _extract_message_text(self, message: AnyMessage) -> str:
        content = getattr(message, "content", "")
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(part.get("text", ""))
                elif isinstance(part, str):
                    parts.append(part)
            return "".join(parts)
        return str(content) if content is not None else ""

    def _truncate_text(self, text: str, max_tokens: int) -> str:
        if max_tokens <= 0 or not text:
            return ""
        if not self.enc:
            return " ".join(text.split()[:max_tokens])
        tokens = self.enc.encode(text)
        if len(tokens) <= max_tokens:
            return text
        return self.enc.decode(tokens[:max_tokens])

    def fit_context_window(
        self,
        messages: List[AnyMessage],
        system_prompt: str,
        context_messages: Optional[List[AnyMessage]] = None,
        task_spec: Optional[Dict[str, Any]] = None,
        tool_results: Optional[Dict[str, Any]] = None,
        min_message_tokens: int = 500,
    ) -> List[AnyMessage]:
        """
        根据 token 预算动态裁剪历史消息。
        优先级：System/Context/Task/Tools 保留，最后一条用户消息保留，其次保留最近历史消息。
        """
        context_messages = context_messages or []
        reserved_text = "\n\n".join(
            [
                system_prompt or "",
                str(task_spec or ""),
                str(tool_results or ""),
                "\n".join(self._extract_message_text(m) for m in context_messages),
            ]
        )
        reserved_tokens = self._count_tokens(reserved_text)
        available_tokens = max(self.max_tokens - reserved_tokens, 0)
        if available_tokens < min_message_tokens:
            available_tokens = max(available_tokens, 0)

        if not messages or available_tokens == 0:
            return []

        selected = []

        # 优先保留最后一条用户消息
        last_user_idx = None
        for i in range(len(messages) - 1, -1, -1):
            if isinstance(messages[i], HumanMessage):
                last_user_idx = i
                break

        if last_user_idx is not None:
            last_user_msg = messages[last_user_idx]
            msg_text = self._extract_message_text(last_user_msg)
            msg_tokens = self._count_tokens(msg_text)
            if available_tokens > 0 and msg_tokens > int(available_tokens * 0.7):
                msg_text = self._truncate_text(msg_text, int(available_tokens * 0.7))
                last_user_msg = HumanMessage(content=msg_text)
                msg_tokens = self._count_tokens(msg_text)
            if msg_tokens <= available_tokens:
                selected.append((last_user_idx, last_user_msg, msg_tokens))
                available_tokens -= msg_tokens

        # 从后往前追加最近消息
        for i in range(len(messages) - 1, -1, -1):
            if i == last_user_idx:
                continue
            msg = messages[i]
            msg_text = self._extract_message_text(msg)
            msg_tokens = self._count_tokens(msg_text)
            if msg_tokens <= 0:
                continue
            if msg_tokens > available_tokens:
                continue
            if available_tokens > 0 and msg_tokens > int(available_tokens * 0.4):
                continue
            selected.append((i, msg, msg_tokens))
            available_tokens -= msg_tokens
            if available_tokens <= 0:
                break

        selected.sort(key=lambda x: x[0])
        return [item[1] for item in selected]

    def _summarize_user_snapshot_from_tasks(self, task_memory: List[Dict[str, Any]]) -> Dict[str, Any]:
        """从最近的 task_memory 中总结 user_snapshot（域、目标、空间、分辨率等模式）"""
        if not task_memory:
            return {}
        
        # 统计最常见的域、目标、空间范围
        domains = {}
        targets = {}
        spatial_scopes = {}
        temporal_scopes = {}
        resolutions = {}
        
        for task in task_memory:
            task_spec = task.get('task_spec', {}) or {}
            
            if task_spec.get('Domain'):
                domains[task_spec['Domain']] = domains.get(task_spec['Domain'], 0) + 1
            if task_spec.get('Target_object'):
                targets[task_spec['Target_object']] = targets.get(task_spec['Target_object'], 0) + 1
            if task_spec.get('Spatial_scope'):
                spatial_scopes[task_spec['Spatial_scope']] = spatial_scopes.get(task_spec['Spatial_scope'], 0) + 1
            if task_spec.get('Temporal_scope'):
                temporal_scopes[task_spec['Temporal_scope']] = temporal_scopes.get(task_spec['Temporal_scope'], 0) + 1
            if task_spec.get('Resolution_requirements'):
                resolutions[task_spec['Resolution_requirements']] = resolutions.get(task_spec['Resolution_requirements'], 0) + 1
        
        # 取频率最高的
        snapshot = {}
        if domains:
            snapshot['preferred_domains'] = sorted(domains.keys(), key=lambda x: domains[x], reverse=True)[:3]
        if targets:
            snapshot['preferred_targets'] = sorted(targets.keys(), key=lambda x: targets[x], reverse=True)[:3]
        if spatial_scopes:
            snapshot['common_spatial_scopes'] = sorted(spatial_scopes.keys(), key=lambda x: spatial_scopes[x], reverse=True)[:3]
        if temporal_scopes:
            snapshot['common_temporal_scopes'] = sorted(temporal_scopes.keys(), key=lambda x: temporal_scopes[x], reverse=True)[:2]
        if resolutions:
            snapshot['common_resolutions'] = sorted(resolutions.keys(), key=lambda x: resolutions[x], reverse=True)[:2]
        
        return snapshot

    def retrieve_relevant_memories(self, user_id: str, query: str, top_k: int = 4) -> Dict[str, Any]:
        """从 Store 中检索用户相关记忆（task / model），并从 task 中总结 user_snapshot"""
        res = {}
        res['task_memory'] = self.store.retrieve_task_memory(user_id, query, limit=top_k)
        res['model_memory'] = self.store.retrieve_model_memory(user_id, query, limit=top_k)
        # 从 task_memory 中动态总结 user_snapshot
        res['user_snapshot'] = self._summarize_user_snapshot_from_tasks(res['task_memory'])
        return res

    def build_context_bundle(self, user_id: Optional[str], session_state: Dict[str, Any], user_query: str) -> List[AnyMessage]:
        """
        构建用户上下文信息并返回为 HumanMessage（用户消息形式）。
        这样允许 LLM 的安全过滤生效（不被当作系统指令）。
        """
        context_parts = []
        
        if user_id:
            mems = self.retrieve_relevant_memories(user_id, user_query, top_k=3)
            user_snapshot = mems.get('user_snapshot') or {}
            task_mem = mems.get('task_memory') or []
            model_mem = mems.get('model_memory') or []
            
            # 第一部分：用户活动快照（从最近的 task 中总结）
            if user_snapshot:
                snapshot_text = "## 你的常见活动模式\n"
                if user_snapshot.get('preferred_domains'):
                    snapshot_text += f"- **主要领域**: {', '.join(user_snapshot['preferred_domains'])}\n"
                if user_snapshot.get('preferred_targets'):
                    snapshot_text += f"- **常见目标**: {', '.join(user_snapshot['preferred_targets'])}\n"
                if user_snapshot.get('common_spatial_scopes'):
                    snapshot_text += f"- **常用区域**: {', '.join(user_snapshot['common_spatial_scopes'])}\n"
                if user_snapshot.get('common_temporal_scopes'):
                    snapshot_text += f"- **常见时间范围**: {', '.join(user_snapshot['common_temporal_scopes'])}\n"
                if user_snapshot.get('common_resolutions'):
                    snapshot_text += f"- **常用分辨率**: {', '.join(user_snapshot['common_resolutions'])}\n"
                context_parts.append(snapshot_text)
            
            # 第二部分：相似的历史任务
            if task_mem:
                task_text = "## 你最近的类似任务\n"
                for i, task in enumerate(task_mem[:3], 1):
                    summary = task.get('summary', 'N/A')
                    if len(summary) > 200:
                        summary = summary[:200] + "..."
                    task_text += f"{i}. {summary}\n"
                context_parts.append(task_text)
            
            # 第三部分：常用模型
            if model_mem:
                model_text = "## 你曾使用过的模型\n"
                for i, model in enumerate(model_mem[:3], 1):
                    model_name = model.get('model_name', 'Unknown')
                    reason = model.get('reason', '自动推荐')
                    model_text += f"{i}. **{model_name}** - {reason}\n"
                context_parts.append(model_text)
        
        # 第四部分：当前任务快照
        task_spec = session_state.get('Task_spec') if session_state else None
        if task_spec and any(task_spec.values()):
            spec_text = "## 当前任务规范\n"
            for key, val in task_spec.items():
                if val:
                    spec_text += f"- **{key}**: {val}\n"
            context_parts.append(spec_text)
        
        if not context_parts:
            context_parts.append("当前无可用的历史记录。这将是你的第一次任务。")
        
        full_context = "\n".join(context_parts)
        
        # 返回为 HumanMessage（允许 LLM 安全过滤）
        return [HumanMessage(content=f"以下是你的历史记录和偏好信息，请参考：\n\n{full_context}")]
