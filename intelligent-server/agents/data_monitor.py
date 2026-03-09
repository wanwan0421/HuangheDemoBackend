"""
数据扫描管理器：批量数据扫描和管理
负责按需扫描用户上传的数据文件，并维护数据画像缓存
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
import hashlib
from agents.data_scan.graph import data_scan_agent, DataScanState
from langchain.messages import HumanMessage
import logging

logger = logging.getLogger(__name__)


class DataProfile:
    """数据画像记录"""
    def __init__(self, file_path: str, profile: Dict[str, Any], timestamp: str):
        self.file_path = file_path
        self.file_id = self._generate_file_id(file_path)
        self.profile = profile
        self.timestamp = timestamp
        self.status = "active"
    
    @staticmethod
    def _generate_file_id(file_path: str) -> str:
        """生成文件唯一标识"""
        return f"file_{hashlib.md5(file_path.encode('utf-8')).hexdigest()[:12]}"
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "file_id": self.file_id,
            "file_path": self.file_path,
            "profile": self.profile,
            "timestamp": self.timestamp,
            "status": self.status
        }


class DataProfileCache:
    """数据画像缓存管理器"""
    def __init__(self, cache_file: str = None):
        self.cache_file = cache_file or "data_profiles_cache.json"
        self.profiles: Dict[str, DataProfile] = {}
        self._load_cache()
    
    def _load_cache(self):
        """从文件加载缓存"""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for file_id, profile_data in data.items():
                        self.profiles[file_id] = DataProfile(
                            file_path=profile_data['file_path'],
                            profile=profile_data['profile'],
                            timestamp=profile_data['timestamp']
                        )
                        self.profiles[file_id].status = profile_data.get('status', 'active')
                logger.info(f"从缓存加载了 {len(self.profiles)} 个数据画像")
            except Exception as e:
                logger.error(f"加载缓存失败: {e}")
    
    def _save_cache(self):
        """保存缓存到文件"""
        try:
            data = {file_id: profile.to_dict() for file_id, profile in self.profiles.items()}
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"缓存已保存，包含 {len(self.profiles)} 个数据画像")
        except Exception as e:
            logger.error(f"保存缓存失败: {e}")
    
    def add_profile(self, file_path: str, profile: Dict[str, Any]) -> str:
        """添加新的数据画像"""
        timestamp = datetime.now().isoformat()
        data_profile = DataProfile(file_path, profile, timestamp)
        self.profiles[data_profile.file_id] = data_profile
        self._save_cache()
        logger.info(f"添加数据画像: {data_profile.file_id} - {file_path}")
        return data_profile.file_id
    
    def get_profile(self, file_id: str) -> Optional[DataProfile]:
        """获取数据画像"""
        return self.profiles.get(file_id)
    
    def get_all_profiles(self) -> List[DataProfile]:
        """获取所有活动的数据画像"""
        return [p for p in self.profiles.values() if p.status == "active"]
    
    def get_profiles_summary(self) -> Dict[str, Any]:
        """获取数据画像汇总"""
        active_profiles = self.get_all_profiles()
        return {
            "total_count": len(active_profiles),
            "profiles": [p.to_dict() for p in active_profiles],
            "last_updated": max([p.timestamp for p in active_profiles]) if active_profiles else None
        }
    
    def remove_profile(self, file_id: str):
        """移除数据画像"""
        if file_id in self.profiles:
            self.profiles[file_id].status = "deleted"
            self._save_cache()
            logger.info(f"移除数据画像: {file_id}")
    
    def clear_all(self):
        """清空所有数据画像"""
        self.profiles.clear()
        self._save_cache()
        logger.info("已清空所有数据画像")


class DataScanner:
    """数据扫描器：批量数据扫描管理"""
    def __init__(self):
        self.cache = DataProfileCache()
    
    async def scan_file(self, file_path: str) -> Optional[str]:
        """
        扫描单个文件，生成数据画像
        
        Returns:
            file_id: 文件标识
        """
        try:
            logger.info(f"开始扫描文件: {file_path}")
            
            # 等待文件写入完成
            await asyncio.sleep(0.2)
            
            # 调用Data Scan Agent
            initial_state: DataScanState = {
                "messages": [HumanMessage(content=f"请扫描文件: {file_path}")],
                "file_path": file_path,
                "facts": {},
                "profile": {},
                "explanation": "",
                "status": "started"
            }
            
            result = data_scan_agent.invoke(initial_state)
            
            if result.get("status") == "completed" and result.get("profile"):
                profile = result["profile"]
                file_id = self.cache.add_profile(file_path, profile)
                logger.info(f"文件扫描完成: {file_id}")
                return file_id
            else:
                logger.error(f"文件扫描失败: {file_path}")
                return None
        
        except Exception as e:
            logger.error(f"扫描文件时出错: {file_path}, 错误: {e}")
            return None
    
    async def scan_batch(self, file_paths: List[str]) -> List[Dict[str, Any]]:
        """
        批量扫描多个文件
        
        Args:
            file_paths: 文件路径列表
        
        Returns:
            扫描结果列表，包含file_id和profile
        """
        results = []
        
        for file_path in file_paths:
            file_id = await self.scan_file(file_path)
            if file_id:
                profile = self.cache.get_profile(file_id)
                if profile:
                    results.append(profile.to_dict())
        
        logger.info(f"批量扫描完成，共扫描 {len(results)} 个文件")
        return results

    async def rescan_with_diff(self, file_paths: List[str]) -> Dict[str, Any]:
        """
        增量重扫并返回前后差异

        Args:
            file_paths: 需要重扫的文件路径

        Returns:
            包含新增/变更/不变文件及差异详情
        """
        results: List[Dict[str, Any]] = []
        added: List[str] = []
        changed: List[Dict[str, Any]] = []
        unchanged: List[str] = []

        for file_path in file_paths:
            file_id = DataProfile._generate_file_id(file_path)
            old_profile_obj = self.cache.get_profile(file_id)
            old_profile = old_profile_obj.to_dict() if old_profile_obj else None

            new_file_id = await self.scan_file(file_path)
            if not new_file_id:
                continue

            new_profile_obj = self.cache.get_profile(new_file_id)
            if not new_profile_obj:
                continue

            new_profile = new_profile_obj.to_dict()
            results.append(new_profile)

            if old_profile is None:
                added.append(file_path)
                continue

            diff = self._compare_profiles(
                old_profile.get("profile", {}),
                new_profile.get("profile", {})
            )
            if diff["changed"]:
                changed.append({
                    "file_path": file_path,
                    "file_id": new_file_id,
                    "diff": diff
                })
            else:
                unchanged.append(file_path)

        return {
            "rescanned_count": len(results),
            "added_files": added,
            "changed_files": changed,
            "unchanged_files": unchanged,
            "data_profiles": results
        }

    def _compare_profiles(self, old_profile: Dict[str, Any], new_profile: Dict[str, Any]) -> Dict[str, Any]:
        """比较前后画像，返回简化差异摘要"""
        changed_fields: List[str] = []
        focus_fields = ["Form", "Spatial", "Temporal", "Variables", "Quality"]

        for field in focus_fields:
            if old_profile.get(field) != new_profile.get(field):
                changed_fields.append(field)

        return {
            "changed": len(changed_fields) > 0,
            "changed_fields": changed_fields,
            "before": {k: old_profile.get(k) for k in changed_fields},
            "after": {k: new_profile.get(k) for k in changed_fields}
        }
    
    async def scan_directory(self, directory: str) -> List[Dict[str, Any]]:
        """
        扫描整个目录
        
        Returns:
            扫描结果列表
        """
        file_paths = []
        
        for root, dirs, files in os.walk(directory):
            for file in files:
                file_path = os.path.join(root, file)
                # 过滤临时文件和隐藏文件
                if not file.startswith('.') and not file.endswith(('.tmp', '.temp')):
                    file_paths.append(file_path)
        
        return await self.scan_batch(file_paths)
    
    def get_all_data_profiles(self) -> Dict[str, Any]:
        """获取所有数据画像汇总"""
        return self.cache.get_profiles_summary()
    
    def get_data_profile(self, file_id: str) -> Optional[Dict[str, Any]]:
        """获取指定文件的数据画像"""
        profile = self.cache.get_profile(file_id)
        return profile.to_dict() if profile else None
    
    def clear_cache(self):
        """清空缓存"""
        self.cache.clear_all()


# 全局数据扫描器实例
_data_scanner_instance: Optional[DataScanner] = None


def get_data_scanner() -> DataScanner:
    """获取数据扫描器单例"""
    global _data_scanner_instance
    if _data_scanner_instance is None:
        _data_scanner_instance = DataScanner()
    return _data_scanner_instance
