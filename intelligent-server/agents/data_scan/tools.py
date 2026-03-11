import json
import os
from typing import Annotated, Dict, Any, List, Optional, TypedDict, Set
from pathlib import Path
import pandas as pd
import xarray as xr
import h5py
import rasterio
import geopandas as gpd
import zipfile
import tarfile
import tempfile
import shutil
import re
from langchain.tools import tool
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.messages import AnyMessage
import operator
from pyproj import CRS
import numpy as np
import hashlib

ARCHIVE_EXTENSIONS = ['.zip', '.tar', '.gz', '.rar']

# 初始化模型
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

data_scan_model = ChatGoogleGenerativeAI(
    model= "gemini-2.5-flash",
    temperature=0,
    max_retries=2,
    streaming=True,
    google_api_key=GOOGLE_API_KEY ,
)

class DataScanState(TypedDict):
    """
    数据分析LLM辅助状态体
    """
    # LLM 对话
    messages: Annotated[List[AnyMessage], operator.add]

    # 输入
    file_path: str

    # 工具“事实层”
    facts: Annotated[Dict[str, Any], operator.or_]

    # 结构化数据画像
    profile: Annotated[Dict[str, Any], operator.or_]

    # 解释层 
    explanation: Annotated[str, operator.add]

    # 状态
    status: str

# ============================================================================
# 工具 0: 文件准备工具（解压、识别主文件）
# ============================================================================

@tool
def tool_prepare_file(file_path: str) -> Dict[str, Any]:
    """
    根据用户上传的文件路径，准备数据文件：
    1. 如果是压缩包，解压到临时目录
    2. 如果是目录，扫描目录下文件
    3. 识别主文件（依据优先级规则）
    Args:
        file_path: 用户上传的文件路径
    Returns: {
        status: "success" | "error",
        primary_file: "解压后的主文件路径",
        temp_dir: "临时目录（如果有解压）",
        file_type: "single" | "archive" | "directory"
    }
    """
    try:
        file_path_obj = Path(file_path)

        # 生成指纹ID
        file_id = f"uid_{hashlib.md5(file_path.encode('utf-8')).hexdigest()[:8]}"
        
        # 情况1：单个文件
        if file_path_obj.is_file():
            ext = file_path_obj.suffix.lower()
            
            # 压缩包格式
            if ext in ['.zip', '.tar', '.gz', '.rar']:
                return handle_archive(file_path)
            
            # 普通单文件
            return {
                "status": "success",
                "file_id": file_id,
                "primary_file": str(file_path),
                "temp_dir": None,
                "file_type": "single",
                "file_size_mb": round(os.path.getsize(file_path) / (1024*1024), 2)
            }
        
        # 情况2：目录
        if file_path_obj.is_dir():
            all_files = collect_files(file_path)
            primary = identify_primary_file(all_files)
            
            return {
                "status": "success",
                "file_id": file_id,
                "primary_file": primary,
                "temp_dir": None,
                "file_type": "directory",
                "file_size_mb": round(os.path.getsize(file_path) / (1024*1024), 2)
            }
        
        return {
            "status": "error",
            "error": f"文件或目录不存在: {file_path}"
        }
        
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }

def handle_archive(archive_path: str) -> Dict[str, Any]:
    """处理压缩包：解压并识别主文件"""
    try:
        ext = Path(archive_path).suffix.lower()
        temp_dir = tempfile.mkdtemp()
        # 生成指纹ID
        file_id = f"uid_{hashlib.md5(archive_path.encode('utf-8')).hexdigest()[:8]}"
        
        # 解压
        if ext == '.zip':
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
        elif ext in ['.tar', '.gz']:
            with tarfile.open(archive_path, 'r:*') as tar_ref:
                tar_ref.extractall(temp_dir)
        else:
            return {
                "status": "error",
                "error": f"不支持的压缩格式: {ext}"
            }
        
        # 收集解压后的文件
        all_files = collect_files(temp_dir)
        if not all_files:
            return {
                "status": "error",
                "error": "压缩包内没有可识别文件"
            }

        primary = identify_primary_file(all_files)
        candidates = identify_primary_candidates(all_files)
        sidecar_exts = [f.suffix.lower() for f in Path(temp_dir).glob(f"{Path(primary).stem}.*")]
        
        return {
            "status": "success",
            "file_id": file_id,
            "primary_file": primary,
            "temp_dir": temp_dir,
            "sidecar_files": sidecar_exts,
            "primary_candidates": candidates,
            "archive_file_count": len(all_files),
            "all_files": all_files,
            "file_type": "archive",
            "file_size_mb": round(os.path.getsize(archive_path) / (1024*1024), 2)
        }
        
    except Exception as e:
        if 'temp_dir' in locals():
            shutil.rmtree(temp_dir, ignore_errors=True)
        return {
            "status": "error",
            "error": str(e)
        }

