"""
地理数据格式转换工具
支持将 Shapefile、GeoTIFF 等格式转换为 Mapbox 可用格式
"""
import sys
import json
import os
import geopandas as gpd
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.io import MemoryFile
from shapely.geometry import box
import base64
from io import BytesIO
from PIL import Image
import numpy as np


def shapefile_to_geojson(shapefile_path, output_path=None):
    """
    将 Shapefile 转换为 GeoJSON 格式
    
    Args:
        shapefile_path: Shapefile 路径（.shp 文件）
        output_path: 输出 GeoJSON 路径（可选）
        
    Returns:
        dict: 包含 GeoJSON 数据和元信息
    """
    try:
        # 读取 Shapefile
        gdf = gpd.read_file(shapefile_path)
        
        # 转换为 WGS84 (EPSG:4326) 以兼容 Mapbox
        if gdf.crs and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)
        
        # 转换为 GeoJSON
        geojson_data = json.loads(gdf.to_json())
        
        # 如果指定了输出路径，保存文件
        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(geojson_data, f, ensure_ascii=False, indent=2)
        
        # 获取边界
        bounds = gdf.total_bounds  # [minx, miny, maxx, maxy]
        
        return {
            "success": True,
            "type": "vector",
            "format": "geojson",
            "data": geojson_data,
            "bounds": bounds.tolist(),
            "crs": "EPSG:4326",
            "feature_count": len(gdf),
            "geometry_type": gdf.geometry.type.unique().tolist(),
            "output_path": output_path
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "type": "vector"
        }


def geotiff_to_mapbox_info(tif_path):
    """
    读取 GeoTIFF 信息并返回边界、元数据
    用于在 Mapbox 上叠加显示栅格数据
    
    Args:
        tif_path: GeoTIFF 文件路径
        
    Returns:
        dict: 包含边界 GeoJSON、元数据和栅格信息
    """
    try:
        print(f"[DEBUG] 开始处理 GeoTIFF 文件: {tif_path}", file=sys.stderr, flush=True)
        
        with rasterio.open(tif_path) as src:
            print(f"[DEBUG] 已打开文件，开始读取元数据...", file=sys.stderr, flush=True)
            
            # 获取边界（转换为 WGS84）
            bounds = src.bounds
            
            # 转换坐标系到 WGS84 如果不是
            if src.crs and src.crs.to_epsg() != 4326:
                print(f"[DEBUG] 坐标系转换: {src.crs} -> EPSG:4326", file=sys.stderr, flush=True)
                from rasterio.warp import transform_bounds
                bounds = transform_bounds(src.crs, 'EPSG:4326', *bounds)
            
            # 创建边界 GeoJSON
            print(f"[DEBUG] 创建边界 GeoJSON...", file=sys.stderr, flush=True)
            bbox_geom = box(bounds[0], bounds[1], bounds[2], bounds[3])
            bounds_geojson = {
                "type": "Feature",
                "geometry": json.loads(gpd.GeoSeries([bbox_geom]).to_json())['features'][0]['geometry'],
                "properties": {
                    "name": os.path.basename(tif_path),
                    "type": "raster_bounds"
                }
            }
            
            print(f"[DEBUG] GeoTIFF 处理完成，生成结果...", file=sys.stderr, flush=True)
            
            # 获取栅格元数据
            print(f"[DEBUG] 读取栅格元数据: {src.width}x{src.height}, {src.count}个波段", file=sys.stderr, flush=True)
            metadata = {
                "width": src.width,
                "height": src.height,
                "count": src.count,  # 波段数
                "dtype": str(src.dtypes[0]),
                "crs": str(src.crs) if src.crs else None,
                "transform": list(src.transform),
                "nodata": src.nodata,
                "bounds": list(bounds)
            }
            
            # 读取统计信息（第一个波段）
            print(f"[DEBUG] 计算波段统计信息...", file=sys.stderr, flush=True)
            band1 = src.read(1)
            stats = {
                "min": float(np.nanmin(band1)),
                "max": float(np.nanmax(band1)),
                "mean": float(np.nanmean(band1)),
                "std": float(np.nanstd(band1))
            }
            
            print(f"[DEBUG] GeoTIFF 处理完全完成！", file=sys.stderr, flush=True)
            
            return {
                "success": True,
                "type": "raster",
                "format": "geotiff",
                "bounds_geojson": bounds_geojson,
                "metadata": metadata,
                "statistics": stats,
                "file_path": tif_path
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "type": "raster"
        }


def geotiff_to_png_tile(tif_path, output_path=None, max_size=1024):
    """
    将 GeoTIFF 转换为 PNG，用于简单可视化
    
    Args:
        tif_path: GeoTIFF 文件路径
        output_path: 输出 PNG 路径（可选）
        max_size: 最大尺寸限制
        
    Returns:
        dict: 包含 PNG 数据（base64）或文件路径
    """
    try:
        with rasterio.open(tif_path) as src:
            # 读取第一个波段
            data = src.read(1)
            
            # 缩放到合理尺寸
            height, width = data.shape
            if max(height, width) > max_size:
                scale = max_size / max(height, width)
                new_height = int(height * scale)
                new_width = int(width * scale)
                
                from scipy.ndimage import zoom
                data = zoom(data, (new_height / height, new_width / width), order=1)
            
            # 归一化到 0-255
            data_min = np.nanmin(data)
            data_max = np.nanmax(data)
            
            if data_max > data_min:
                data_normalized = ((data - data_min) / (data_max - data_min) * 255).astype(np.uint8)
            else:
                data_normalized = np.zeros_like(data, dtype=np.uint8)
            
            # 转换为 PIL Image
            img = Image.fromarray(data_normalized, mode='L')
            
            # 保存或返回 base64
            if output_path:
                img.save(output_path)
                return {
                    "success": True,
                    "type": "raster",
                    "format": "png",
                    "output_path": output_path
                }
            else:
                # 返回 base64
                buffer = BytesIO()
                img.save(buffer, format='PNG')
                img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                
                return {
                    "success": True,
                    "type": "raster",
                    "format": "png",
                    "data": f"data:image/png;base64,{img_base64}"
                }
                
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "type": "raster"
        }


