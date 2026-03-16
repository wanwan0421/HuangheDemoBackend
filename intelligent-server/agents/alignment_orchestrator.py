"""
Alignment orchestration utilities.
"""

import logging
from typing import Any, Dict, List, Optional

from agents.alignment.graph import AlignmentState, alignment_agent

logger = logging.getLogger(__name__)


class AlignmentOrchestrator:
    """Encapsulates alignment execution and decision packaging."""

    def perform_alignment(
        self,
        task_spec: Dict[str, Any],
        model_contract: Dict[str, Any],
        data_profiles: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not data_profiles:
            alignment_result: Dict[str, Any] = {
                "overall_score": 0.0,
                "summary": "未提供数据文件",
                "status": "pending",
                "blocking_issues": ["未提供数据文件，无法执行对齐检查"],
                "non_blocking_issues": [],
                "recommended_actions": ["请先上传模型需要的数据文件后重试"],
                "warnings": [],
            }
            alignment_result.update(
                self.build_decision_package(
                    alignment_result=alignment_result,
                    model_contract=model_contract,
                    status="pending",
                )
            )
            return {
                "status": "pending",
                "alignment_result": alignment_result,
            }

        try:
            alignment_initial_state: AlignmentState = {
                "messages": [],
                "Task_spec": task_spec,
                "Model_contract": model_contract,
                "Data_profile": self.merge_data_profiles(data_profiles),
                "Alignment_result": {},
                "status": "started",
            }

            alignment_result_state = alignment_agent.invoke(alignment_initial_state)
            alignment_result = alignment_result_state.get("Alignment_result", {})

            overall_score = alignment_result.get("overall_score", 0.0)
            if overall_score >= 0.9:
                status = "matched"
            elif overall_score >= 0.5:
                status = "partial"
            else:
                status = "mismatch"

            alignment_result.update(
                self.build_decision_package(
                    alignment_result=alignment_result,
                    model_contract=model_contract,
                    status=status,
                )
            )

            return {
                "status": status,
                "alignment_result": alignment_result,
            }

        except Exception as exc:
            logger.error("对齐检查失败: %s", exc)
            alignment_result = {
                "error": str(exc),
                "overall_score": 0.0,
                "summary": f"对齐检查失败: {str(exc)}",
                "blocking_issues": [f"对齐检查失败: {str(exc)}"],
                "non_blocking_issues": [],
                "recommended_actions": ["请检查输入数据和模型契约后重试"],
                "warnings": [],
            }
            alignment_result.update(
                self.build_decision_package(
                    alignment_result=alignment_result,
                    model_contract=model_contract,
                    status="error",
                )
            )
            return {
                "status": "error",
                "alignment_result": alignment_result,
            }

    def build_decision_package(
        self,
        alignment_result: Dict[str, Any],
        model_contract: Optional[Dict[str, Any]],
        status: str,
    ) -> Dict[str, Any]:
        """Build a Go/No-Go decision package from alignment output."""
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
                mapping_plan_draft.append(
                    {
                        "input_name": input_name,
                        "priority": "high" if slot_status == "mismatch" else "medium",
                        "actions": actions,
                    }
                )

        for transformation in suggested_transformations:
            mapping_plan_draft.append(
                {
                    "input_name": "global",
                    "priority": "medium",
                    "actions": [transformation],
                }
            )

        required_slots = (model_contract or {}).get("Required_slots", []) or []
        file_estimate = len(minimal_runnable_inputs)
        required_count = len(required_slots)

        if blocking_issues:
            can_run_now = False
            go_no_go = "no-go"
            risk_level = "high"
        elif status in ["matched", "partial"]:
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
                "available_input_count": file_estimate,
            },
        }

    def merge_data_profiles(self, data_profiles: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Merge multiple data profiles for alignment agent input."""
        if not data_profiles:
            return {}

        if len(data_profiles) == 1:
            return data_profiles[0].get("profile", {})

        merged_profile: Dict[str, Any] = {
            "data_sources": [],
            "spatial_union": {},
            "temporal_union": {},
            "forms": [],
        }

        for data_profile in data_profiles:
            profile = data_profile.get("profile", {})
            merged_profile["data_sources"].append(
                {
                    "file_id": data_profile.get("file_id"),
                    "file_path": data_profile.get("file_path"),
                    "form": profile.get("Form"),
                    "spatial": profile.get("Spatial"),
                    "temporal": profile.get("Temporal"),
                }
            )

            form = profile.get("Form")
            if form and form not in merged_profile["forms"]:
                merged_profile["forms"].append(form)

        return merged_profile

    def extract_missing_data(self, alignment_result: Dict[str, Any]) -> List[str]:
        """Extract missing input hints from alignment output."""
        missing_data: List[str] = []

        per_slot = alignment_result.get("per_slot", []) or []
        for slot in per_slot:
            slot_status = slot.get("overall_status", "")
            if slot_status in ["mismatch", "missing"]:
                input_name = slot.get("input_name", "")
                gaps = slot.get("semantic_alignment", {}).get("gaps", [])
                if input_name:
                    missing_data.append(f"{input_name}: {', '.join(gaps)}")

        return missing_data
