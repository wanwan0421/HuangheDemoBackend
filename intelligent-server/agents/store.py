from typing import List, Dict, Any, Optional
from pymongo import MongoClient, ASCENDING, DESCENDING
from datetime import datetime
import os
import re
import json
import hashlib
from pathlib import Path
from dotenv import load_dotenv
from math import sqrt

try:
    from openai import OpenAI
    from pymilvus import Collection, connections
except Exception:
    OpenAI = None
    Collection = None
    connections = None

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")
MEMORY_COLLECTION = "userMemories"
MEMORY_MILVUS_COLLECTION = os.getenv("MEMORY_MILVUS_COLLECTION", "")
MEMORY_EMBEDDING_MODEL = os.getenv("MEMORY_EMBEDDING_MODEL", os.getenv("EMBEDDING_MODEL", "gemini-embedding-001"))
MEMORY_EMBEDDING_DIM = int(
    os.getenv(
        "MEMORY_EMBEDDING_DIM",
        os.getenv("EMBEDDING_DIM", "1536"),
    )
)
AIHUBMIX_API_KEY = os.getenv("MEMORY_AGENT_API_KEY") or os.getenv("OPENAI_COMPAT_API_KEY") or os.getenv("AIHUBMIX_API_KEY")
AIHUBMIX_BASE_URL = os.getenv("MEMORY_AGENT_BASE_URL") or os.getenv("OPENAI_COMPAT_BASE_URL") or os.getenv("AIHUBMIX_BASE_URL")
MILVUS_HOST = os.getenv("MILVUS_HOST", "localhost")
MILVUS_PORT = int(os.getenv("MILVUS_PORT", "19530"))


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """计算两个向量的余弦相似度"""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sqrt(sum(a * a for a in vec_a))
    norm_b = sqrt(sum(b * b for b in vec_b))
    if norm_a < 1e-9 or norm_b < 1e-9:
        return 0.0
    return dot_product / (norm_a * norm_b)