def collect_files(dir_path: str) -> List[str]:
    """
    递归收集目录下所有文件
    Args:
        dir_path: 目录路径
    Returns:
        文件路径列表
    """
    files = []
    for root, _, filenames in os.walk(dir_path):
        for filename in filenames:
            # 跳过隐藏文件和系统文件
            if not filename.startswith('.') and not filename.startswith('__'):
                files.append(os.path.join(root, filename))
    return files

def identify_primary_file(files: List[str]) -> str:
    """
    从文件列表中识别主文件
    优先级：
    1. XML（参数文件）
    2. .shp（Shapefile 主文件）
    3. .tif/.tiff（栅格）
    4. .nc（NetCDF）
    5. .csv/.json（表格/矢量）
    """
    if not files:
        return ""
    
    # 按优先级排序
    priority_extensions = [
        '.xml',
        '.tif', '.tiff', '.geotiff',
        '.shp',
        '.nc', '.netcdf',
        '.geojson',
        '.csv',
        '.json',
        '.h5', '.hdf', '.hdf5'
    ]
    
    for ext in priority_extensions:
        for file in files:
            if file.lower().endswith(ext):
                return file
    
    # 如果没有匹配，返回第一个非临时文件
    return files[0]


def identify_primary_candidates(files: List[str]) -> List[str]:
    """返回按优先级排序的候选主文件列表"""
    if not files:
        return []

    priority_extensions = [
        '.xml',
        '.tif', '.tiff', '.geotiff',
        '.shp',
        '.nc', '.netcdf',
        '.geojson',
        '.csv',
        '.json',
        '.h5', '.hdf', '.hdf5'
    ]

    ranked: List[str] = []
    for ext in priority_extensions:
        ranked.extend([f for f in files if f.lower().endswith(ext)])

    extras = [f for f in files if f not in ranked]
    return ranked + extras


def resolve_primary_file(file_path: str) -> Dict[str, Any]:
    """将输入路径统一解析为可分析的主文件路径，支持单文件/目录/压缩包"""
    file_path_obj = Path(file_path)

    if file_path_obj.is_file() and file_path_obj.suffix.lower() in ARCHIVE_EXTENSIONS:
        prepared = handle_archive(file_path)
        if prepared.get("status") != "success":
            raise ValueError(prepared.get("error", "压缩包处理失败"))
        return {
            "primary_file": prepared.get("primary_file"),
            "source_type": "archive",
            "primary_candidates": prepared.get("primary_candidates", []),
            "archive_file_count": prepared.get("archive_file_count", 0),
            "all_files": prepared.get("all_files", []),
        }

    if file_path_obj.is_dir():
        all_files = collect_files(file_path)
        if not all_files:
            raise ValueError("目录内没有可识别文件")
        return {
            "primary_file": identify_primary_file(all_files),
            "source_type": "directory",
            "primary_candidates": identify_primary_candidates(all_files),
            "archive_file_count": len(all_files),
            "all_files": all_files,
        }

    return {
        "primary_file": file_path,
        "source_type": "single",
        "primary_candidates": [file_path],
        "archive_file_count": 1,
        "all_files": [file_path],
    }


def _form_from_extension(file_path: str) -> str:
    ext = Path(file_path).suffix.lower()
    if ext == '.xml':
        return "Parameter"
    if ext in ['.shp', '.geojson', '.kml', '.gml']:
        return "Vector"
    if ext in ['.tif', '.tiff', '.geotiff', '.img', '.asc', '.vrt']:
        return "Raster"
    if ext in ['.csv', '.xlsx', '.xls']:
        return "Table"
    if ext in ['.nc', '.h5', '.hdf', '.hdf5']:
        return "Timeseries"
    return "Unknown"


def infer_source_forms(candidate_files: List[str]) -> List[str]:
    forms: List[str] = []
    for candidate in candidate_files:
        form = _form_from_extension(candidate)
        if form != "Unknown" and form not in forms:
            forms.append(form)
    return forms


def _extract_years_from_text(text: str) -> List[int]:
    years: List[int] = []
    for token in re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", text or ""):
        try:
            value = int(token)
            if value not in years:
                years.append(value)
        except Exception:
            continue
    return years


def infer_temporal_from_candidates(candidate_files: List[str]) -> Dict[str, Any]:
    years: List[int] = []
    for file_path in candidate_files:
        name = Path(file_path).stem
        for year in _extract_years_from_text(name):
            if year not in years:
                years.append(year)

    years = sorted(years)
    has_time = len(years) >= 2

    frequency = "unknown"
    if len(years) >= 2:
        intervals = [years[idx + 1] - years[idx] for idx in range(len(years) - 1)]
        if intervals and len(set(intervals)) == 1:
            frequency = f"{intervals[0]}-year"
        else:
            frequency = "irregular"

    return {
        "Has_time": has_time,
        "Years": years,
        "Start_time": years[0] if years else None,
        "End_time": years[-1] if years else None,
        "Frequency_hint": frequency,
        "Confidence": 0.85 if has_time else (0.4 if years else 0.2),
    }


