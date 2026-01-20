import json
import os
from typing import Annotated, Dict, Any, List, Optional, TypedDict
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
from google import genai
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.messages import AnyMessage
import operator
from pyproj import CRS

# 初始化模型
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
client = genai.Client(api_key=GOOGLE_API_KEY )

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
        
        # 情况1：单个文件
        if file_path_obj.is_file():
            ext = file_path_obj.suffix.lower()
            
            # 压缩包格式
            if ext in ['.zip', '.tar', '.gz', '.rar']:
                return handle_archive(file_path)
            
            # 普通单文件
            return {
                "status": "success",
                "primary_file": str(file_path),
                "temp_dir": None,
                "file_type": "single",
            }
        
        # 情况2：目录
        if file_path_obj.is_dir():
            all_files = collect_files(file_path)
            primary = identify_primary_file(all_files)
            
            return {
                "status": "success",
                "primary_file": primary,
                "temp_dir": None,
                "file_type": "directory",
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
        primary = identify_primary_file(all_files)
        
        return {
            "status": "success",
            "primary_file": primary,
            "temp_dir": temp_dir,
            "file_type": "archive",
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
        '.shp',
        '.tif', '.tiff', '.geotiff',
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
        ext = Path(file_path).suffix.lower()
        
        # 1. 基于扩展名的快速判断
        if ext == '.xml':
            return {
                "status": "success",
                "Form": "Parameter",
                "Confidence": 0.95
            }
        
        if ext in ['.shp', '.geojson', '.kml', '.gml']:
            return {
                "status": "success",
                "Form": "Vector",
                "Confidence": 0.9
            }
        
        if ext in ['.tif', '.tiff', '.geotiff', '.img', '.asc', '.vrt']:
            return {
                "status": "success",
                "Form": "Raster",
                "Confidence": 0.9
            }
        
        # 2. 需要内容检查的格式
        if ext == '.csv':
            return detect_csv(file_path)
        
        if ext == '.json':
            return detect_json(file_path)
        
        if ext == '.nc':
            return detect_netcdf(file_path)
        
        if ext in ['.h5', '.hdf', '.hdf5']:
            return detect_hdf5(file_path)
        
        return {
            "status": "success",
            "Form": "Unknown",
            "Confidence": 0.3,
        }
        
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
        
        if isinstance(data, list) and isinstance(data[0], dict):
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
            Statistics: {min: 最小值, max: 最大值, mean: 平均值, std: 标准差, nodata_ratio: "无效值比例"},
            Value_range: [最小值, 最大值],
            Band_count: 波段数,
            Nodata: "无效值"
        }
    """
    try:
        with rasterio.open(file_path) as src:
            # 基础信息
            crs_info = parse_wkt_to_dict(src.crs.to_wkt())

            # 深度统计，计算真实值分布和空值占比（读取第一波段进行分析）
            ov_level = 0
            if src.width * src.height > 1000000: # 超过100万像素则抽样
                ov_level = 2 
            
            data = src.read(1, masked=True) # 使用 masked array 自动处理 nodata
            
            # 计算有效值
            valid_data = data.compressed() # 移除 mask(nodata) 后的扁平数组
            total_pixels = data.size
            valid_count = len(valid_data)
            nodata_ratio = (total_pixels - valid_count) / total_pixels if total_pixels > 0 else 0

            stats = {
                "min": float(valid_data.min()) if valid_count > 0 else 0,
                "max": float(valid_data.max()) if valid_count > 0 else 0,
                "mean": float(valid_data.mean()) if valid_count > 0 else 0,
                "std": float(valid_data.std()) if valid_count > 0 else 0,
                "nodata_ratio": f"{nodata_ratio:.2%}"
            }

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
                            "unit": crs_info["Unit"],
                            "label_x": "Easting (X)" if crs_info["Is_Projected"] else "Longitude",
                            "label_y": "Northing (Y)" if crs_info["Is_Projected"] else "Latitude"
                        }
                    },
                    "Resolution": {"x": abs(src.res[0]), "y": abs(src.res[1])},
                    "Statistics": stats,
                    "Value_range": [src.read().min().item(), src.read().max().item()],
                    "Band_count": src.count,
                    "Nodata": src.nodata
                }
            }
    except Exception as e:
        return {"status": "error", "error": str(e)}

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
            Attributes: [{name: 属性名, type: 属性类型}]
        }
    """
    try:
        gdf = gpd.read_file(file_path)

        # 基础信息
        raw_wkt = gdf.crs.to_wkt() if gdf.crs else ""
        crs_info = parse_wkt_to_dict(raw_wkt)
        bounds = gdf.total_bounds.tolist()

        # 几何质量检查
        is_all_valid = gdf.is_valid.all()
        invalid_count = (~gdf.is_valid).sum()

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
                    "Is_all_valid": bool(is_all_valid),
                    "Invalid_count": int(invalid_count)
                },
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
        if file_path.endswith('.csv'):
            df = pd.read_csv(file_path, nrows=100)
        else:
            df = pd.read_excel(file_path, nrows=100)
        
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
        if file_path.endswith('.nc'):
            ds = xr.open_dataset(file_path)
            return {
                "status": "success",
                "data": {
                    "Dimensions": dict(ds.dims),
                    "Variables": list(ds.data_vars),
                    "Has_time": "time" in ds.dims
                }
            }
        else:
            df = pd.read_csv(file_path, nrows=100)
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
        # 读取文件内容
        with open(file_path, 'r', encoding='utf-8') as f:
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

