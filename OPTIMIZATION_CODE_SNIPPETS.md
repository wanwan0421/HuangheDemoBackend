# 关键优化实现代码示例

## 🔐 Priority-1: 后端Agent认证修复

### 问题现状
```python
# ❌ 当前 FastAPI 中的代码（不安全）
@app.get("/api/agent/stream")
async def stream_agent(query: str, sessionId: Optional[str] = None):
    print("Received stream query:", query, "sessionId:", sessionId)
    # 直接用 sessionId，无任何owner检查
    # → 任何用户都可以通过猜测sessionId访问他人会话！
    
    thread_id = sessionId or str(uuid.uuid4())
    final_state = agent.astream(
        config={"configurable": {"thread_id": thread_id}}
    )
```

### 修复方案

#### 步骤1: NestJS 侧修改
```typescript
// src/chat/chat.service.ts - 修改getSystemStream()

getSystemStream(query: string, sessionId?: string, userId?: string): Observable {
    const headers = {};
    
    // 关键：将userId添加到header中传给Python
    if (userId) {
        headers['X-User-ID'] = userId;
    }
    
    return new Observable((observer) => {
        this.httpService.axiosRef({
            url: `${process.env.agentUrl}/stream?query=${encodeURIComponent(query)}${sessionId ? `&sessionId=${encodeURIComponent(sessionId)}` : ''}`,
            method: 'GET',
            headers,  // ← 传userId
            responseType: 'stream',
        }).then((response) => {
            // 原SSE解析逻辑...
        })
    });
}

// src/chat/chat.service.ts - 修改streamWithMemory()
streamWithMemory(sessionId: string, query: string, userId: string): Observable {
    return new Observable((observer) => {
        // 先验证session归属
        this.getOwnedSession(sessionId, userId).then(() => {
            // 调用Agent时传userId
            return this.getSystemStream(query, sessionId, userId);
        }).subscribe(observer);
    });
}
```

#### 步骤2: FastAPI 侧修改
```python
# intelligent-server/main.py

from fastapi import Depends, HTTPException, status, Header
from fastapi.security import HTTPBearer
from typing import Optional
from pymongo import MongoClient
from bson import ObjectId

# 初始化认证
security = HTTPBearer()
mongo_client = MongoClient("mongodb://localhost:27017/")
db = mongo_client["huanghe-demo"]

async def verify_session_ownership(
    sessionId: str,
    userId: Optional[str] = Header(None, alias="X-User-ID"),
) -> tuple[str, str]:
    """验证sessionId的所有权"""
    
    if not sessionId or not userId:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing sessionId or userId"
        )
    
    # 查询MongoDB验证
    session_doc = db.sessions.find_one({
        "_id": ObjectId(sessionId),
        "userId": userId,
    })
    
    if not session_doc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized session access"
        )
    
    return sessionId, userId

@app.get("/api/agent/stream")
async def stream_agent(
    query: str,
    sessionId: Optional[str] = None,
    X_User_ID: tuple = Depends(verify_session_ownership),
):
    """
    修复后的stream_agent
    - 验证sessionId的owner是userId
    - 拒绝跨用户访问
    """
    verified_sessionId, verified_userId = X_User_ID
    
    print(f"Stream query for user {verified_userId}: {query} (sessionId: {verified_sessionId})")
    
    # 后续逻辑完全相同
    thread_id = verified_sessionId
    # ... agent.astream(...)
```

#### 步骤3: 单测覆盖
```python
# test_agent_auth.py

import pytest
from fastapi.testclient import TestClient
from main import app
from unittest.mock import patch, MagicMock

client = TestClient(app)

def test_stream_agent_missing_user_id():
    """缺少userId时应拒绝"""
    response = client.get(
        "/api/agent/stream",
        params={"query": "test", "sessionId": "session_123"}
    )
    assert response.status_code == 401

def test_stream_agent_wrong_user_id():
    """userId不匹配时应拒绝"""
    with patch("main.db.sessions.find_one") as mock_find:
        mock_find.return_value = None  # 模拟找不到
        
        response = client.get(
            "/api/agent/stream",
            params={"query": "test", "sessionId": "session_123"},
            headers={"X-User-ID": "wrong_user_id"}
        )
        assert response.status_code == 403

def test_stream_agent_valid_access():
    """userId匹配时应允许"""
    with patch("main.db.sessions.find_one") as mock_find:
        mock_find.return_value = {
            "_id": "session_123",
            "userId": "user_123"
        }
        with patch("main.agent.astream") as mock_astream:
            mock_astream.return_value = []
            
            response = client.get(
                "/api/agent/stream",
                params={"query": "test", "sessionId": "session_123"},
                headers={"X-User-ID": "user_123"}
            )
            assert response.status_code == 200
```