def _list_dataset_sources(file_path: str) -> Dict[str, Any]:
    resolved = resolve_primary_file(file_path)
    all_files = resolved.get("all_files", []) or []

    # 对单文件兜底
    if not all_files:
        target = resolved.get("primary_file") or file_path
        all_files = [target]

    source_files = [
        f for f in all_files
        if Path(f).suffix.lower() in [
            '.xml', '.shp', '.geojson', '.kml', '.gml', '.tif', '.tiff', '.geotiff', '.img', '.asc', '.vrt',
            '.csv', '.xlsx', '.xls', '.json', '.nc', '.h5', '.hdf', '.hdf5'
        ]
    ]

    shapefile_sidecar_exts = {'.dbf', '.shx', '.prj', '.cpg', '.sbn', '.sbx', '.qix'}
    by_stem: Dict[str, Dict[str, Any]] = {}
    entries: List[Dict[str, Any]] = []

    for file_item in source_files:
        ext = Path(file_item).suffix.lower()
        stem = str(Path(file_item).with_suffix(''))
        if ext == '.shp' or ext in shapefile_sidecar_exts:
            group = by_stem.setdefault(stem, {"shp": None, "sidecars": []})
            if ext == '.shp':
                group["shp"] = file_item
            else:
                group["sidecars"].append(file_item)

    grouped_shp_paths: Set[str] = set()
    for stem, group in by_stem.items():
        if group.get("shp"):
            shp_path = group["shp"]
            grouped_shp_paths.add(shp_path)
            entries.append({
                "file_path": shp_path,
                "sidecar_files": sorted(group.get("sidecars", [])),
                "form": "Vector",
            })

    for file_item in source_files:
        ext = Path(file_item).suffix.lower()
        if ext in shapefile_sidecar_exts:
            continue
        if file_item in grouped_shp_paths:
            continue
        entries.append({
            "file_path": file_item,
            "sidecar_files": [],
            "form": _form_from_extension(file_item),
        })

    entries = sorted(entries, key=lambda item: item.get("file_path", ""))
    return {
        "source_type": resolved.get("source_type"),
        "primary_file": resolved.get("primary_file"),
        "primary_candidates": resolved.get("primary_candidates", []),
        "archive_file_count": resolved.get("archive_file_count", len(all_files)),
        "all_files": all_files,
        "source_entries": entries,
    }


def _analyze_source_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    file_path = entry.get("file_path")
    if not file_path:
        return {"status": "error", "error": "source missing file_path"}

    form = entry.get("form") or _form_from_extension(file_path)
    result: Dict[str, Any]

    if form == "Raster":
        result = tool_analyze_raster.invoke({"file_path": file_path})
    elif form == "Vector":
        result = tool_analyze_vector.invoke({"file_path": file_path})
    elif form == "Table":
        result = tool_analyze_table.invoke({"file_path": file_path})
    elif form == "Timeseries":
        result = tool_analyze_timeseries.invoke({"file_path": file_path})
    elif form == "Parameter":
        result = tool_analyze_parameter.invoke({"file_path": file_path})
    else:
        result = {"status": "success", "data": {}}

    data = result.get("data", {}) if isinstance(result, dict) else {}
    temporal = infer_temporal_from_candidates([file_path])

    if isinstance(data, dict) and data.get("Has_time") is True:
        temporal["Has_time"] = True
        temporal["Confidence"] = max(temporal.get("Confidence", 0.2), 0.9)

    useful_fields: Dict[str, Any] = {}
    if form == "Raster":
        useful_fields = {
            "Statistics": data.get("Statistics"),
            "Band_count": data.get("Band_count"),
            "Nodata_Value": data.get("Nodata_Value"),
            "Data_Type": data.get("Data_Type"),
        }
    elif form == "Vector":
        useful_fields = {
            "Geometry_type": data.get("Geometry_type"),
            "Attributes": data.get("Attributes"),
        }
    elif form == "Table":
        useful_fields = {
            "Row_count": data.get("Row_count"),
            "Columns": data.get("Columns"),
            "Dtypes": data.get("Dtypes"),
        }
    elif form == "Timeseries":
        useful_fields = {
            "Dimensions": data.get("Dimensions"),
            "Variables": data.get("Variables"),
            "Has_time": data.get("Has_time"),
        }
    elif form == "Parameter":
        useful_fields = {
            "Value_type": data.get("Value_type"),
            "Unit": data.get("Unit"),
        }

    useful_fields = {
        key: value
        for key, value in useful_fields.items()
        if value not in [None, [], {}]
    }

    return {
        "status": "success",
        "file_path": file_path,
        "form": form,
        "sidecar_files": entry.get("sidecar_files", []),
        "spatial": data.get("Spatial"),
        "temporal": temporal,
        "resolution": data.get("Resolution"),
        "quality": data.get("Quality"),
        **useful_fields,
    }


