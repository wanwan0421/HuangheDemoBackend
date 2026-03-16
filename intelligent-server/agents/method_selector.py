"""
Method selection utilities for data transformation.
"""

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from pymongo import MongoClient

logger = logging.getLogger(__name__)


class MethodSelector:
    """Finds and ranks candidate transformation methods."""

    def __init__(
        self,
        data_method_base_url: str,
        data_method_token: str,
        mongo_uri: str,
        mongo_db_name: str,
    ):
        self.data_method_base_url = data_method_base_url.rstrip("/")
        self.data_method_token = data_method_token
        self.mongo_uri = mongo_uri
        self.mongo_db_name = mongo_db_name
        self._db_client: Optional[MongoClient] = None

    def extract_method_name_from_hints(self, hints: List[str]) -> Optional[str]:
        for hint in hints:
            text = str(hint or "").strip()
            if not text:
                continue

            quoted = re.findall(r"[`'\"]([^`'\"]+)[`'\"]", text)
            for name in quoted:
                candidate = name.strip()
                if candidate and len(candidate) >= 2:
                    return candidate

            match = re.search(
                r"(?:方法|method|method_name|convertMethod)\s*[:：]\s*([A-Za-z0-9_\-\u4e00-\u9fa5]+)",
                text,
                re.IGNORECASE,
            )
            if match:
                return match.group(1).strip()

        return None

    def select_method(
        self,
        input_name: str,
        all_hints: List[str],
        file_extension: str,
        top_k: int = 5,
    ) -> Dict[str, Any]:
        remote_candidates = self.rank_remote_method_candidates(
            input_name=input_name,
            all_hints=all_hints,
            file_extension=file_extension,
            top_k=top_k,
        )

        mongo_candidates = self.rank_method_candidates(
            input_name=input_name,
            all_hints=[json.dumps(item, ensure_ascii=False) for item in remote_candidates] + all_hints,
            file_extension=file_extension,
            top_k=top_k,
        )

        combined: Dict[str, Dict[str, Any]] = {}
        for item in [*remote_candidates, *mongo_candidates]:
            name = str(item.get("name") or "").strip()
            if not name:
                continue

            current = combined.get(name)
            if not current:
                combined[name] = item
                continue

            current_score = float(current.get("score") or 0.0)
            incoming_score = float(item.get("score") or 0.0)
            if incoming_score > current_score:
                combined[name] = item

        candidates = sorted(
            list(combined.values()),
            key=lambda candidate: float(candidate.get("score") or 0.0),
            reverse=True,
        )[:top_k]

        method_name = ""
        if candidates:
            method_name = str(candidates[0].get("name") or "").strip()

        return {
            "method_name": method_name,
            "candidates": candidates,
        }

    def _container_get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        query = urllib.parse.urlencode(params or {})
        url = f"{self.data_method_base_url}/{endpoint.lstrip('/')}"
        if query:
            url = f"{url}?{query}"

        req = urllib.request.Request(
            url,
            headers={"token": self.data_method_token},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
                if data.get("code", 0) != 0:
                    raise Exception(data.get("msg") or "数据处理服务返回错误")
                return data
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else str(exc)
            raise Exception(f"容器服务 GET 失败: HTTP {exc.code}: {detail}")

    def _list_remote_methods_by_keyword(self, keyword: str, limit: int = 200) -> List[Dict[str, Any]]:
        page = 1
        collected: List[Dict[str, Any]] = []

        first = self._container_get(
            "container/method/listWithTag",
            params={"page": page, "limit": limit, "key": keyword} if keyword else {"page": page, "limit": limit},
        )

        page_data = first.get("page") or {}
        total_count = int(page_data.get("totalCount") or 0)
        total_pages = max(1, (total_count + limit - 1) // limit)
        collected.extend(page_data.get("list") or [])

        for current in range(2, total_pages + 1):
            data = self._container_get(
                "container/method/listWithTag",
                params={"page": current, "limit": limit, "key": keyword}
                if keyword
                else {"page": current, "limit": limit},
            )
            current_page = data.get("page") or {}
            collected.extend(current_page.get("list") or [])

        return collected

    def rank_remote_method_candidates(
        self,
        input_name: str,
        all_hints: List[str],
        file_extension: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        tokens = self._normalize_tokens([input_name, file_extension, *all_hints])
        search_tokens = [token for token in tokens if token and len(token) >= 2][:6]

        if not search_tokens:
            return []

        candidate_map: Dict[str, Dict[str, Any]] = {}

        for token in search_tokens:
            try:
                methods = self._list_remote_methods_by_keyword(token, limit=120)
            except Exception as exc:
                logger.warning("远程方法检索失败（token=%s）: %s", token, exc)
                continue

            for method_item in methods:
                method_id = str(method_item.get("id") or "")
                method_name = str(method_item.get("name") or "")
                if not method_name:
                    continue

                key = method_id or method_name
                entry = candidate_map.get(key)
                if not entry:
                    entry = {
                        "id": method_item.get("id"),
                        "name": method_name,
                        "description": str(method_item.get("description") or ""),
                        "longDesc": str(method_item.get("longDesc") or ""),
                        "params": method_item.get("params") or [],
                        "score": 0.0,
                    }
                    candidate_map[key] = entry

                searchable = " ".join(
                    [
                        entry.get("name", ""),
                        entry.get("description", ""),
                        entry.get("longDesc", ""),
                        json.dumps(entry.get("params", []), ensure_ascii=False),
                    ]
                ).lower()

                if token.lower() in searchable:
                    entry["score"] = float(entry.get("score", 0.0)) + 1.0

                if any(keyword in searchable for keyword in ["转换", "转化", "convert", "reproject", "重投影"]):
                    entry["score"] = float(entry.get("score", 0.0)) + 0.3

        ranked = sorted(candidate_map.values(), key=lambda item: float(item.get("score", 0.0)), reverse=True)
        return ranked[:top_k]

    def _get_db(self):
        if self._db_client is None:
            self._db_client = MongoClient(self.mongo_uri)
        return self._db_client[self.mongo_db_name]

    def _normalize_tokens(self, texts: List[str]) -> List[str]:
        tokens: List[str] = []
        for text in texts:
            parts = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9_\-]+", str(text or "").lower())
            tokens.extend([part for part in parts if len(part) >= 2])

        defaults = [
            "转换",
            "转化",
            "投影",
            "重投影",
            "重采样",
            "裁剪",
            "格式",
            "crs",
            "convert",
            "reproject",
            "resample",
        ]
        return list(dict.fromkeys(tokens + defaults))

    def rank_method_candidates(
        self,
        input_name: str,
        all_hints: List[str],
        file_extension: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        try:
            db = self._get_db()
            collection = db["modelResource"]

            docs = list(
                collection.find(
                    {"type": "METHOD"},
                    {
                        "_id": 0,
                        "id": 1,
                        "name": 1,
                        "description": 1,
                        "normalTags": 1,
                        "inputParams": 1,
                        "outputParams": 1,
                        "updateTime": 1,
                    },
                )
            )
        except Exception as exc:
            logger.warning("方法元数据读取失败，跳过 Python 侧检索: %s", exc)
            return []

        if not docs:
            return []

        token_source = [input_name, file_extension, *all_hints]
        tokens = self._normalize_tokens(token_source)

        ranked: List[Dict[str, Any]] = []
        for doc in docs:
            name = str(doc.get("name") or "")
            description = str(doc.get("description") or "")
            tags = [str(item) for item in (doc.get("normalTags") or [])]
            input_params = [
                str(item.get("name") or "")
                for item in (doc.get("inputParams") or [])
                if isinstance(item, dict)
            ]
            output_params = [
                str(item.get("name") or "")
                for item in (doc.get("outputParams") or [])
                if isinstance(item, dict)
            ]

            searchable = " ".join([name, description, " ".join(tags), " ".join(input_params), " ".join(output_params)]).lower()
            score = 0.0

            for token in tokens:
                if token in searchable:
                    score += 1

            if input_params:
                score += 0.2
            if output_params:
                score += 0.2

            if any(keyword in searchable for keyword in ["转换", "转化", "convert", "reproject", "重投影"]):
                score += 0.5

            ranked.append(
                {
                    "id": doc.get("id"),
                    "name": name,
                    "description": description,
                    "score": round(float(score), 3),
                    "normalTags": tags,
                    "inputParams": input_params,
                    "outputParams": output_params,
                    "updateTime": str(doc.get("updateTime") or ""),
                }
            )

        ranked.sort(key=lambda item: (item.get("score", 0), item.get("updateTime", "")), reverse=True)
        return ranked[:top_k]