---

## 📝 Priority-2: 对话摘要系统

### 核心实现
```python
# intelligent-server/agents/memory.py - 新建

from datetime import datetime
from typing import List, Dict, Any, Optional
from langchain.messages import AnyMessage, SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from pymongo import MongoClient
import tiktoken
import json

class ConversationMemory:
    """
    分层对话记忆系统
    - 消息链：完整保留（供链路追踪）
    - 摘要：定期压缩长消息
    - 检查点：关键节点快照
    """
    
    def __init__(self, sessionId: str):
        self.sessionId = sessionId
        self.client = MongoClient("mongodb://localhost:27017/")
        self.db = self.client["huanghe-demo"]
        self.collection = self.db["conversation_memory"]
        
        self.enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
        self.compression_model = ChatOpenAI(
            model="gpt-3.5-turbo",
            temperature=0.3,
        )
    
    def count_tokens(self, content: str) -> int:
        """计算文本的token数"""
        if isinstance(content, str):
            return len(self.enc.encode(content))
        return len(self.enc.encode(str(content)))
    
    async def compress_messages(
        self,
        messages: List[AnyMessage],
        max_tokens: int = 2000,
    ) -> List[AnyMessage]:
        """
        如果消息链总token > max_tokens，压缩为摘要
        
        策略：
        1. 计算总token
        2. 如果超预算，保留最后N条（recent_window），压缩前面的
        3. 用LLM生成摘要替代压缩消息
        4. 保存原消息到archive，便于后续恢复
        """
        
        # 计算总token
        total_tokens = sum(
            self.count_tokens(getattr(m, "content", ""))
            for m in messages
        )
        
        if total_tokens <= max_tokens:
            return messages  # 不超预算，原样返回
        
        # 确定要压缩的范围
        recent_window = 5  # 保留最后5条消息
        to_compress = messages[:-recent_window]
        to_keep = messages[-recent_window:]
        
        # 生成摘要
        compress_content = "\n".join([
            f"[{type(m).__name__}] {getattr(m, 'content', '')[:200]}"
            for m in to_compress
        ])
        
        summary_prompt = f"""
        以下是对话历史的前面部分。请用2-3句话总结关键信息（用户目标、已推荐模型、主要决策）：
        
        {compress_content}
        
        摘要："""
        
        summary_response = await self.compression_model.apredict(summary_prompt)
        
        # 用SystemMessage替代
        compressed_messages = [
            SystemMessage(content=f"[对话摘要] {summary_response}"),
            *to_keep,
        ]
        
        # 保存原消息到archive供恢复
        self._save_compressed_archive(to_compress, summary_response)
        
        return compressed_messages
    
    def _save_compressed_archive(
        self,
        original_messages: List[AnyMessage],
        summary: str,
    ):
        """保存压缩的消息到数据库，供调试和恢复"""
        self.collection.insert_one({
            "sessionId": self.sessionId,
            "timestamp": datetime.now(),
            "type": "compression",
            "original_count": len(original_messages),
            "summary": summary,
            "archived_messages": [
                {
                    "role": type(m).__name__,
                    "content": getattr(m, "content", "")[:500],  # 前500字符
                }
                for m in original_messages
            ],
        })
    
    async def save_checkpoint(
        self,
        node_name: str,
        state: Dict[str, Any],
        metadata: Dict = None,
    ):
        """
        保存关键节点的快照
        - 用于链路追踪
        - 用于故障恢复
        - 用于性能分析
        """
        self.collection.insert_one({
            "sessionId": self.sessionId,
            "timestamp": datetime.now(),
            "type": "checkpoint",
            "node_name": node_name,
            "task_spec": state.get("Task_spec"),
            "recommended_model": state.get("recommended_model", {}).get("name"),
            "tool_results": list(state.get("tool_results", {}).keys()),
            "message_count": len(state.get("messages", [])),
            "metadata": metadata or {},
        })
    
    async def retrieve_similar_context(
        self,
        query: str,
        limit: int = 3,
    ) -> List[Dict]:
        """
        检索历史相似的对话
        用于优化推荐（如果用户问过类似问题）
        """
        # 简单的关键词匹配（生产环境可用embedding）
        keywords = set(query.lower().split())
        
        similar = []
        for doc in self.collection.find(
            {"sessionId": self.sessionId, "type": "checkpoint"},
            sort=[("timestamp", -1)],
            limit=100,
        ):
            checkpoint_text = f"{doc.get('node_name')} {doc.get('metadata', {})}"
            match_count = len(keywords & set(checkpoint_text.lower().split()))
            
            if match_count > 0:
                similar.append({
                    "score": match_count,
                    "checkpoint": doc,
                })
        
        return sorted(similar, key=lambda x: x["score"], reverse=True)[:limit]

# 集成点：在recommend_model_node中使用
async def recommend_model_node(state: ModelState) -> Dict[str, Any]:
    """修改后的节点"""
    
    # 初始化记忆管理
    memory = ConversationMemory(state.get("session_id"))
    
    # 压缩消息链
    compressed_messages = await memory.compress_messages(
        state["messages"],
        max_tokens=4000
    )
    
    # 用压缩后的消息调用LLM
    system = SystemMessage(content="...")
    response = tools.model_with_tools.invoke([system] + compressed_messages)
    
    # 保存检查点
    await memory.save_checkpoint(
        node_name="recommend_model",
        state=state,
        metadata={"response_type": type(response).__name__}
    )
    
    return {"messages": [response]}
```