class Store:
    """基础跨线程/跨会话存储

    提供按 namespace 存取用户级长期记忆接口。支持多层搜索：
    1. 优先尝试 Milvus 向量搜索
    2. 降级到 MongoDB 向量搜索（本地余弦相似度）
    3. 最后回退到关键词匹配
    """

    _shared_milvus_init_attempted = False
    _shared_milvus_available = False
    _shared_memory_vector_collection = None

    def __init__(self, mongo_uri: str = MONGO_URI, db_name: str = MONGO_DB_NAME):
        if not mongo_uri or not db_name:
            raise RuntimeError("MONGO_URI and MONGO_DB_NAME must be configured in intelligent-server/.env")
        self.client = MongoClient(mongo_uri)
        self.db = self.client[db_name]
        self.collection = self._collection(MEMORY_COLLECTION)
        self._embedding_client = None
        self._memory_vector_collection = None
        self._milvus_available = False
        self._milvus_init_attempted = False  # 延迟初始化标志
        self._ensure_indexes()
        # 注意：Milvus 初始化延迟到首次使用时进行，避免阻塞应用启动

    def _collection(self, name: str):
        return self.db[name]

    def _ensure_indexes(self) -> None:
        self.collection.create_index([("userId", ASCENDING), ("namespace", ASCENDING), ("updated_at", DESCENDING)])
        self.collection.create_index([("userId", ASCENDING), ("kind", ASCENDING), ("created_at", DESCENDING)])
        self.collection.create_index(
            [("userId", ASCENDING), ("namespace", ASCENDING), ("memory_key", ASCENDING)],
            sparse=True,
        )
        # MongoDB 向量搜索索引（如果版本支持）
        try:
            indexes = self.collection.list_indexes()
            has_vector_index = any("embedding" in idx.get("name", "") for idx in indexes)
            if not has_vector_index and hasattr(self.collection, "create_search_index"):
                self.collection.create_search_index({
                    "name": "embedding_vector",
                    "definition": {
                        "mappings": {
                            "dynamic": True,
                            "fields": {
                                "embedding": {
                                    "type": "knnVector",
                                    "dimensions": MEMORY_EMBEDDING_DIM,
                                    "similarity": "cosine"
                                }
                            }
                        }
                    }
                })
        except Exception:
            pass  # MongoDB 版本不支持或索引已存在

    def _init_milvus(self) -> None:
        """
        尝试连接 Milvus，失败时降级到 MongoDB 向量搜索
        
        采用延迟初始化 + 重试机制：
        - 延迟初始化：仅在首次需要时连接
        - 重试：连接失败时最多重试 5 次，每次等待 1 秒
        """
        if not (MEMORY_MILVUS_COLLECTION and OpenAI and Collection and connections and AIHUBMIX_API_KEY):
            return
        
        if Store._shared_milvus_init_attempted:
            self._milvus_init_attempted = True
            self._milvus_available = Store._shared_milvus_available
            self._memory_vector_collection = Store._shared_memory_vector_collection
            return  # 已经尝试过初始化

        Store._shared_milvus_init_attempted = True
        self._milvus_init_attempted = True
        
        import time
        import logging
        
        max_retries = 5
        retry_interval = 1  # 秒
        
        for attempt in range(max_retries):
            try:
                logging.info(f"Attempting to connect to Milvus (attempt {attempt + 1}/{max_retries})...")
                connections.connect(alias="memory_store", host=MILVUS_HOST, port=MILVUS_PORT)
                try:
                    from pymilvus import utility
                    if not utility.has_collection(MEMORY_MILVUS_COLLECTION, using="memory_store"):
                        logging.warning(
                            f"Milvus collection '{MEMORY_MILVUS_COLLECTION}' not found; disabling Milvus memory store"
                        )
                        self._milvus_available = False
                        Store._shared_milvus_available = False
                        Store._shared_memory_vector_collection = None
                        return
                except Exception:
                    pass

                self._memory_vector_collection = Collection(MEMORY_MILVUS_COLLECTION, using="memory_store")
                self._memory_vector_collection.load()
                self._milvus_available = True
                Store._shared_milvus_available = True
                Store._shared_memory_vector_collection = self._memory_vector_collection
                logging.info("✓ Milvus connected successfully")
                return
            except Exception as e:
                logging.warning(f"Milvus connection failed (attempt {attempt + 1}/{max_retries}): {str(e)[:100]}")
                if attempt < max_retries - 1:
                    time.sleep(retry_interval)
        
        # 所有重试都失败
        logging.warning("All Milvus connection attempts failed, falling back to MongoDB-only storage")
        self._milvus_available = False
        self._memory_vector_collection = None
        Store._shared_milvus_available = False
        Store._shared_memory_vector_collection = None
    
    def _ensure_milvus_ready(self) -> bool:
        """
        确保 Milvus 已初始化（如果配置了的话）
        这是一个懒加载调用，仅在首次需要向量操作时触发
        """
        if not MEMORY_MILVUS_COLLECTION:
            return False  # 未配置 Milvus
        
        if not self._milvus_init_attempted and not Store._shared_milvus_init_attempted:
            self._init_milvus()
        else:
            self._milvus_init_attempted = True
            self._milvus_available = Store._shared_milvus_available
            self._memory_vector_collection = Store._shared_memory_vector_collection

        return self._milvus_available

    def _normalize_text(self, value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip().lower())

    def _tokenize(self, text: str) -> set[str]:
        normalized = self._normalize_text(text)
        tokens = set(re.findall(r"[a-z0-9_./-]+", normalized))
        chinese_chars = re.findall(r"[\u4e00-\u9fff]", normalized)
        tokens.update(chinese_chars)
        tokens.update("".join(chinese_chars[i:i + 2]) for i in range(max(len(chinese_chars) - 1, 0)))
        return {token for token in tokens if token}

    def _memory_key(self, namespace: str, payload: Dict[str, Any]) -> str:
        if namespace == "task_memory":
            task_spec = payload.get("task_spec") or {}
            key_payload = {
                key: self._normalize_text(task_spec.get(key))
                for key in ["Domain", "Target_object", "Spatial_scope", "Temporal_scope", "Resolution_requirements"]
            }
            if not any(key_payload.values()):
                key_payload["summary"] = self._normalize_text(payload.get("summary"))
        elif namespace == "model_memory":
            key_payload = {
                "model_md5": self._normalize_text(payload.get("model_md5")),
                "success": bool(payload.get("success", True)),
            }
        else:
            key_payload = payload

        raw = json.dumps(key_payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _get_embedding_client(self):
        if self._embedding_client is None and OpenAI:
            self._embedding_client = OpenAI(api_key=AIHUBMIX_API_KEY, base_url=AIHUBMIX_BASE_URL)
        return self._embedding_client

    def _embed_text(self, text: str) -> Optional[List[float]]:
        if not text or not AIHUBMIX_API_KEY:
            return None
        try:
            client = self._get_embedding_client()
            if client is None:
                return None
            return client.embeddings.create(model=MEMORY_EMBEDDING_MODEL, input=text).data[0].embedding
        except Exception:
            return None

    def _memory_text(self, namespace: str, payload: Dict[str, Any]) -> str:
        if namespace == "task_memory":
            task_spec = payload.get("task_spec") or {}
            return " ".join(
                str(part or "")
                for part in [
                    payload.get("summary"),
                    task_spec.get("Domain"),
                    task_spec.get("Target_object"),
                    task_spec.get("Spatial_scope"),
                    task_spec.get("Temporal_scope"),
                    task_spec.get("Resolution_requirements"),
                ]
            ).strip()
        if namespace == "model_memory":
            return " ".join(
                str(part or "")
                for part in [payload.get("model_name"), payload.get("model_md5"), payload.get("reason")]
            ).strip()
        if namespace == "user_snapshot":
            return " ".join(
                str(part or "")
                for part in [
                    payload.get("summary"),
                    " ".join(payload.get("active_domains", []) or []),
                    " ".join(payload.get("recent_targets", []) or []),
                    " ".join(payload.get("spatiotemporal_patterns", []) or []),
                    " ".join(payload.get("model_preferences", []) or []),
                ]
            ).strip()
        return str(payload)

    def _upsert_vector_memory(self, user_id: str, namespace: str, kind: str, memory_key: str, payload: Dict[str, Any]) -> None:
        """写入记忆到向量数据库（优先 Milvus，降级 MongoDB）"""
        text = self._memory_text(namespace, payload)
        vector = self._embed_text(text)
        if vector is None:
            return

        # 尝试写入 Milvus（惰性初始化）
        if self._ensure_milvus_ready():
            try:
                row = {
                    "memory_key": memory_key,
                    "userId": user_id,
                    "namespace": namespace,
                    "kind": kind,
                    "text": text,
                    "payload_json": json.dumps(payload, ensure_ascii=False),
                    "embedding": vector,
                }
                if hasattr(self._memory_vector_collection, "upsert"):
                    self._memory_vector_collection.upsert([row])
                else:
                    self._memory_vector_collection.insert([row])
                return
            except Exception as e:
                import logging
                logging.warning(f"Milvus write failed: {str(e)[:100]}")
                self._milvus_available = False

        # 降级到 MongoDB 向量存储
        try:
            now = datetime.utcnow()
            self.collection.update_one(
                {"userId": user_id, "namespace": namespace, "memory_key": memory_key},
                {
                    "$set": {
                        "userId": user_id,
                        "namespace": namespace,
                        "kind": kind,
                        "memory_key": memory_key,
                        "payload": payload,
                        "embedding": vector,
                        "embedding_text": text,
                        "updated_at": now,
                    },
                    "$setOnInsert": {"created_at": now},
                },
                upsert=True,
            )
        except Exception:
            pass

    def _semantic_search_memory(self, user_id: str, namespace: str, query: str, limit: int) -> List[Dict[str, Any]]:
        """向量语义搜索，支持 Milvus 或 MongoDB"""
        query_vector = self._embed_text(query)
        if query_vector is None:
            return []

        # 尝试 Milvus 搜索
        if self._ensure_milvus_ready():
            try:
                safe_user_id = str(user_id).replace('"', '\\"')
                safe_namespace = str(namespace).replace('"', '\\"')
                results = self._memory_vector_collection.search(
                    data=[query_vector],
                    anns_field="embedding",
                    param={"metric_type": "COSINE", "params": {"ef": 64}},
                    limit=max(limit, 5),
                    expr=f'userId == "{safe_user_id}" && namespace == "{safe_namespace}"',
                    output_fields=["memory_key", "payload_json", "text"],
                )
                hits = []
                first = results[0] if results else []
                for hit in first:
                    memory_key = self._safe_hit_get(hit, "memory_key")
                    payload_json = self._safe_hit_get(hit, "payload_json")
                    payload = {}
                    if payload_json:
                        try:
                            payload = json.loads(payload_json)
                        except Exception:
                            pass
                    if payload:
                        payload.setdefault("userId", user_id)
                        payload.setdefault("namespace", namespace)
                        payload["score"] = float(getattr(hit, "score", 0.5))
                        payload["retrieval"] = "milvus_semantic"
                        hits.append(payload)
                if hits:
                    return hits[:limit]
            except Exception as e:
                import logging
                logging.warning(f"Milvus search failed: {str(e)[:100]}")
                self._milvus_available = False

        # 降级到 MongoDB 本地向量相似度搜索
        try:
            docs = list(
                self.collection.find(
                    {
                        "userId": user_id,
                        "namespace": namespace,
                        "embedding": {"$exists": True},
                    }
                )
                .sort("updated_at", -1)
                .limit(100)
            )

            scored = []
            for doc in docs:
                embedding = doc.get("embedding")
                if isinstance(embedding, list) and len(embedding) > 0:
                    sim = cosine_similarity(query_vector, embedding)
                    if sim > 0.3:  # 相似度阈值
                        scored.append((sim, doc))

            scored.sort(key=lambda x: x[0], reverse=True)
            hits = []
            for score, doc in scored[:limit]:
                payload = doc.get("payload") or {}
                payload.setdefault("userId", user_id)
                payload.setdefault("namespace", namespace)
                payload["score"] = score
                payload["retrieval"] = "mongodb_semantic"
                hits.append(payload)
            return hits
        except Exception:
            return []

    def _safe_hit_get(self, hit: Any, field_name: str) -> Any:
        if isinstance(hit, dict):
            return hit.get(field_name)
        if hasattr(hit, "get"):
            try:
                return hit.get(field_name)
            except Exception:
                pass
        entity = getattr(hit, "entity", None)
        if entity is not None:
            try:
                return entity.get(field_name)
            except Exception:
                pass
        return getattr(hit, field_name, None)

    def _is_meaningful_task_spec(self, task_spec: Dict[str, Any]) -> bool:
        return bool(task_spec and any(self._normalize_text(value) for value in task_spec.values()))

    def _doc_payload_with_meta(self, doc: Dict[str, Any], score: float = 0.0) -> Dict[str, Any]:
        payload = dict(doc.get("payload") or {})
        payload.update(
            {
                "userId": doc.get("userId"),
                "namespace": doc.get("namespace"),
                "score": score,
                "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
                "updated_at": doc.get("updated_at").isoformat() if doc.get("updated_at") else None,
            }
        )
        return payload

    def _upsert_namespaced_doc(self, user_id: str, namespace: str, kind: str, payload: Dict[str, Any]) -> None:
        now = datetime.utcnow()
        self.collection.update_one(
            {"userId": user_id, "namespace": namespace},
            {
                "$set": {
                    "userId": user_id,
                    "namespace": namespace,
                    "kind": kind,
                    "payload": payload,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )

    def _insert_memory(self, user_id: str, namespace: str, kind: str, payload: Dict[str, Any]) -> None:
        now = datetime.utcnow()
        memory_key = self._memory_key(namespace, payload)
        self.collection.update_one(
            {"userId": user_id, "namespace": namespace, "memory_key": memory_key},
            {
                "$set": {
                    "userId": user_id,
                    "namespace": namespace,
                    "kind": kind,
                    "memory_key": memory_key,
                    "payload": payload,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        self._upsert_vector_memory(user_id, namespace, kind, memory_key, payload)

    def _find_latest_by_namespace(self, user_id: str, namespace: str) -> Optional[Dict[str, Any]]:
        return self.collection.find_one({"userId": user_id, "namespace": namespace}, sort=[("updated_at", DESCENDING)])

    # --- task_memory ---

    def add_task_memory(self, user_id: str, task_summary: str, task_spec: Dict[str, Any]):
        if not user_id or not self._is_meaningful_task_spec(task_spec):
            return
        self._insert_memory(
            user_id,
            "task_memory",
            "task_memory",
            {
                "summary": task_summary,
                "task_spec": task_spec,
            },
        )
        self.update_user_snapshot(user_id)

    def retrieve_task_memory(self, user_id: str, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        semantic_results = self._semantic_search_memory(user_id, "task_memory", query, limit)
        if semantic_results:
            return semantic_results

        query_tokens = self._tokenize(query)
        results = []
        for doc in self.collection.find({"userId": user_id, "namespace": "task_memory"}).sort("created_at", -1).limit(200):
            payload = doc.get("payload") or {}
            text = (payload.get("summary") or "") + " " + " ".join(
                str(v) for v in (payload.get("task_spec") or {}).values()
            )
            text_tokens = self._tokenize(text)
            score = len(query_tokens & text_tokens)
            if score > 0:
                results.append({"score": score, "doc": self._doc_payload_with_meta(doc, score)})

        if results:
            results.sort(key=lambda x: (x["score"], x["doc"].get("updated_at") or ""), reverse=True)
            return [r["doc"] for r in results[:limit]]

        recent = self.collection.find({"userId": user_id, "namespace": "task_memory"}).sort("updated_at", -1).limit(limit)
        return [self._doc_payload_with_meta(doc, 0.0) for doc in recent]

    # --- model_memory ---

    def add_model_memory(self, user_id: str, model_md5: str, model_name: str, reason: str = None, success: bool = True):
        if not user_id or not self._normalize_text(model_md5):
            return
        self._insert_memory(
            user_id,
            "model_memory",
            "model_memory",
            {
                "model_md5": model_md5,
                "model_name": model_name,
                "reason": reason,
                "success": bool(success),
            },
        )
        self.update_user_snapshot(user_id)

    def retrieve_model_memory(self, user_id: str, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        semantic_results = self._semantic_search_memory(user_id, "model_memory", query, limit)
        if semantic_results:
            return semantic_results

        query_tokens = self._tokenize(query)
        results = []
        for doc in self.collection.find({"userId": user_id, "namespace": "model_memory"}).sort("created_at", -1).limit(200):
            payload = doc.get("payload") or {}
            text = (payload.get("model_name") or "") + " " + (payload.get("reason") or "")
            score = len(query_tokens & self._tokenize(text))
            if score > 0:
                results.append({"score": score, "doc": self._doc_payload_with_meta(doc, score)})

        if results:
            results.sort(key=lambda x: (x["score"], x["doc"].get("updated_at") or ""), reverse=True)
            return [r["doc"] for r in results[:limit]]

        recent = self.collection.find({"userId": user_id, "namespace": "model_memory"}).sort("updated_at", -1).limit(limit)
        return [self._doc_payload_with_meta(doc, 0.0) for doc in recent]

    def _merge_memory_results(
        self, primary: List[Dict[str, Any]], fallback: List[Dict[str, Any]], limit: int
    ) -> List[Dict[str, Any]]:
        seen = set()
        merged = []
        for item in primary + fallback:
            key = item.get("memory_key") or item.get("model_md5") or item.get("summary") or repr(item)
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= limit:
                break
        return merged

    def update_user_snapshot(self, user_id: str) -> Dict[str, Any]:
        task_docs = list(
            self.collection.find({"userId": user_id, "namespace": "task_memory"})
            .sort("updated_at", -1)
            .limit(50)
        )
        model_docs = list(
            self.collection.find({"userId": user_id, "namespace": "model_memory"})
            .sort("updated_at", -1)
            .limit(30)
        )

        def top_values(values: List[str], limit: int = 5) -> List[str]:
            counts: Dict[str, float] = {}
            for index, value in enumerate(values):
                normalized = self._normalize_text(value)
                if not normalized:
                    continue
                counts[value] = counts.get(value, 0.0) + 1.0 / (1 + index * 0.15)
            return [item[0] for item in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]]

        task_payloads = [doc.get("payload") or {} for doc in task_docs]
        model_payloads = [doc.get("payload") or {} for doc in model_docs]
        task_specs = [payload.get("task_spec") or {} for payload in task_payloads]

        active_domains = top_values([spec.get("Domain") for spec in task_specs])
        recent_targets = top_values([spec.get("Target_object") for spec in task_specs])
        spatial = top_values([spec.get("Spatial_scope") for spec in task_specs], limit=3)
        temporal = top_values([spec.get("Temporal_scope") for spec in task_specs], limit=3)
        resolutions = top_values([spec.get("Resolution_requirements") for spec in task_specs], limit=3)
        model_preferences = top_values([payload.get("model_name") for payload in model_payloads])

        pattern_parts = []
        if spatial:
            pattern_parts.append("空间: " + ", ".join(spatial))
        if temporal:
            pattern_parts.append("时间: " + ", ".join(temporal))
        if resolutions:
            pattern_parts.append("分辨率: " + ", ".join(resolutions))

        summary_parts = []
        if active_domains:
            summary_parts.append("常做领域为" + "、".join(active_domains[:3]))
        if recent_targets:
            summary_parts.append("近期关注" + "、".join(recent_targets[:3]))
        if model_preferences:
            summary_parts.append("常用模型包括" + "、".join(model_preferences[:3]))

        payload = {
            "summary": "；".join(summary_parts) if summary_parts else "暂无稳定画像",
            "active_domains": active_domains,
            "recent_targets": recent_targets,
            "spatiotemporal_patterns": pattern_parts,
            "model_preferences": model_preferences,
            "sample_size": {
                "tasks": len(task_docs),
                "models": len(model_docs),
            },
        }
        self._upsert_namespaced_doc(user_id, "user_snapshot", "user_snapshot", payload)
        self._upsert_vector_memory(user_id, "user_snapshot", "user_snapshot", f"user_snapshot:{user_id}", payload)
        return payload

    def retrieve_user_snapshot(self, user_id: str, query: str = "") -> Dict[str, Any]:
        """检索用户画像快照"""
        semantic = self._semantic_search_memory(user_id, "user_snapshot", query, 1) if query else []
        if semantic:
            return semantic[0]
        doc = self._find_latest_by_namespace(user_id, "user_snapshot")
        if doc:
            return self._doc_payload_with_meta(doc, 0.0)
        return self.update_user_snapshot(user_id)
