"""
Triangle Matching Coordinator

Flow:
1. Streaming endpoints update session Task/Model/Data incrementally.
2. Align endpoint runs alignment from persisted session payload.
3. Optional auto transform is triggered for partial/mismatch cases.
"""

import logging
import os
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from agents.alignment_orchestrator import AlignmentOrchestrator
from agents.data_monitor import get_data_scanner
from agents.method_selector import MethodSelector
from agents.transform_executor import TransformExecutor

logger = logging.getLogger(__name__)


class MatchingStatus(Enum):
    """Alignment status."""

    PENDING = "pending"
    PROCESSING = "processing"
    MATCHED = "matched"
    PARTIAL = "partial"
    MISMATCH = "mismatch"
    ERROR = "error"


class TriangleMatchingSession:
    """Session object for task-model-data alignment."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.created_at = datetime.now().isoformat()

        self.task_spec: Optional[Dict[str, Any]] = None
        self.model_contract: Optional[Dict[str, Any]] = None
        self.data_profiles: List[Dict[str, Any]] = []

        self.alignment_result: Optional[Dict[str, Any]] = None
        self.status = MatchingStatus.PENDING
        self.completed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
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


class TriangleMatchingCoordinator:
    """Coordinates session lifecycle, alignment and optional transformation."""

    def __init__(self):
        self.sessions: Dict[str, TriangleMatchingSession] = {}
        self.data_scanner = get_data_scanner()

        data_method_base_url = (os.getenv("DATA_METHOD_BASE_URL") or "http://172.21.252.222:8080").rstrip("/")
        data_method_token = os.getenv("DATA_METHOD_TOKEN") or ""
        mongo_uri = os.getenv("MONGO_URI") or "mongodb://localhost:27017/"
        mongo_db_name = os.getenv("MONGO_DB_NAME") or "huanghe-demo"

        self.alignment_orchestrator = AlignmentOrchestrator()
        self.method_selector = MethodSelector(
            data_method_base_url=data_method_base_url,
            data_method_token=data_method_token,
            mongo_uri=mongo_uri,
            mongo_db_name=mongo_db_name,
        )
        self.transform_executor = TransformExecutor(
            data_method_base_url=data_method_base_url,
            data_method_token=data_method_token,
            method_selector=self.method_selector,
        )

    def _get_or_create_session(self, session_id: str) -> TriangleMatchingSession:
        session = self.sessions.get(session_id)
        if not session:
            session = TriangleMatchingSession(session_id)
            self.sessions[session_id] = session
        return session

    def _status_from_text(self, status_text: str) -> MatchingStatus:
        mapping = {
            "pending": MatchingStatus.PENDING,
            "processing": MatchingStatus.PROCESSING,
            "matched": MatchingStatus.MATCHED,
            "partial": MatchingStatus.PARTIAL,
            "mismatch": MatchingStatus.MISMATCH,
            "error": MatchingStatus.ERROR,
        }
        return mapping.get(status_text, MatchingStatus.ERROR)

    def update_task_and_model_from_stream(
        self,
        session_id: str,
        task_spec: Optional[Dict[str, Any]] = None,
        model_contract: Optional[Dict[str, Any]] = None,
    ) -> TriangleMatchingSession:
        session = self._get_or_create_session(session_id)

        if task_spec:
            session.task_spec = task_spec
        if model_contract:
            session.model_contract = model_contract

        if session.task_spec and session.model_contract:
            session.status = MatchingStatus.PENDING
        else:
            session.status = MatchingStatus.PROCESSING

        return session

    def add_data_profile_from_stream(
        self,
        session_id: str,
        file_path: str,
        profile: Dict[str, Any],
    ) -> TriangleMatchingSession:
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

        replaced = False
        for index, item in enumerate(session.data_profiles):
            if item.get("file_path") == file_path:
                session.data_profiles[index] = payload
                replaced = True
                break

        if not replaced:
            session.data_profiles.append(payload)

        if session.task_spec and session.model_contract:
            session.status = MatchingStatus.PENDING

        return session

    async def execute_alignment(self, session_id: str, auto_transform: bool = True) -> TriangleMatchingSession:
        """Run alignment and optional auto transformation for an existing session."""
        logger.info("执行对齐检查: %s", session_id)

        session = self.sessions.get(session_id)
        if not session:
            raise Exception(f"会话不存在: {session_id}，请先通过流式接口创建会话")

        if not session.task_spec or not session.model_contract:
            raise Exception(f"会话不完整: {session_id}，缺少任务规范或模型契约")

        session.status = MatchingStatus.PROCESSING

        try:
            alignment_payload = self.alignment_orchestrator.perform_alignment(
                task_spec=session.task_spec,
                model_contract=session.model_contract,
                data_profiles=session.data_profiles,
            )
            session.status = self._status_from_text(alignment_payload.get("status", "error"))
            session.alignment_result = alignment_payload.get("alignment_result", {})

            if auto_transform and session.status in [MatchingStatus.PARTIAL, MatchingStatus.MISMATCH]:
                session.alignment_result = await self.transform_executor.attempt_transformations(
                    alignment_result=session.alignment_result or {},
                    data_profiles=session.data_profiles,
                )

            session.completed_at = datetime.now().isoformat()
            logger.info("对齐完成: %s, 状态: %s", session_id, session.status.value)
            return session

        except Exception as exc:
            logger.error("对齐失败: %s, 错误: %s", session_id, exc)
            session.status = MatchingStatus.ERROR
            session.alignment_result = {
                "error": str(exc),
                "overall_score": 0.0,
                "summary": f"对齐检查失败: {str(exc)}",
                "blocking_issues": [f"对齐检查失败: {str(exc)}"],
                "non_blocking_issues": [],
                "recommended_actions": ["请检查输入数据后重试"],
                "warnings": [],
            }
            session.alignment_result.update(
                self.alignment_orchestrator.build_decision_package(
                    alignment_result=session.alignment_result,
                    model_contract=session.model_contract,
                    status=session.status.value,
                )
            )
            return session

    def get_session(self, session_id: str) -> Optional[TriangleMatchingSession]:
        return self.sessions.get(session_id)

    def get_alignment_status(self, session_id: str) -> Dict[str, Any]:
        session = self.sessions.get(session_id)
        if not session:
            return {"error": "会话不存在"}

        if not session.alignment_result:
            return {
                "status": session.status.value,
                "overall_score": 0.0,
                "summary": "对齐尚未执行",
                "missing_data": [],
                "recommendations": [],
                "blocking_issues": [],
                "warnings": [],
                "can_run_now": False,
                "go_no_go": "no-go",
                "risk_level": "high",
                "minimal_runnable_inputs": [],
                "mapping_plan_draft": [],
                "recommended_actions": [],
                "execution_estimate": {},
            }

        alignment_result = session.alignment_result
        return {
            "status": session.status.value,
            "overall_score": alignment_result.get("overall_score", 0.0),
            "summary": alignment_result.get("summary", ""),
            "missing_data": self.alignment_orchestrator.extract_missing_data(alignment_result),
            "recommendations": alignment_result.get("recommendations", []),
            "blocking_issues": alignment_result.get("blocking_issues", []),
            "warnings": alignment_result.get("warnings", []),
            "can_run_now": alignment_result.get("can_run_now", False),
            "go_no_go": alignment_result.get("go_no_go", "no-go"),
            "risk_level": alignment_result.get("risk_level", "high"),
            "minimal_runnable_inputs": alignment_result.get("minimal_runnable_inputs", []),
            "mapping_plan_draft": alignment_result.get("mapping_plan_draft", []),
            "recommended_actions": alignment_result.get("recommended_actions", []),
            "execution_estimate": alignment_result.get("execution_estimate", {}),
        }


_coordinator_instance: Optional[TriangleMatchingCoordinator] = None


def get_coordinator() -> TriangleMatchingCoordinator:
    """Get coordinator singleton."""
    global _coordinator_instance
    if _coordinator_instance is None:
        _coordinator_instance = TriangleMatchingCoordinator()
    return _coordinator_instance