---

## 🎯 Priority-3: 动态上下文窗口

### 核心实现
```python
# intelligent-server/agents/context_manager.py - 新建

from typing import List, Dict, Any
from langchain.messages import AnyMessage, SystemMessage, HumanMessage
import tiktoken

class ContextManager:
    """
    动态上下文窗口管理
    - 根据token预算自适应调整消息数量
    - 优先保留关键消息（最后用户输入、工具结果）
    - 防止长对话爆炸
    """
    
    def __init__(self, max_tokens: int = 4000, model: str = "gpt-3.5-turbo"):
        self.max_tokens = max_tokens
        self.enc = tiktoken.encoding_for_model(model)
    
    def count_tokens(self, content: Any) -> int:
        """计算任意内容的token数"""
        if isinstance(content, str):
            return len(self.enc.encode(content))
        else:
            return len(self.enc.encode(str(content)))
    
    def fit_context_window(
        self,
        messages: List[AnyMessage],
        system_prompt: str,
        task_spec: Dict = None,
        tool_results: Dict = None,
    ) -> List[AnyMessage]:
        """
        根据token预算，动态调整消息集合
        
        优先级：
        1. System prompt + Task spec + Tool results（必保，占 ~30%预算）
        2. 最后一条user message（必保）
        3. 最近的3-5条AI/Tool交互（优先保）
        4. 历史消息（按时间倒序追加，直到预算用尽）
        """
        
        # 计算固定部分占用
        system_content = f"""
System Prompt: {system_prompt}

Task Spec: {task_spec}

Recent Tool Results: {tool_results}
""".strip()
        
        reserved_tokens = self.count_tokens(system_content)
        available_for_messages = self.max_tokens - reserved_tokens
        
        if available_for_messages < 500:  # 至少留500token给消息
            print(f"Warning: Reserved tokens ({reserved_tokens}) exceeds budget. Increase max_tokens.")
        
        # 构建返回消息列表
        fitted_messages = []
        tokens_used = 0
        
        # 步骤1：保留最后一条user message
        if messages and isinstance(messages[-1], HumanMessage):
            last_user_msg = messages[-1]
            msg_tokens = self.count_tokens(last_user_msg.content)
            if msg_tokens <= available_for_messages * 0.7:  # 不能超过70%
                fitted_messages.append(last_user_msg)
                tokens_used += msg_tokens
                remaining_messages = messages[:-1]
            else:
                # 最后的user message太长，截断
                print(f"Last user message too long ({msg_tokens} tokens). Truncating.")
                remaining_messages = messages
        else:
            remaining_messages = messages
        
        # 步骤2：从后向前追加其他消息
        for i in range(len(remaining_messages) - 1, -1, -1):
            msg = remaining_messages[i]
            msg_tokens = self.count_tokens(msg.content)
            
            # 防止单条消息过大
            if msg_tokens > (available_for_messages - tokens_used) * 0.4:
                continue
            
            # 还有预算就加入
            if tokens_used + msg_tokens <= available_for_messages:
                fitted_messages.insert(0, msg)
                tokens_used += msg_tokens
            else:
                break
        
        # 调试信息
        print(f"""
Context Window Fit Report:
- Total budget: {self.max_tokens} tokens
- Reserved (system/spec/tools): {reserved_tokens} tokens
- Used for messages: {tokens_used} tokens
- Remaining: {available_for_messages - tokens_used} tokens
- Input messages: {len(messages)} → Fitted: {len(fitted_messages)}
""")
        
        return fitted_messages
    
    def estimate_response_tokens(self, user_query: str) -> int:
        """估计模型回复的token数（用于预算规划）"""
        # 简单的启发式方法
        query_tokens = self.count_tokens(user_query)
        # 假设回复长度是query的2-3倍
        estimated_response = query_tokens * 2.5
        return int(estimated_response)

# 集成点：modify recommend_model_node
def recommend_model_node(state: ModelState) -> Dict[str, Any]:
    """修改后的节点"""
    
    context_mgr = ContextManager(
        max_tokens=4000,  # 根据模型调整
        model="gpt-3.5-turbo"
    )
    
    # 动态调整消息窗口
    fitted_messages = context_mgr.fit_context_window(
        messages=state["messages"],
        system_prompt="...",
        task_spec=state.get("Task_spec"),
        tool_results=state.get("tool_results"),
    )
    
    # 估计回复token，用于预算
    estimated_response = context_mgr.estimate_response_tokens(
        get_latest_user_query(state["messages"])
    )
    
    # 调用LLM
    system = SystemMessage(content="...")
    response = tools.model_with_tools.invoke([system] + fitted_messages)
    
    return {"messages": [response]}
```

