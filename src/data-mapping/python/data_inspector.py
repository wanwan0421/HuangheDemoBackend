import sys
import json
import os
import pandas as pd
import xarray as xr
import h5py
import numpy as np
import rasterio
import geopandas as gpd

# ==========================================
# Part1：类型判断
# ==========================================

def inspect_json_detect(path):
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # GeoJSON 判定
    if isinstance(data, dict) and data.get("type") in ["FeatureCollection", "Feature"]:
        return {
            "detected_form": "Vector",
            "confidence": 0.95,
            "details": {"geometry": "GeoJSON"}
        }

    # Table-like JSON
    if isinstance(data, list) and isinstance(data[0], dict):
        return {
            "detected_form": "Table",
            "confidence": 0.85,
            "details": {"columns": list(data[0].keys())}
        }

    return {"detected_form": "Unknown", "confidence": 0.3}

def inspect_csv_detect(path):
    df = pd.read_csv(path, nrows=5)
    cols = [c.lower() for c in df.columns]

    has_lon = any(c in cols for c in ["lon", "longitude", "x", "经度"])
    has_lat = any(c in cols for c in ["lat", "latitude", "y", "纬度"])
    has_time = any("time" in c or "date" in c for c in cols)

    if has_lon and has_lat:
        return {
            "detected_form": "Vector",
            "confidence": 0.9,
            "details": {"geometry": "Point", "has_time": has_time}
        }

    if has_time:
        return {
            "detected_form": "Timeseries",
            "confidence": 0.8,
            "details": {"has_time": True}
        }

    return {
        "detected_form": "Table",
        "confidence": 0.85,
        "details": {"columns": cols}
    }

def inspect_netcdf_detect(path):
    ds = xr.open_dataset(path)
    dims = set(ds.dims.keys())

    if {"lat", "lon"}.issubset(dims):
        return {
            "detected_form": "Raster",
            "confidence": 0.9,
            "details": {"dimensions": list(dims)}
        }

    if "time" in dims:
        return {
            "detected_form": "Timeseries",
            "confidence": 0.9,
            "details": {"dimensions": list(dims)}
        }

    return {"detected_form": "Unknown", "confidence": 0.4}

def inspect_hdf_detect(path):
    with h5py.File(path, 'r') as f:
        keys = list(f.keys())

    if any("lat" in k.lower() or "lon" in k.lower() for k in keys):
        return {
            "detected_form": "Raster",
            "confidence": 0.85,
            "details": {"datasets": keys}
        }

    return {
        "detected_form": "Timeseries",
        "confidence": 0.7,
        "details": {"datasets": keys}
    }

# ==========================================
# Part2：元数据提取
# ==========================================

def json_serial(obj):
    if isinstance(obj, (np.interger, int)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Type {type(obj)} not serializable")

def extract_raster(path):
    try:
        with rasterio.open(path) as src:
            # value, range（采样计算）
            min_val, max_val = 0, 0
            try:
                # 只读取概览或小块以提高速度
                arr = src.read(1, out_shape=(1, int(src.height/10), int(src.width/10)))
                # 排除nodata
                if src.nodata is not None:
                    arr = arr[arr != src.nodata]
                if arr.size > 0:
                    min_val, max_val = float(np.min(arr)), float(np.max(arr))
            except Exception:
                pass

            return {
                "resolution": {"x": abs(src.res[0]), "y": abs(src.res[1])},
                "unit": src.units[0] if src.units and src.units[0] else "Unknown",
                "value_range": [min_val,  max_val],
                "nodata": src.nodata if src.nodata is not None else -9999,
                "band_count": src.count
            }
    except Exception as e:
        return {"error": str(e)}

def extract_vector(path):
    try:
        gdf = gpd.read_file(path)
        
        # 映射Pandas类型到Node定义的类型
        type_map = {
            'int64': 'Int', 'float64': 'Float', 'object': 'String', 
            'bool': 'Boolean', 'datetime64[ns]': 'Date'
        }
        
        attrs = []
        for col_name, dtype in gdf.dtypes.items():
            if col_name != 'geometry':
                ts_type = type_map.get(str(dtype), 'String')
                attrs.append({"name": col_name, "type": ts_type})

        # 拓扑检查 (非常耗时，仅检查前100个要素)
        is_valid = True
        if len(gdf) > 0:
            is_valid = gdf.geometry.iloc[:100].is_valid.all()

        geom_type = "Unknown"
        if not gdf.empty:
            g_type = gdf.geom_type.mode()[0] # 取众数
            if 'Point' in g_type: geom_type = 'Point'
            elif 'Line' in g_type: geom_type = 'Line'
            elif 'Polygon' in g_type: geom_type = 'Polygon'

        return {
            "geometry_type": geom_type,
            "topology_valid": bool(is_valid),
            "attributes": attrs
        }
    except Exception as e:
        return {"error": str(e)}
    
def extract_table(path):
    import pandas as pd
    try:
        df = pd.read_csv(path, nrows=100) if path.endswith('.csv') else pd.read_excel(path, nrows=100)
        
        # 猜测时间字段
        time_field = None
        for col in df.columns:
            if 'time' in col.lower() or 'date' in col.lower():
                time_field = col
                break
        
        # Primary Key 很难猜，通常留空或取第一列
        return {
            "primary_key": None, 
            "time_field": time_field
        }
    except Exception as e:
        return {"error": str(e)}

def extract_timeseries(path):
    import xarray as xr
    import pandas as pd
    try:
        # 尝试用 xarray (netcdf) 或 pandas (csv)
        time_step_val = 1
        time_step_unit = 'Hour'
        
        if path.endswith('.nc'):
            ds = xr.open_dataset(path)
            if 'time' in ds.coords:
                times = ds.coords['time'].values
                if len(times) > 1:
                    diff = pd.to_timedelta(np.diff(times[:2])[0])
                    # 简单转换 diff 到 unit
                    if diff.days > 28: time_step_unit = 'Month'
                    elif diff.days >= 1: time_step_unit = 'Day'
                    elif diff.seconds >= 3600: time_step_unit = 'Hour'
                    else: time_step_unit = 'Second'
                    # 这里简化处理 value，实际可能需要更复杂计算
                    time_step_val = 1 
        
        elif path.endswith('.csv'):
             # CSV 时序分析逻辑...
             pass

        return {
            "time_step": {
                "value": time_step_val,
                "unit": time_step_unit
            },
            "aggregation": "Instant" # 默认为瞬时值
        }
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: python script.py <command> <filepath> [args]"})); sys.exit(1)
        
    command = sys.argv[1] # 'detect' or 'extract'
    file_path = sys.argv[2]
    
    result = {}
    
    # --- 模式 1: Detect (Form Inference) ---
    if command == "detect":
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".json": result = inspect_json_detect(file_path)
        elif ext == ".csv": result = inspect_csv_detect(file_path)
        elif ext == ".nc": result = inspect_netcdf_detect(file_path)
        elif ext == ".hdf": result = inspect_hdf_detect(file_path)
        else: result = {"detected_form": "Unknown", "confidence": 0.2}

    # --- 模式 2: Extract (Metadata Profiling) ---
    elif command == "extract":
        form_type = sys.argv[3] if len(sys.argv) > 3 else "Unknown"
        
        if form_type == "Raster": result = extract_raster(file_path)
        elif form_type == "Vector": result = extract_vector(file_path)
        elif form_type == "Table": result = extract_table(file_path)
        elif form_type == "Timeseries": result = extract_timeseries(file_path)
        else: result = {}

    print(json.dumps(result, default=json_serial))