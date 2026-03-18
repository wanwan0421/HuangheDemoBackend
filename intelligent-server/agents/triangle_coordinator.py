"""
Triangle Matching Coordinator

Flow:
1. Streaming endpoints update session Task/Model/Data incrementally.
2. Alignment agent reads session payload from API request and writes back summary state.
"""

import logging
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

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
    """Coordinates session lifecycle for multi-agent collaboration."""

    def __init__(self):
        self.sessions: Dict[str, TriangleMatchingSession] = {}

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

    def get_session(self, session_id: str) -> Optional[TriangleMatchingSession]:
        return self.sessions.get(session_id)


_coordinator_instance: Optional[TriangleMatchingCoordinator] = None


def get_coordinator() -> TriangleMatchingCoordinator:
    """Get coordinator singleton."""
    global _coordinator_instance
    if _coordinator_instance is None:
        _coordinator_instance = TriangleMatchingCoordinator()
    return _coordinator_instance
