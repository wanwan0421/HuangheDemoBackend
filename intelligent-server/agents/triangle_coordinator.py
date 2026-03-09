"""
三角匹配协调器（Triangle Matching Coordinator）
实现流式 Task + Model + Data 的对齐检查

工作模式：流式 → 一键对齐
1. 流式接口（stream_agent）解析任务/推荐模型，同步写入session
2. 流式接口（data_scan_stream_endpoint）扫描数据，同步写入session
3. 一键对齐接口基于session数据执行对齐检查
"""

import asyncio
import json
import logging
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime
from enum import Enum

from agents.alignment.graph import alignment_agent, AlignmentState
from agents.data_monitor import get_data_scanner
from langchain.messages import HumanMessage

logger = logging.getLogger(__name__)


class MatchingStatus(Enum):
    """匹配状态"""
    PENDING = "pending"  # 等待执行
    PROCESSING = "processing"  # 处理中
    MATCHED = "matched"  # 完全匹配
    PARTIAL = "partial"  # 部分匹配
    MISMATCH = "mismatch"  # 不匹配
    ERROR = "error"  # 错误


class TriangleMatchingSession:
    """三角匹配会话"""
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.created_at = datetime.now().isoformat()
        
        # 三方信息
        self.task_spec: Optional[Dict[str, Any]] = None
        self.model_contract: Optional[Dict[str, Any]] = None
        self.data_profiles: List[Dict[str, Any]] = []
        
        # 对齐结果
        self.alignment_result: Optional[Dict[str, Any]] = None
        
        # 当前状态
        self.status = MatchingStatus.PENDING
        self.completed_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "status": self.status.value,
            "task_spec": self.task_spec,
            "model_contract": self.model_contract,
            "data_profiles": self.data_profiles,
            "alignment_result": self.alignment_result
        }