def parse_wkt_to_dict(wkt_str: str) -> Dict[str, str]:
    """
    使用 pyproj 优化解析 WKT 字符串
    """
    if not wkt_str or len(wkt_str) < 10:
        return {"Name": "Unknown", "Wkt": wkt_str}
    
    try:
        # 将 WKT 转换为 CRS 对象
        crs_obj = CRS.from_wkt(wkt_str)
        
        # 提取单位：如果是投影坐标系，优先获取线性单位(如 metre)
        unit = "Unknown"
        if crs_obj.is_projected:
            unit = crs_obj.axis_info[0].unit_name # 准确获取 'metre'
        else:
            unit = "degree"

        # 提取投影信息
        proj_name = "Geographic"
        if crs_obj.coordinate_operation and hasattr(crs_obj.coordinate_operation, 'method_name'):
            proj_name = crs_obj.coordinate_operation.method_name
        else:
            proj_name = "Projected"

        # 提取中央经线
        cm = "N/A"
        if crs_obj.is_projected:
            # 遍历投影参数寻找中央经线
            for param in crs_obj.coordinate_operation.params:
                if "central_meridian" in param.name.lower():
                    cm = f"{param.value}°E"
                    break

        return {
            "Name": crs_obj.name,           # 'CGCS2000_3_Degree_GK_CM_113E'
            "Datum": crs_obj.datum.name if crs_obj.datum else "Unknown",
            "Projection": proj_name,
            "Central_meridian": cm,
            "Unit": unit,                   # 现在会准确返回 'metre'
            "Is_Projected": crs_obj.is_projected,
            "Wkt": wkt_str
        }
    except Exception as e:
        # 兜底：如果解析失败，返回基础信息
        return {"Name": "Parse Error", "Error": str(e), "Wkt": wkt_str}

def build_spatial_info(raw_crs: str, bounds: list) -> Dict[str, Any]:
    """
    统一构建 Spatial 语义结构
    """
    spatial = {
        "Crs": parse_wkt_to_dict(raw_crs),
        "Extent": {
            "bbox": bounds,
            "axis": ["X", "Y"],
            "unit": "unknown",
            "crs_type": "unknown"
        }
    }

    if raw_crs:
        crs = CRS.from_wkt(raw_crs)

        spatial["Extent"]["crs_type"] = (
            "projected" if crs.is_projected else "geographic"
        )

        if crs.axis_info:
            spatial["Extent"]["unit"] = crs.axis_info[0].unit_name

    return spatial

# ============================================================================
# 工具注册（供 LangGraph 调用）
# ============================================================================

tools = [
    tool_prepare_file,
    tool_detect_format,
    tool_analyze_raster,
    tool_analyze_vector,
    tool_analyze_table,
    tool_analyze_timeseries,
    tool_analyze_parameter
]

TOOLS_BY_NAME = {tool.name: tool for tool in tools}
model_with_tools = data_scan_model.bind_tools(tools)