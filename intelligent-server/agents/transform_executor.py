"""
Data transformation execution utilities.
"""

import asyncio
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional

from agents.method_selector import MethodSelector


class TransformExecutor:
    """Executes remote transformation calls based on alignment output."""

    def __init__(
        self,
        data_method_base_url: str,
        data_method_token: str,
        method_selector: MethodSelector,
    ):
        self.data_method_base_url = data_method_base_url.rstrip("/")
        self.data_method_token = data_method_token
        self.method_selector = method_selector

    async def attempt_transformations(
        self,
        alignment_result: Dict[str, Any],
        data_profiles: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        per_slot = alignment_result.get("per_slot", []) or []
        suggested_transformations = alignment_result.get("suggested_transformations", []) or []

        attempts: List[Dict[str, Any]] = []

        for slot in per_slot:
            input_name = str(slot.get("input_name") or "unknown")
            slot_status = str(slot.get("overall_status") or slot.get("spec_alignment", {}).get("status") or "partial")
            if slot_status not in ["mismatch", "partial", "missing"]:
                continue

            slot_actions = slot.get("actions", []) or []
            all_hints = [str(item) for item in [*slot_actions, *suggested_transformations] if item]
            method_name = self.method_selector.extract_method_name_from_hints(all_hints)

            profile_item = self._find_profile_for_slot(data_profiles, input_name)
            if not profile_item:
                attempts.append(
                    {
                        "input_name": input_name,
                        "status": "skipped",
                        "reason": "未找到可用于转换的数据文件",
                    }
                )
                continue

            file_path = str(profile_item.get("file_path") or "")
            profile_data = profile_item.get("profile", {}) or {}
            data_id = self._resolve_data_id(profile_item, file_path, profile_data)

            file_extension = ""
            if file_path and "." in file_path:
                file_extension = "." + file_path.split(".")[-1]

            method_candidates: List[Dict[str, Any]] = []
            if not method_name:
                selection = self.method_selector.select_method(
                    input_name=input_name,
                    all_hints=all_hints,
                    file_extension=file_extension,
                    top_k=5,
                )
                method_name = str(selection.get("method_name") or "").strip()
                method_candidates = selection.get("candidates", []) or []

            if not method_name:
                attempts.append(
                    {
                        "input_name": input_name,
                        "status": "needs_manual_selection",
                        "reason": "未找到精确或模糊匹配的方法，请人工选择",
                        "candidates": method_candidates,
                        "hints": all_hints,
                    }
                )
                continue

            payload = {
                "convertMethod": method_name,
                "dataId": str(data_id),
                "filePath": file_path,
                "fileExtension": file_extension,
                "inputName": input_name,
                "actionHints": all_hints,
            }

            try:
                effective_data_id = str(data_id or "").strip()
                if not effective_data_id:
                    raise Exception("缺少可用的数据 ID，请传入 data_id 或上传后 URL（/data/{id}）")

                result_file_name = f"result_{int(datetime.now().timestamp())}{file_extension}"
                response = await asyncio.to_thread(
                    self._invoke_remote_method_by_name,
                    method_name,
                    effective_data_id,
                    result_file_name,
                )

                attempts.append(
                    {
                        "input_name": input_name,
                        "status": "success",
                        "request": {
                            **payload,
                            "dataId": effective_data_id,
                            "resultFileName": result_file_name,
                        },
                        "response": response,
                        "method_candidates": method_candidates,
                    }
                )
            except Exception as exc:
                attempts.append(
                    {
                        "input_name": input_name,
                        "status": "failed",
                        "request": payload,
                        "error": str(exc),
                        "method_candidates": method_candidates,
                    }
                )

        success_count = len([item for item in attempts if item.get("status") == "success"])
        failed_count = len([item for item in attempts if item.get("status") == "failed"])

        alignment_result["transformation_attempts"] = attempts
        alignment_result["auto_transform_summary"] = {
            "attempted": len(attempts),
            "success": success_count,
            "failed": failed_count,
            "invoke_url": f"{self.data_method_base_url}/container/method/invoke/{{methodId}}",
        }

        recommended_actions = alignment_result.get("recommended_actions", []) or []
        if success_count > 0:
            recommended_actions.append("已触发数据转换，请对转换结果执行数据重扫并重新对齐")
        elif attempts:
            recommended_actions.append("数据转换尝试失败，请检查方法名、dataId 和数据服务连通性后重试")
            recommended_actions.append("若未匹配到方法，请从 candidates 中人工选定 convertMethod 后重试")
        alignment_result["recommended_actions"] = list(dict.fromkeys(recommended_actions))

        return alignment_result

    def _find_profile_for_slot(self, data_profiles: List[Dict[str, Any]], input_name: str) -> Optional[Dict[str, Any]]:
        normalized_name = str(input_name or "").strip().lower()
        for item in data_profiles:
            slot_key = str(item.get("slot_key") or "").strip().lower()
            if slot_key and slot_key == normalized_name:
                return item

        for item in data_profiles:
            if item.get("file_path"):
                return item

        return None

    def _resolve_data_id(self, profile_item: Dict[str, Any], file_path: str, profile_data: Dict[str, Any]) -> str:
        data_id = (
            profile_item.get("data_id")
            or profile_item.get("uploaded_data_id")
            or profile_item.get("remote_data_id")
            or profile_data.get("data_id")
            or profile_data.get("id")
        )
        if data_id:
            return str(data_id).strip()

        file_path_str = str(file_path or "").strip()
        if not file_path_str:
            return ""

        match = re.search(r"/data/([^/?#]+)", file_path_str)
        if match:
            return match.group(1).strip()

        if file_path_str.startswith("http://") or file_path_str.startswith("https://"):
            tail = file_path_str.rstrip("/").split("/")[-1]
            return tail.strip()

        return ""

    def _container_get(self, endpoint: str, timeout: int = 30) -> Dict[str, Any]:
        url = f"{self.data_method_base_url}/{endpoint.lstrip('/')}"
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

    def _container_post(self, endpoint: str, payload: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
        url = f"{self.data_method_base_url}/{endpoint.lstrip('/')}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "token": self.data_method_token,
                "Content-Type": "application/json",
            },
            method="POST",
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
            raise Exception(f"容器服务 POST 失败: HTTP {exc.code}: {detail}")

    def _invoke_remote_method_by_name(self, method_name: str, data_id: str, result_file_name: str) -> Dict[str, Any]:
        quoted_name = urllib.parse.quote(method_name, safe="")
        detail = self._container_get(f"container/method/infoByName/{quoted_name}")
        method = detail.get("method") or {}
        method_id = method.get("id")
        if method_id is None:
            raise Exception(f"方法 {method_name} 未返回 method id")

        invoke_payload = {
            "val0": data_id,
            "val1": result_file_name,
        }
        invoke_resp = self._container_post(f"container/method/invoke/{method_id}", invoke_payload, timeout=120)
        return {
            "method_id": method_id,
            "method_name": method_name,
            "request": invoke_payload,
            "response": {
                "code": invoke_resp.get("code", 0),
                "msg": invoke_resp.get("msg", ""),
                "output": invoke_resp.get("output", {}),
                "info": invoke_resp.get("info", ""),
            },
        }