class TriangleMatchingCoordinator:
    """
    三角匹配协调器（批量处理模式）
    
    职责：
    1. 管理Task、Model、Data三方信息
    2. 执行批量对齐检查
    3. 维护会话状态
    """
    
    def __init__(self):
        self.sessions: Dict[str, TriangleMatchingSession] = {}
        self.data_scanner = get_data_scanner()

    def _get_or_create_session(self, session_id: str) -> TriangleMatchingSession:
        """获取或创建会话（用于流式阶段增量写入）"""
        session = self.sessions.get(session_id)
        if not session:
            session = TriangleMatchingSession(session_id)
            self.sessions[session_id] = session
        return session

    def update_task_and_model_from_stream(
        self,
        session_id: str,
        task_spec: Optional[Dict[str, Any]] = None,
        model_contract: Optional[Dict[str, Any]] = None
    ) -> TriangleMatchingSession:
        """由流式接口写入阶段1关键节点（Task_spec / Model_contract）"""
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
        profile: Dict[str, Any]
    ) -> TriangleMatchingSession:
        """由流式数据扫描接口写入单文件画像"""
        session = self._get_or_create_session(session_id)

        if not profile:
            return session

        payload = {
            "file_id": f"stream_{uuid.uuid4().hex[:12]}",
            "file_path": file_path,
            "profile": profile,
            "timestamp": datetime.now().isoformat(),
            "status": "active"
        }

        replaced = False
        for idx, item in enumerate(session.data_profiles):
            if item.get("file_path") == file_path:
                session.data_profiles[idx] = payload
                replaced = True
                break

        if not replaced:
            session.data_profiles.append(payload)

        if session.task_spec and session.model_contract:
            session.status = MatchingStatus.PENDING

        return session
    
    async def execute_alignment(self, session_id: str) -> TriangleMatchingSession:
        """
        一键对齐：基于已保存的会话数据执行对齐检查
        
        流程：读取会话中的 Task_spec + Model_contract + Data_profiles → 对齐检查
        
        Args:
            session_id: 会话ID（必须已在流式阶段填充task_spec/model_contract/data_profiles）
        
        Returns:
            完成对齐的会话对象
        """
        logger.info(f"执行对齐检查: {session_id}")
        
        # 获取已存在的会话
        session = self.sessions.get(session_id)
        if not session:
            raise Exception(f"会话不存在: {session_id}，请先通过流式接口创建会话")
        
        if not session.task_spec or not session.model_contract:
            raise Exception(f"会话不完整: {session_id}，缺少任务规范或模型契约")
        
        session.status = MatchingStatus.PROCESSING
        
        try:
            # 执行对齐
            await self._perform_alignment(session)
            session.completed_at = datetime.now().isoformat()
            logger.info(f"对齐完成: {session_id}, 状态: {session.status.value}")
            return session
        
        except Exception as e:
            logger.error(f"对齐失败: {session_id}, 错误: {e}")
            session.status = MatchingStatus.ERROR
            session.alignment_result = {
                "error": str(e),
                "overall_score": 0.0,
                "summary": f"对齐检查失败: {str(e)}",
                "blocking_issues": [f"对齐检查失败: {str(e)}"],
                "non_blocking_issues": [],
                "recommended_actions": ["请检查输入数据后重试"],
                "warnings": []
            }
            session.alignment_result.update(
                self._build_decision_package(
                    alignment_result=session.alignment_result,
                    model_contract=session.model_contract,
                    status=session.status
                )
            )
            return session
    
    async def _perform_alignment(self, session: TriangleMatchingSession):
        """
        执行对齐检查
        
        Args:
            session: 会话对象
        """
        if not session.data_profiles:
            logger.warning(f"会话 {session.session_id} 没有数据画像，跳过对齐")
            session.status = MatchingStatus.PENDING
            session.alignment_result = {
                "overall_score": 0.0,
                "summary": "未提供数据文件",
                "status": "pending",
                "blocking_issues": ["未提供数据文件，无法执行对齐检查"],
                "non_blocking_issues": [],
                "recommended_actions": ["请先上传模型需要的数据文件后重试"],
                "warnings": []
            }
            session.alignment_result.update(
                self._build_decision_package(
                    alignment_result=session.alignment_result,
                    model_contract=session.model_contract,
                    status=session.status
                )
            )
            return
        
        try:
            # 准备对齐输入
            alignment_initial_state: AlignmentState = {
                "messages": [],
                "Task_spec": session.task_spec,
                "Model_contract": session.model_contract,
                "Data_profile": self._merge_data_profiles(session.data_profiles),
                "Alignment_result": {},
                "status": "started"
            }
            
            # 调用Alignment Agent
            alignment_result_state = alignment_agent.invoke(alignment_initial_state)
            session.alignment_result = alignment_result_state.get("Alignment_result", {})
            
            # 判断对齐状态
            overall_score = session.alignment_result.get("overall_score", 0.0)
            if overall_score >= 0.9:
                session.status = MatchingStatus.MATCHED
            elif overall_score >= 0.5:
                session.status = MatchingStatus.PARTIAL
            else:
                session.status = MatchingStatus.MISMATCH

            session.alignment_result.update(
                self._build_decision_package(
                    alignment_result=session.alignment_result,
                    model_contract=session.model_contract,
                    status=session.status
                )
            )
            
            logger.info(f"对齐完成: {session.session_id}, 得分: {overall_score}, 状态: {session.status.value}")
        
        except Exception as e:
            logger.error(f"对齐检查失败: {e}")
            session.status = MatchingStatus.ERROR
            session.alignment_result = {
                "error": str(e),
                "overall_score": 0.0,
                "summary": f"对齐检查失败: {str(e)}",
                "blocking_issues": [f"对齐检查失败: {str(e)}"],
                "non_blocking_issues": [],
                "recommended_actions": ["请检查输入数据和模型契约后重试"],
                "warnings": []
            }
            session.alignment_result.update(
                self._build_decision_package(
                    alignment_result=session.alignment_result,
                    model_contract=session.model_contract,
                    status=session.status
                )
            )
    
    def _build_decision_package(
        self,
        alignment_result: Dict[str, Any],
        model_contract: Optional[Dict[str, Any]],
        status: MatchingStatus
    ) -> Dict[str, Any]:
        """构建Go/No-Go决策包，辅助用户做执行前判断"""
        blocking_issues = alignment_result.get("blocking_issues", []) or []
        non_blocking_issues = alignment_result.get("non_blocking_issues", []) or []
        per_slot = alignment_result.get("per_slot", []) or []
        suggested_transformations = alignment_result.get("suggested_transformations", []) or []

        warnings = list(non_blocking_issues)
        minimal_runnable_inputs: List[str] = []
        mapping_plan_draft: List[Dict[str, Any]] = []

        for slot in per_slot:
            input_name = slot.get("input_name", "unknown")
            slot_status = slot.get("overall_status") or slot.get("spec_alignment", {}).get("status", "partial")

            if slot_status in ["match", "partial"]:
                minimal_runnable_inputs.append(input_name)

            if slot_status == "partial":
                warnings.append(f"{input_name}: 存在部分不匹配，建议先执行映射")

            actions = slot.get("actions", []) or []
            if actions:
                mapping_plan_draft.append({
                    "input_name": input_name,
                    "priority": "high" if slot_status == "mismatch" else "medium",
                    "actions": actions
                })

        for transformation in suggested_transformations:
            mapping_plan_draft.append({
                "input_name": "global",
                "priority": "medium",
                "actions": [transformation]
            })

        required_slots = (model_contract or {}).get("Required_slots", []) or []
        file_estimate = len(minimal_runnable_inputs)
        required_count = len(required_slots)

        if blocking_issues:
            can_run_now = False
            go_no_go = "no-go"
            risk_level = "high"
        elif status in [MatchingStatus.MATCHED, MatchingStatus.PARTIAL]:
            can_run_now = True
            go_no_go = "go"
            risk_level = "medium" if warnings else "low"
        else:
            can_run_now = False
            go_no_go = "no-go"
            risk_level = "medium"

        recommended_actions: List[str] = []
        if blocking_issues:
            recommended_actions.append("存在阻塞问题，请先执行数据映射或补齐缺失输入后再运行模型")
        elif warnings:
            recommended_actions.append("可先用最小可运行输入集试跑，再迭代修复告警项")
        else:
            recommended_actions.append("可直接进入模型执行阶段")

        recommended_actions.append("修复后建议调用增量重扫接口，仅重扫变更文件并查看前后差异")

        estimated_minutes = max(2, required_count * 2)
        if required_count >= 8 or file_estimate >= 10:
            estimated_minutes = max(estimated_minutes, 20)

        return {
            "can_run_now": can_run_now,
            "go_no_go": go_no_go,
            "risk_level": risk_level,
            "warnings": warnings,
            "recommended_actions": recommended_actions,
            "minimal_runnable_inputs": list(dict.fromkeys(minimal_runnable_inputs)),
            "mapping_plan_draft": mapping_plan_draft,
            "execution_estimate": {
                "estimated_minutes": estimated_minutes,
                "required_slot_count": required_count,
                "available_input_count": file_estimate
            }
        }

    def _merge_data_profiles(self, data_profiles: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        合并多个数据画像为统一的Data_profile
        
        策略：
        - 如果只有一个数据文件，直接返回
        - 如果有多个数据文件，按照输入槽位组织
        """
        if not data_profiles:
            return {}
        
        if len(data_profiles) == 1:
            return data_profiles[0].get("profile", {})
        
        # 多数据文件合并
        merged_profile = {
            "data_sources": [],
            "spatial_union": {},
            "temporal_union": {},
            "forms": []
        }
        
        for dp in data_profiles:
            profile = dp.get("profile", {})
            merged_profile["data_sources"].append({
                "file_id": dp.get("file_id"),
                "file_path": dp.get("file_path"),
                "form": profile.get("Form"),
                "spatial": profile.get("Spatial"),
                "temporal": profile.get("Temporal")
            })
            
            # 收集数据形式
            form = profile.get("Form")
            if form and form not in merged_profile["forms"]:
                merged_profile["forms"].append(form)
        
        return merged_profile
    
    def get_session(self, session_id: str) -> Optional[TriangleMatchingSession]:
        """获取会话"""
        return self.sessions.get(session_id)
    
    def get_alignment_status(self, session_id: str) -> Dict[str, Any]:
        """
        获取对齐状态和建议
        
        Returns:
            {
                "status": "matched" | "partial" | "mismatch" | "pending" | "processing" | "error",
                "overall_score": 0.0-1.0,
                "summary": "...",
                "missing_data": [...],
                "recommendations": [...],
                "blocking_issues": [...]
            }
        """
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
                "execution_estimate": {}
            }
        
        alignment_result = session.alignment_result
        
        return {
            "status": session.status.value,
            "overall_score": alignment_result.get("overall_score", 0.0),
            "summary": alignment_result.get("summary", ""),
            "missing_data": self._extract_missing_data(alignment_result),
            "recommendations": alignment_result.get("recommendations", []),
            "blocking_issues": alignment_result.get("blocking_issues", []),
            "warnings": alignment_result.get("warnings", []),
            "can_run_now": alignment_result.get("can_run_now", False),
            "go_no_go": alignment_result.get("go_no_go", "no-go"),
            "risk_level": alignment_result.get("risk_level", "high"),
            "minimal_runnable_inputs": alignment_result.get("minimal_runnable_inputs", []),
            "mapping_plan_draft": alignment_result.get("mapping_plan_draft", []),
            "recommended_actions": alignment_result.get("recommended_actions", []),
            "execution_estimate": alignment_result.get("execution_estimate", {})
        }
    
    def _extract_missing_data(self, alignment_result: Dict[str, Any]) -> List[str]:
        """从对齐结果中提取缺失的数据"""
        missing_data = []
        
        per_slot = alignment_result.get("per_slot", [])
        for slot in per_slot:
            status = slot.get("overall_status", "")
            if status == "mismatch" or status == "missing":
                input_name = slot.get("input_name", "")
                gaps = slot.get("semantic_alignment", {}).get("gaps", [])
                if input_name:
                    missing_data.append(f"{input_name}: {', '.join(gaps)}")
        
        return missing_data

# 全局协调器实例
_coordinator_instance: Optional[TriangleMatchingCoordinator] = None


def get_coordinator() -> TriangleMatchingCoordinator:
    """获取协调器单例"""
    global _coordinator_instance
    if _coordinator_instance is None:
        _coordinator_instance = TriangleMatchingCoordinator()
    return _coordinator_instance

