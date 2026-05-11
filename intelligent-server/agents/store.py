from typing import List, Dict, Any, Optional
from pymongo import MongoClient, ASCENDING, DESCENDING
from datetime import datetime
import os

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")
MEMORY_COLLECTION = "userMemories"


class Store:
    """基础跨线程/跨会话存储（轻量实现）

    提供按 namespace 存取用户级长期记忆接口。
    """

    def __init__(self, mongo_uri: str = MONGO_URI, db_name: str = MONGO_DB_NAME):
        self.client = MongoClient(mongo_uri)
        self.db = self.client[db_name]
        self.collection = self._collection(MEMORY_COLLECTION)
        self._ensure_indexes()

    def _collection(self, name: str):
        return self.db[name]

    def _ensure_indexes(self) -> None:
        self.collection.create_index([("userId", ASCENDING), ("namespace", ASCENDING), ("updated_at", DESCENDING)])
        self.collection.create_index([("userId", ASCENDING), ("kind", ASCENDING), ("created_at", DESCENDING)])

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
        self.collection.insert_one(
            {
                "userId": user_id,
                "namespace": namespace,
                "kind": kind,
                "payload": payload,
                "created_at": now,
                "updated_at": now,
            }
        )

    def _find_latest_by_namespace(self, user_id: str, namespace: str) -> Optional[Dict[str, Any]]:
        return self.collection.find_one({"userId": user_id, "namespace": namespace}, sort=[("updated_at", DESCENDING)])

    # --- task_memory --------------------------------------------
    def add_task_memory(self, user_id: str, task_summary: str, task_spec: Dict[str, Any]):
        self._insert_memory(
            user_id,
            "task_memory",
            "task_memory",
            {
                "summary": task_summary,
                "task_spec": task_spec,
            },
        )

    def retrieve_task_memory(self, user_id: str, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        # 简单基于关键词匹配的检索实现；生产可接 embedding 服务
        keywords = set([w.lower() for w in query.split() if w.strip()])
        results = []
        for doc in self.collection.find({'userId': user_id, 'namespace': 'task_memory'}).sort('created_at', -1).limit(200):
            payload = doc.get('payload') or {}
            text = (payload.get('summary') or '') + ' ' + ' '.join(str(v) for v in (payload.get('task_spec') or {}).values())
            score = sum(1 for k in keywords if k in text.lower())
            if score > 0:
                results.append({'score': score, 'doc': payload | {'userId': user_id, 'namespace': 'task_memory'}})

        results.sort(key=lambda x: x['score'], reverse=True)
        return [r['doc'] for r in results[:limit]]

    # --- model_memory -------------------------------------------
    def add_model_memory(self, user_id: str, model_md5: str, model_name: str, reason: str = None, success: bool = True):
        self._insert_memory(
            user_id,
            "model_memory",
            "model_memory",
            {
                'model_md5': model_md5,
                'model_name': model_name,
                'reason': reason,
                'success': bool(success),
            },
        )

    def retrieve_model_memory(self, user_id: str, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        # 基于 model_name/ reason 的关键词匹配
        keywords = set([w.lower() for w in query.split() if w.strip()])
        results = []
        for doc in self.collection.find({'userId': user_id, 'namespace': 'model_memory'}).sort('created_at', -1).limit(200):
            payload = doc.get('payload') or {}
            text = (payload.get('model_name') or '') + ' ' + (payload.get('reason') or '')
            score = sum(1 for k in keywords if k in text.lower())
            if score > 0:
                results.append({'score': score, 'doc': payload | {'userId': user_id, 'namespace': 'model_memory'}})

        results.sort(key=lambda x: x['score'], reverse=True)
        return [r['doc'] for r in results[:limit]]

    # --- simple semantic search stub ----------------------------
    def semantic_search(self, namespace: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        # stub - for production replace with embeddings + vector DB
        parts = [part for part in namespace.split(':') if part]
        if len(parts) < 3:
            return []

        user_id = parts[1]
        bucket = parts[2]

        if bucket == 'task_memory':
            return self.retrieve_task_memory(user_id, query, limit=limit)
        if bucket == 'model_memory':
            return self.retrieve_model_memory(user_id, query, limit=limit)
        return []