def analyze_dataset(file_path: str) -> Dict[str, Any]:
    try:
        listing = _list_dataset_sources(file_path)
        sources = listing.get("source_entries", [])
        if not sources:
            return {
                "status": "error",
                "error": "未发现可分析的数据源"
            }

        analyzed_sources: List[Dict[str, Any]] = []
        source_forms: List[str] = []
        all_temporal_files: List[str] = []
        for source in sources:
            analyzed = _analyze_source_entry(source)
            if analyzed.get("status") == "success":
                cleaned_source = {
                    key: value
                    for key, value in analyzed.items()
                    if key != "status" and value not in [None, [], {}]
                }
                analyzed_sources.append(cleaned_source)
                form = cleaned_source.get("form")
                if form and form not in source_forms:
                    source_forms.append(form)
                all_temporal_files.append(cleaned_source.get("file_path", ""))

        temporal_summary = infer_temporal_from_candidates(all_temporal_files)

        all_years: Set[int] = set(temporal_summary.get("Years", []))
        for source in analyzed_sources:
            source_temporal = source.get("temporal", {}) or {}
            for year in source_temporal.get("Years", []) or []:
                try:
                    all_years.add(int(year))
                except Exception:
                    continue
        merged_years = sorted(list(all_years))

        temporal_summary["Years"] = merged_years
        temporal_summary["Start_time"] = merged_years[0] if merged_years else None
        temporal_summary["End_time"] = merged_years[-1] if merged_years else None
        temporal_summary["Has_time"] = temporal_summary.get("Has_time", False) or len(merged_years) >= 2

        first_source = analyzed_sources[0] if analyzed_sources else {}
        first_form = first_source.get("form") if first_source else "Unknown"
        first_source_summary = {
            key: value
            for key, value in first_source.items()
            if key not in {
                "status",
                "file_path",
                "form",
                "sidecar_files",
                "spatial",
                "temporal",
                "resolution",
                "quality",
            }
            and value not in [None, [], {}]
        }

        profile_data = {
            "Form": first_form,
            "Source_forms": source_forms,
            "primary_file": listing.get("primary_file"),
            "Source_type": listing.get("source_type"),
            "data_sources": analyzed_sources,
            "Spatial": first_source.get("spatial"),
            "Resolution": first_source.get("resolution"),
            "Temporal": temporal_summary,
            "Quality": first_source.get("quality"),
            "Source_count": len(analyzed_sources),
            **first_source_summary,
        }

        profile_data = {
            key: value
            for key, value in profile_data.items()
            if value not in [None, [], {}]
        }

        return {
            "status": "success",
            "data": profile_data,
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


def validate_profile_consistency(profile: Dict[str, Any]) -> Dict[str, Any]:
    issues: List[str] = []
    warnings: List[str] = []

    data_sources = profile.get("data_sources", []) or []
    temporal = profile.get("Temporal", {}) or {}
    source_forms = profile.get("Source_forms", []) or []

    if profile.get("Source_count", 0) > 1 and len(data_sources) <= 1:
        issues.append("检测到多文件输入，但仅产生单一数据源画像，可能存在误判")

    if "Vector" in source_forms:
        for source in data_sources:
            if source.get("form") == "Vector":
                file_path = str(source.get("file_path", "")).lower()
                if file_path.endswith('.shp'):
                    sidecars = [Path(p).suffix.lower() for p in source.get("sidecar_files", [])]
                    missing = [ext for ext in ['.dbf', '.shx'] if ext not in sidecars]
                    if missing:
                        issues.append(f"Shapefile 侧车文件缺失: {file_path} 缺少 {','.join(missing)}")

    for source in data_sources:
        if source.get("form") == "Raster" and not source.get("resolution"):
            warnings.append(f"栅格缺少分辨率信息: {source.get('file_path')}")

    crs_tokens: List[str] = []
    spatial_candidates: List[Any] = []
    if data_sources:
        spatial_candidates.extend(source.get("spatial") for source in data_sources)
    else:
        spatial_candidates.append(profile.get("Spatial"))

    for spatial in spatial_candidates:
        crs = spatial.get("Crs") if isinstance(spatial, dict) else None
        if isinstance(crs, dict):
            token = crs.get("EPSG") or crs.get("Name")
            if token and str(token) not in crs_tokens:
                crs_tokens.append(str(token))

    if len(crs_tokens) > 1:
        warnings.append("检测到数据源存在混合CRS，可能影响空间叠置分析")

    years = temporal.get("Years", []) or []
    has_time = bool(temporal.get("Has_time"))
    if len(years) >= 2 and not has_time:
        issues.append("检测到多个年份文件，但 Temporal.Has_time 为 false")
    if has_time and len(years) < 2:
        warnings.append("Temporal.Has_time 为 true，但年份点不足，建议补充时间元数据")

    validation_score = 1.0
    if issues:
        validation_score -= min(0.7, len(issues) * 0.2)
    if warnings:
        validation_score -= min(0.3, len(warnings) * 0.05)
    validation_score = max(0.0, round(validation_score, 2))

    return {
        "status": "healthy" if not issues else "warning",
        "score": validation_score,
        "issues": issues,
        "warnings": warnings,
        "requires_review": bool(issues),
    }


@tool
def tool_analyze_dataset(file_path: str) -> Dict[str, Any]:
    """多源数据集扫描：识别并分析一个输入中的多个数据源（而非单 primary_file）"""
    return analyze_dataset(file_path)


@tool
def tool_validate_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    """二次校验：对结构化数据画像进行合理性验证"""
    try:
        return {
            "status": "success",
            "data": validate_profile_consistency(profile or {}),
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


# ============================================================================
# 工具 1: 初步检测工具
# ============================================================================

@tool
def tool_detect_format(file_path: str) -> Dict[str, Any]:
    """
    初步检测文件格式，依据扩展名和内容启发式判断
    - Raster: 栅格/影像数据（网格结构，通常有lat/lon维度）
    - Vector: 矢量地理数据（点、线、面几何，包含坐标）
    - Table: 纯表格数据（无地理参考）
    - Timeseries: 时间序列数据（强调时间维度）
    - Parameter: 配置参数文件
    Args:
        file_path: 文件路径
    Returns:
        dict: 包含检测结果的字典，格式为 {status, form, confidence}
    """
    try:
        resolved = resolve_primary_file(file_path)
        target_file = resolved.get("primary_file") or file_path
        primary_candidates = resolved.get("primary_candidates", [target_file])
        source_forms = infer_source_forms(primary_candidates)
        ext = Path(target_file).suffix.lower()

        base_meta = {
            "Source_type": resolved.get("source_type"),
            "Source_forms": source_forms,
        }
        
        # 1. 基于扩展名的快速判断
        if ext == '.xml':
            result = {
                "status": "success",
                "Form": "Parameter",
                "Confidence": 0.95,
            }
            result.update(base_meta)
            return result
        
        if ext in ['.shp', '.geojson', '.kml', '.gml']:
            result = {
                "status": "success",
                "Form": "Vector",
                "Confidence": 0.9,
            }
            result.update(base_meta)
            return result
        
        if ext in ['.tif', '.tiff', '.geotiff', '.img', '.asc', '.vrt']:
            result = {
                "status": "success",
                "Form": "Raster",
                "Confidence": 0.9,
            }
            result.update(base_meta)
            return result
        
        # 2. 需要内容检查的格式
        if ext == '.csv':
            result = detect_csv(target_file)
            result.update(base_meta)
            return result
        
        if ext == '.json':
            result = detect_json(target_file)
            result.update(base_meta)
            return result
        
        if ext == '.nc':
            result = detect_netcdf(target_file)
            result.update(base_meta)
            return result
        
        if ext in ['.h5', '.hdf', '.hdf5']:
            result = detect_hdf5(target_file)
            result.update(base_meta)
            return result
        
        result = {
            "status": "success",
            "Form": "Unknown",
            "Confidence": 0.3,
        }
        result.update(base_meta)
        return result
        
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }

def detect_csv(file_path: str) -> Dict[str, Any]:
    """
    判断CSV文件类型（表格/矢量/时间序列）
    Args:
        file_path: CSV文件路径
    Returns:
        dict: 检测结果
    """
    try:
        df = pd.read_csv(file_path, nrows=5)
        cols = [c.lower() for c in df.columns]
        
        has_lon = any(c in cols for c in ["lon", "longitude", "x", "经度"])
        has_lat = any(c in cols for c in ["lat", "latitude", "y", "纬度"])
        has_time = any("time" in c or "date" in c for c in cols)
        
        if has_lon and has_lat:
            return {
                "status": "success",
                "Form": "Vector",
                "Confidence": 0.9
            }
        
        if has_time:
            return {
                "status": "success",
                "Form": "Timeseries",
                "Confidence": 0.8
            }
        
        return {
            "status": "success",
            "Form": "Table",
            "Confidence": 0.85
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }

def detect_json(file_path: str) -> Dict[str, Any]:
    """
    判断JSON文件类型（表格/矢量）
    Args:
        file_path: JSON文件路径
    Returns:
        dict: 检测结果
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if isinstance(data, dict) and data.get("type") in ["FeatureCollection", "Feature"]:
            return {
                "status": "success",
                "Form": "Vector",
                "Confidence": 0.95
            }
        
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return {
                "status": "success",
                "Form": "Table",
                "Confidence": 0.85
            }
        
        return {
            "status": "success",
            "Form": "Unknown",
            "Confidence": 0.4
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }

def detect_netcdf(file_path: str) -> Dict[str, Any]:
    """
    判断NetCDF文件类型（栅格/时间序列）
    Args:
        file_path: NetCDF文件路径
    Returns:
        dict: 检测结果
    """
    try:
        ds = xr.open_dataset(file_path)
        dims = set(ds.dims.keys())
        
        if {"lat", "lon"}.issubset(dims):
            ds.close()
            return {
                "status": "success",
                "Form": "Raster",
                "Confidence": 0.9
            }
        
        if "time" in dims:
            ds.close()
            return {
                "status": "success",
                "Form": "Timeseries",
                "Confidence": 0.9
            }
        
        ds.close()
        return {
            "status": "success",
            "Form": "Unknown",
            "Confidence": 0.5
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }

def detect_hdf5(file_path: str) -> Dict[str, Any]:
    """
    判断HDF5文件类型（栅格/时间序列）
    Args:
        file_path: HDF5文件路径
    Returns:
        dict: 检测结果
    """
    try:
        with h5py.File(file_path, 'r') as f:
            keys = list(f.keys())
        
        if any("lat" in k.lower() or "lon" in k.lower() for k in keys):
            return {
                "status": "success",
                "Form": "Raster",
                "Confidence": 0.85
            }
        
        return {
            "status": "success",
            "Form": "Timeseries",
            "Confidence": 0.7
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }

# ============================================================================
# 工具2-6: 专项分析工具
# ============================================================================

@tool
def tool_analyze_raster(file_path: str) -> Dict[str, Any]:
    """
    详细分析栅格类型的数据
    Args:
        file_path: 文件路径
    Returns:
        status: "success" | "error",
        data: {
            Spatial: {
                Crs: "坐标参考系",
                Extent: {min_x: 最小X, max_x: 最大X, min_y: 最小Y, max_y: 最大Y, unit: 单位, label_x: "Easting (X)"|"Longitude", label_y: "Northing (Y)"|"Latitude"}
            },
            Resolution: {x: 像素大小X, y: 像素大小Y},
            Statistics: {min: 最小值, max: 最大值, mean: 平均值, std: 标准差},
            Band_count: 波段数,
            Nodata: "无效值",
            Quality: {问题列表，空几何比例},
        }
    """
    try:
        resolved = resolve_primary_file(file_path)
        target_file = resolved.get("primary_file") or file_path
        temporal_info = infer_temporal_from_candidates([target_file])
        with rasterio.open(target_file) as src:
            crs_info = parse_wkt_to_dict(src.crs.to_wkt())
            
            # 只读取第一个波段，masked=True 会自动屏蔽 nodata
            band1 = src.read(1, masked=True)  # shape = [height, width]

            # 统计有效像元
            valid_mask = ~band1.mask            # True 表示有效像元
            valid_count = np.sum(valid_mask)
            total_count = band1.size            # 只计算该波段的像元数

            # 质量检测
            q_issues = []
            nodata_ratio = (total_count - valid_count) / total_count
            
            if nodata_ratio > 0.9:
                q_issues.append("mostly_empty or all_nodata")
            
            if valid_count > 0:
                valid_pixels = band1.compressed()  # 有效像元值
                g_min = float(valid_pixels.min())
                g_max = float(valid_pixels.max())
                std_val = float(valid_pixels.std())
                mean_val = float(valid_pixels.mean())
                # 如果最大值超过平均值 10 个标准差，可能存在未处理的离群点
                if std_val > 0 and (float(valid_pixels.max()) > mean_val + 10 * std_val):
                    q_issues.append("extreme_outliers_detected")

                stats = {
                    "min": g_min,
                    "max": g_max,
                    "mean": mean_val,
                    "std":  std_val
                }
            else:
                stats = {"min": 0, "max": 0, "mean": 0, "std": 0}

            return {
                "status": "success",
                "data": {
                    "Spatial": {
                        "Crs": crs_info,
                        "Extent": {
                            "min_x": src.bounds.left,
                            "max_x": src.bounds.right,
                            "min_y": src.bounds.bottom,
                            "max_y": src.bounds.top,
                            "unit": crs_info.get("Unit", "unknown"),
                            "label_x": "Easting (X)" if crs_info.get("Is_Projected") else "Longitude",
                            "label_y": "Northing (Y)" if crs_info.get("Is_Projected") else "Latitude"
                        }
                    },
                    "Temporal": temporal_info,
                    "Resolution": {"x": abs(src.res[0]), "y": abs(src.res[1])},
                    "Statistics": stats,
                    "Band_count": src.count,
                    "Nodata_Value": src.nodata,
                    "Data_Type": src.dtypes[0],
                    "Source": {
                        "Source_type": resolved.get("source_type"),
                        "Resolved_primary_file": target_file,
                        "Primary_candidates": resolved.get("primary_candidates", []),
                        "Archive_file_count": resolved.get("archive_file_count", 1),
                    },
                    "Quality": generate_quality_report(q_issues, nodata_ratio),
                }
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@tool
def tool_analyze_vector(file_path: str) -> Dict[str, Any]:
    """
    详细分析矢量类型的数据
    Args:
        file_path: 文件路径
    Returns:
        status: "success" | "error",
        data: {
            Spatial: {
                Crs: "坐标参考系",
                Extent: [minX, minY, maxX, maxY]
            },
            Geometry_type: "几何类型",
            Feature_count: 要素数量,
            Quality: {问题列表，空几何比例},
            Attributes: [{name: 属性名, type: 属性类型}]
        }
    """
    try:
        target_file = resolve_primary_file(file_path).get("primary_file") or file_path
        gdf = gpd.read_file(target_file)

        # 基础信息
        raw_wkt = gdf.crs.to_wkt() if gdf.crs else ""
        crs_info = parse_wkt_to_dict(raw_wkt)
        bounds = gdf.total_bounds.tolist()

        q_issues = []
        # 几何有效性检测
        invalid_mask = ~gdf.is_valid
        invalid_count = int(invalid_mask.sum())
        if invalid_count > 0:
            q_issues.append(f"invalid_geometry_found_{invalid_count}_features")

        # 空几何检测
        empty_mask = gdf.is_empty
        empty_count = int(empty_mask.sum())
        if empty_count > 0:
            q_issues.append(f"empty_geometry_found_{empty_count}_features")

        # 坐标系缺失风险
        raw_wkt = gdf.crs.to_wkt() if gdf.crs else ""
        if not raw_wkt:
            q_issues.append("missing_crs_definition")

        # 属性完整性检测
        null_cols = [col for col in gdf.columns if gdf[col].isnull().all() and col != 'geometry']
        if null_cols:
            q_issues.append(f"empty_attribute_columns_{len(null_cols)}")

        # 属性统计摘要
        # 提取数值型列的描述统计
        desc = gdf.describe().to_dict()

        detailed_attributes = []
        for col in gdf.columns:
            if col == 'geometry': continue
            
            attr_info = {
                "name": col,
                "type": str(gdf[col].dtype),
                "null_count": int(gdf[col].isna().sum()),
                "unique_count": int(gdf[col].nunique())
            }
            
            # 如果是数值列，把 summary 合并进去
            if col in desc:
                attr_info["stats"] = {
                    "min": desc[col]["min"],
                    "max": desc[col]["max"],
                    "mean": desc[col]["mean"]
                }
            
            detailed_attributes.append(attr_info)
        
        geom_type = "Unknown"
        if not gdf.empty:
            g_type = gdf.geom_type.mode()[0]
            if 'Point' in g_type: geom_type = 'Point'
            elif 'Line' in g_type: geom_type = 'Line'
            elif 'Polygon' in g_type: geom_type = 'Polygon'
        
        return {
            "status": "success",
            "data": {
                "Spatial": {
                    "Crs": crs_info,
                    "Extent": {
                        "min_x": bounds[0],
                        "max_x": bounds[2],
                        "min_y": bounds[1],
                        "max_y": bounds[3],
                        "unit": crs_info["Unit"],
                        "label_x": "Easting (X)" if crs_info["Is_Projected"] else "Longitude",
                        "label_y": "Northing (Y)" if crs_info["Is_Projected"] else "Latitude"
                    }
                },
                "Geometry_type": {
                    "Type": geom_type,
                    "Feature_count": len(gdf),
                },
                "Quality": generate_quality_report(q_issues, empty_count/max(len(gdf),1)),
                "Attributes": detailed_attributes
            }
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}

@tool
def tool_analyze_table(file_path: str) -> Dict[str, Any]:
    """
    详细分析表格类型的数据
    Args:
        file_path: 文件路径
    Returns:
        status: "success" | "error",
        data: {
            Row_count: 行数,
            Columns: [列名],
            Dtypes: {列名: 数据类型},
            Sample_rows: [样本行]
        }
    """
    try:
        target_file = resolve_primary_file(file_path).get("primary_file") or file_path
        if target_file.endswith('.csv'):
            df = pd.read_csv(target_file, nrows=100)
        else:
            df = pd.read_excel(target_file, nrows=100)
        
        return {
            "status": "success",
            "data": {
                "Row_count": len(df),
                "Columns": list(df.columns),
                "Dtypes": df.dtypes.astype(str).to_dict(),
                "Sample_rows": df.head(3).to_dict(orient='records')
            }
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}

@tool
def tool_analyze_timeseries(file_path: str) -> Dict[str, Any]:
    """
    详细分析时间序列类型的数据
    Args:
        file_path: 文件路径
    Returns:
        status: "success" | "error",
        data: {
            Dimensions: {维度名: 大小},
            Variables: [变量名],
            Has_time: 是否包含时间维度
        }
    """
    try:
        target_file = resolve_primary_file(file_path).get("primary_file") or file_path
        if target_file.endswith('.nc'):
            ds = xr.open_dataset(target_file)
            return {
                "status": "success",
                "data": {
                    "Dimensions": dict(ds.dims),
                    "Variables": list(ds.data_vars),
                    "Has_time": "time" in ds.dims
                }
            }
        else:
            df = pd.read_csv(target_file, nrows=100)
            return {
                "status": "success",
                "data": {
                    "Columns": list(df.columns),
                    "Row_count": len(df)
                }
            }
    except Exception as e:
        return {"status": "error", "error": str(e)}

@tool
def tool_analyze_parameter(file_path: str) -> Dict[str, Any]:
    """
    详细分析参数类型的数据
    Args:
        file_path: 文件路径
    Returns:
        status: "success" | "error",
        data: {
            Value_type: "int" | "float" | "string" | "boolean",
            Unit: "单位"
        }
    """
    try:
        target_file = resolve_primary_file(file_path).get("primary_file") or file_path
        # 读取文件内容
        with open(target_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 使用正则表达式匹配XDO节点
        xdo_pattern = r'<XDO\s+([^\/>]+?)\s*\/>'
        xdo_match = re.search(xdo_pattern, content, re.IGNORECASE)
        
        if not xdo_match:
            return {
                "status": "error",
                "error": "未找到XDO节点"
            }
        
        # 提取属性文本
        attr_text = xdo_match.group(1)
        
        # 解析属性
        attr_pattern = r'(\w+)\s*=\s*"([^"]*)"'
        attrs = {}
        for match in re.finditer(attr_pattern, attr_text):
            attr_name = match.group(1)
            attr_value = match.group(2)
            attrs[attr_name] = attr_value
        
        # 规范化 kernelType
        kernel_type = attrs.get('kernelType', '')
        value_type = normalize_kernel_type(kernel_type)
        
        return {
            "status": "success",
            "data": {
                "Value_type": value_type,
                "Unit": attrs.get('unit') or 'Unknown'
            }
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}

def normalize_kernel_type(kernel_type: Optional[str]) -> str:
    """
    规范化参数类型
    @param kernel_type: 原始类型字符串
    @returns: 规范化后的类型 ('int' | 'float' | 'string' | 'boolean')
    """
    if not kernel_type:
        return 'string'
    
    kernel_type_lower = kernel_type.lower()
    
    # 整数类型
    if kernel_type_lower in ['int', 'integer']:
        return 'int'
    
    # 浮点类型
    if kernel_type_lower in ['float', 'double', 'number']:
        return 'float'
    
    # 布尔类型
    if kernel_type_lower in ['bool', 'boolean']:
        return 'boolean'
    
    # 默认字符串类型
    return 'string'

def parse_wkt_to_dict(wkt_str: str) -> Dict[str, Any]:
    """
    使用 pyproj 优化解析 WKT 字符串
    """
    if not wkt_str or len(wkt_str) < 10:
        return {"Name": "Unknown", "Wkt": wkt_str}
    
    try:
        # 将 WKT 转换为 CRS 对象
        crs_obj = CRS.from_wkt(wkt_str)
        epsg_code = crs_obj.to_epsg()
        is_engineering = bool(getattr(crs_obj, "is_engineering", False))
        is_projected_like = bool(crs_obj.is_projected or is_engineering)
        
        # 提取单位：优先读取轴单位，避免 LOCAL_CS / engineering CRS 被误判
        unit = "Unknown"
        if crs_obj.axis_info:
            unit = getattr(crs_obj.axis_info[0], "unit_name", None) or "Unknown"
        elif crs_obj.is_geographic:
            unit = "degree"

        # 提取投影信息
        proj_name = "Unknown"
        if crs_obj.coordinate_operation and hasattr(crs_obj.coordinate_operation, 'method_name'):
            proj_name = crs_obj.coordinate_operation.method_name
        elif is_engineering:
            proj_name = "Engineering"
        elif crs_obj.is_projected:
            proj_name = "Projected"
        elif crs_obj.is_geographic:
            proj_name = "Geographic"
        else:
            proj_name = "Unknown"

        # 提取中央经线
        cm = "N/A"
        if crs_obj.coordinate_operation and hasattr(crs_obj.coordinate_operation, 'params'):
            # 遍历投影参数寻找中央经线
            for param in crs_obj.coordinate_operation.params:
                if "central_meridian" in param.name.lower():
                    cm = f"{param.value}°E"
                    break

        return {
            "Name": crs_obj.name,           # 'CGCS2000_3_Degree_GK_CM_113E'
            "EPSG": f"EPSG:{epsg_code}" if epsg_code else "Unknown",
            "Datum": crs_obj.datum.name if crs_obj.datum else "Unknown",
            "Projection": proj_name,
            "Central_meridian": cm,
            "Unit": unit,
            "Is_Projected": is_projected_like,
            "Is_Engineering": is_engineering,
            "Wkt": wkt_str
        }
    except Exception as e:
        # 兜底：如果解析失败，返回基础信息
        return {"Name": "Parse Error", "Error": str(e), "Wkt": wkt_str}

def generate_quality_report(issues: List[str], nodata_ratio: float = 0.0) -> Dict[str, Any]:
    """统一质量报告结构"""
    return {
        "status": "warning" if issues else "healthy",
        "issues": issues,
        "nodata_percentage": f"{nodata_ratio:.2%}",
        "requires_repair": len(issues) > 0
    }

# ============================================================================
# 工具注册（供 LangGraph 调用）
# ============================================================================

tools = [
    tool_prepare_file,
    tool_detect_format,
    tool_analyze_dataset,
    tool_validate_profile,
    tool_analyze_raster,
    tool_analyze_vector,
    tool_analyze_table,
    tool_analyze_timeseries,
    tool_analyze_parameter
]

TOOLS_BY_NAME = {tool.name: tool for tool in tools}