---

## 🛠️ Priority-4: Coordinator持久化

### 核心修改
```python
# agents/coordinator_db.py - 修改为持久化版本

from datetime import datetime, timedelta
from typing import Dict, Optional, List
from pymongo import MongoClient
from enum import Enum

class TriangleMatchingSession:
    """会话对象（同上）"""
    
    @staticmethod
    def from_dict(doc: Dict):
        """从MongoDB文档反序列化"""
        session = TriangleMatchingSession(doc["session_id"])
        session.task_spec = doc.get("task_spec")
        session.model_contract = doc.get("model_contract")
        session.data_profiles = doc.get("data_profiles", [])
        session.alignment_result = doc.get("alignment_result")
        session.status = MatchingStatus(doc.get("status", "pending"))
        session.created_at = doc.get("created_at", datetime.now().isoformat())
        session.completed_at = doc.get("completed_at")
        return session
    
    def to_dict(self) -> Dict:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "status": self.status.value,
            "task_spec": self.task_spec,
            "model_contract": self.model_contract,
            "data_profiles": self.data_profiles,
            "alignment_result": self.alignment_result,
        }

class PersistentTriangleMatchingCoordinator:
    """持久化协调器（带DB备份）"""
    
    def __init__(self, mongodb_uri: str = "mongodb://localhost:27017/"):
        self.client = MongoClient(mongodb_uri)
        self.db = self.client["huanghe-demo"]
        self.sessions_collection = self.db["coordinator_sessions"]
        
        # 内存缓存（提高频繁访问的速度）
        self.memory_sessions: Dict[str, TriangleMatchingSession] = {}
        
        # 创建索引加速查询
        self.sessions_collection.create_index([("session_id", 1)])
        self.sessions_collection.create_index([("created_at", 1)])
        
        print("[Coordinator] Initialized with persistent storage")
    
    def _get_or_create_session(self, session_id: str) -> TriangleMatchingSession:
        """从内存缓存或DB恢复会话"""
        
        # 步骤1：检查内存缓存
        if session_id in self.memory_sessions:
            return self.memory_sessions[session_id]
        
        # 步骤2：从DB加载
        doc = self.sessions_collection.find_one({"session_id": session_id})
        if doc:
            session = TriangleMatchingSession.from_dict(doc)
            self.memory_sessions[session_id] = session
            print(f"[Coordinator] Restored session {session_id} from DB")
            return session
        
        # 步骤3：创建新会话
        session = TriangleMatchingSession(session_id)
        self.memory_sessions[session_id] = session
        print(f"[Coordinator] Created new session {session_id}")
        return session
    
    def update_task_and_model_from_stream(
        self,
        session_id: str,
        task_spec: Optional[Dict] = None,
        model_contract: Optional[Dict] = None,
    ) -> TriangleMatchingSession:
        """
        更新会话，并同步到DB
        """
        session = self._get_or_create_session(session_id)
        
        if task_spec:
            session.task_spec = task_spec
        if model_contract:
            session.model_contract = model_contract
        
        # 更新状态
        if session.task_spec and session.model_contract:
            session.status = MatchingStatus.PENDING
        else:
            session.status = MatchingStatus.PROCESSING
        
        # 同步到DB（关键！）
        self.sessions_collection.update_one(
            {"session_id": session_id},
            {"$set": {
                **session.to_dict(),
                "last_updated": datetime.now(),
            }},
            upsert=True,  # 不存在则插入
        )
        
        print(f"[Coordinator] Updated session {session_id} → {session.status.value}")
        return session
    
    def add_data_profile_from_stream(
        self,
        session_id: str,
        file_path: str,
        profile: Dict,
    ) -> TriangleMatchingSession:
        """追加数据画像（同原逻辑，但要持久化）"""
        session = self._get_or_create_session(session_id)
        
        if not profile:
            return session
        
        payload = {
            "file_id": f"stream_{uuid.uuid4().hex[:12]}",
            "file_path": file_path,
            "profile": profile,
            "timestamp": datetime.now().isoformat(),
            "status": "active",
        }
        
        # 按file_path去重替换
        replaced = False
        for index, item in enumerate(session.data_profiles):
            if item.get("file_path") == file_path:
                session.data_profiles[index] = payload
                replaced = True
                break
        
        if not replaced:
            session.data_profiles.append(payload)
        
        # 立即同步到DB
        self.sessions_collection.update_one(
            {"session_id": session_id},
            {"$set": {
                "data_profiles": session.data_profiles,
                "last_updated": datetime.now(),
            }},
            upsert=True,
        )
        
        print(f"[Coordinator] Added data profile for {file_path}")
        return session
    
    async def cleanup_expired_sessions(
        self,
        max_age_hours: int = 24,
    ):
        """
        定期清理过期会话
        应该作为后台任务定期运行
        """
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
        
        # 从DB删除
        result = self.sessions_collection.delete_many({
            "status": {"$ne": "matched"},  # 非完成状态
            "created_at": {"$lt": cutoff_time}
        })
        
        if result.deleted_count > 0:
            print(f"[Coordinator] Cleaned up {result.deleted_count} expired sessions")
        
        # 从内存缓存删除
        expired_ids = [
            sid for sid, session in self.memory_sessions.items()
            if datetime.fromisoformat(session.created_at) < cutoff_time
            and session.status != MatchingStatus.MATCHED
        ]
        
        for sid in expired_ids:
            del self.memory_sessions[sid]
        
        print(f"[Coordinator] Cleaned {len(expired_ids)} sessions from memory cache")
    
    def get_session(self, session_id: str) -> Optional[TriangleMatchingSession]:
        """获取会话（优先返回内存缓存或从DB恢复）"""
        return self._get_or_create_session(session_id)

# 后台任务：定期清理（可用APScheduler）
from apscheduler.schedulers.background import BackgroundScheduler

def setup_coordinator_cleanup():
    """启动后台清理任务"""
    scheduler = BackgroundScheduler()
    
    async def cleanup_task():
        coordinator = get_coordinator()
        await coordinator.cleanup_expired_sessions(max_age_hours=24)
    
    scheduler.add_job(cleanup_task, "cron", hour=2, minute=0)  # 每天凌晨2点
    scheduler.start()
    print("[Coordinator] Cleanup scheduler started")
```