def convert_to_mapbox(file_path, output_dir=None):
    """
    自动检测文件类型并转换为 Mapbox 兼容格式
    
    Args:
        file_path: 输入文件路径
        output_dir: 输出目录（可选）
        
    Returns:
        dict: 转换结果
    """
    print(f"[DEBUG] 开始转换文件: {file_path}", file=sys.stderr, flush=True)
    
    ext = os.path.splitext(file_path)[1].lower()
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    
    print(f"[DEBUG] 文件扩展名: {ext}", file=sys.stderr, flush=True)
    
    # Shapefile
    if ext == '.shp':
        print(f"[DEBUG] 检测到 Shapefile, 正在转换为 GeoJSON...", file=sys.stderr, flush=True)
        output_path = None
        if output_dir:
            output_path = os.path.join(output_dir, f"{base_name}.geojson")
        return shapefile_to_geojson(file_path, output_path)
    
    # GeoJSON (直接读取并验证)
    elif ext in ['.geojson', '.json']:
        print(f"[DEBUG] 检测到 GeoJSON, 正在处理...", file=sys.stderr, flush=True)
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                geojson_data = json.load(f)
            
            if geojson_data.get('type') in ['FeatureCollection', 'Feature']:
                gdf = gpd.GeoDataFrame.from_features(geojson_data)
                bounds = gdf.total_bounds
                
                print(f"[DEBUG] GeoJSON 处理完成", file=sys.stderr, flush=True)
                
                return {
                    "success": True,
                    "type": "vector",
                    "format": "geojson",
                    "data": geojson_data,
                    "bounds": bounds.tolist(),
                    "feature_count": len(gdf)
                }
        except:
            pass
    
    # GeoTIFF / TIFF
    elif ext in ['.tif', '.tiff', '.geotiff']:
        print(f"[DEBUG] 检测到 GeoTIFF/TIFF, 正在处理...", file=sys.stderr, flush=True)
        result = geotiff_to_mapbox_info(file_path)
        return result
    
    # KML (需要转换)
    elif ext == '.kml':
        print(f"[DEBUG] 检测到 KML, 正在转换为 GeoJSON...", file=sys.stderr, flush=True)
        try:
            gdf = gpd.read_file(file_path)
            if gdf.crs and gdf.crs.to_epsg() != 4326:
                gdf = gdf.to_crs(epsg=4326)
            
            geojson_data = json.loads(gdf.to_json())
            output_path = None
            if output_dir:
                output_path = os.path.join(output_dir, f"{base_name}.geojson")
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(geojson_data, f, ensure_ascii=False, indent=2)
            
            print(f"[DEBUG] KML 转换完成", file=sys.stderr, flush=True)
            
            return {
                "success": True,
                "type": "vector",
                "format": "geojson",
                "data": geojson_data,
                "bounds": gdf.total_bounds.tolist(),
                "feature_count": len(gdf),
                "output_path": output_path
            }
        except Exception as e:
            print(f"[ERROR] KML 转换失败: {str(e)}", file=sys.stderr, flush=True)
            return {"success": False, "error": str(e), "type": "vector"}
    
    print(f"[ERROR] 不支持的文件格式: {ext}", file=sys.stderr, flush=True)
    return {
        "success": False,
        "error": f"Unsupported file format: {ext}",
        "supported_formats": [".shp", ".geojson", ".json", ".tif", ".tiff", ".kml"]
    }


if __name__ == "__main__":
    print(f"[DEBUG] 地理数据转换脚本启动", file=sys.stderr, flush=True)
    
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: python geo_converter.py <command> <file_path> [output_dir]"}))
        sys.exit(1)
    
    command = sys.argv[1]
    print(f"[DEBUG] 执行命令: {command}", file=sys.stderr, flush=True)
    
    if command == "convert":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "File path required"}))
            sys.exit(1)
        
        file_path = sys.argv[2]
        output_dir = sys.argv[3] if len(sys.argv) > 3 else None
        
        print(f"[DEBUG] 输入文件: {file_path}", file=sys.stderr, flush=True)
        if output_dir:
            print(f"[DEBUG] 输出目录: {output_dir}", file=sys.stderr, flush=True)
        
        result = convert_to_mapbox(file_path, output_dir)
        print(f"[DEBUG] 转换完成，即将输出结果...", file=sys.stderr, flush=True)
        print(json.dumps(result, ensure_ascii=False))
        print(f"[DEBUG] 脚本执行完毕", file=sys.stderr, flush=True)
    
    elif command == "shapefile_to_geojson":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Shapefile path required"}))
            sys.exit(1)
        
        file_path = sys.argv[2]
        output_path = sys.argv[3] if len(sys.argv) > 3 else None
        
        result = shapefile_to_geojson(file_path, output_path)
        print(json.dumps(result, ensure_ascii=False))
    
    elif command == "geotiff_info":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "GeoTIFF path required"}))
            sys.exit(1)
        
        file_path = sys.argv[2]
        result = geotiff_to_mapbox_info(file_path)
        print(json.dumps(result, ensure_ascii=False))
    
    else:
        print(json.dumps({"error": f"Unknown command: {command}"}))
        sys.exit(1)