---

## 📊 集成与测试检查清单

```markdown
### 代码集成
- [ ] 后端认证（main.py + chat.service.ts）
  - [ ] NestJS 添加userId到header
  - [ ] FastAPI middleware验证
  - [ ] 单测覆盖
  
- [ ] 对话摘要（ConversationMemory）
  - [ ] 集成到recommend_model_node
  - [ ] 配置max_tokens参数
  - [ ] 单测：验证压缩率

- [ ] 动态窗口（ContextManager）
  - [ ] 集成到所有LLM节点
  - [ ] token计数验证
  - [ ] 长对话E2E测试

- [ ] Coordinator持久化
  - [ ] 更新get_coordinator()工厂函数
  - [ ] MongoDB索引创建
  - [ ] 后台清理任务

### 测试
- [ ] 单元测试：各模块独立功能
- [ ] 集成测试：完整流程（需求→模型→对齐）
- [ ] 长对话测试：50+轮对话，验证token管理
- [ ] 多并发测试：10+用户并发访问
- [ ] 故障恢复测试：进程重启后会话恢复

### 部署
- [ ] 代码审查
- [ ] 灰度发布（10% → 50% → 100%）
- [ ] 性能监控（对比优化前后）
- [ ] 用户反馈收集
```

---

**总耗时估计**：8-10周  
**分工建议**：  
- 后端安全（1人，1-2天）  
- 记忆系统（1人，2周）  
- 上下文管理（1人，1周）  
- 持久化改造（1人，1周）  
- 测试 + 部署（1人，1周）
