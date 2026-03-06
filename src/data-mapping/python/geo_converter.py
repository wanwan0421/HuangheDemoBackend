"""
地理数据格式转换工具
支持将 Shapefile、GeoTIFF 等格式转换为 Mapbox 可用格式
"""
import sys
import json
import os
import math
import geopandas as gpd
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.io import MemoryFile
from shapely.geometry import box
import base64
from io import BytesIO
from PIL import Image
import numpy as np


def _try_configure_proj_lib():
    """Try to locate proj.db and set PROJ_LIB if available."""
    if os.environ.get('PROJ_LIB'):
        return

    candidate_dirs = []

    try:
        import pyproj  # type: ignore

        try:
            data_dir = pyproj.datadir.get_data_dir()
            if data_dir:
                candidate_dirs.append(data_dir)
        except Exception:
            pass

        pyproj_root = os.path.dirname(pyproj.__file__)
        candidate_dirs.extend([
            os.path.join(pyproj_root, 'proj_dir', 'share', 'proj'),
            os.path.join(pyproj_root, 'share', 'proj'),
        ])
    except Exception:
        pass

    try:
        rasterio_root = os.path.dirname(rasterio.__file__)
        candidate_dirs.extend([
            os.path.join(rasterio_root, 'proj_data'),
            os.path.join(rasterio_root, 'gdal_data'),
        ])
    except Exception:
        pass

    for candidate in candidate_dirs:
        if candidate and os.path.isdir(candidate):
            proj_db = os.path.join(candidate, 'proj.db')
            if os.path.exists(proj_db):
                os.environ['PROJ_LIB'] = candidate
                return


def _is_web_mercator_crs(crs):
    if not crs:
        return False

    try:
        epsg = crs.to_epsg()
    except Exception:
        epsg = None

    if epsg in (3857, 900913):
        return True

    crs_text = str(crs).lower()
    return (
        'pseudo-mercator' in crs_text
        or 'web mercator' in crs_text
        or 'wgs 84 / pseudo-mercator' in crs_text
        or 'epsg:3857' in crs_text
    )


def _mercator_to_wgs84_bounds(bounds):
    minx, miny, maxx, maxy = bounds
    radius = 6378137.0

    def x_to_lon(x):
        return (x / radius) * (180.0 / math.pi)

    def y_to_lat(y):
        return (2.0 * math.atan(math.exp(y / radius)) - math.pi / 2.0) * (180.0 / math.pi)

    return (x_to_lon(minx), y_to_lat(miny), x_to_lon(maxx), y_to_lat(maxy))


_try_configure_proj_lib()


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
    """
    try:
        print(f"[DEBUG] Start processing GeoTIFF: {tif_path}", file=sys.stderr, flush=True)
        
        with rasterio.open(tif_path) as src:            
            # 获取边界
            bounds = src.bounds
            src_crs = src.crs
            
            print(f"[DEBUG] Original CRS: {src_crs}", file=sys.stderr, flush=True)
            print(f"[DEBUG] Original bounds: {bounds}", file=sys.stderr, flush=True)
            
            # 转换坐标系到 WGS84
            wgs84_bounds = bounds
            if src_crs:
                try:
                    # 检查是否为 Web Mercator
                    if _is_web_mercator_crs(src_crs):
                        print(f"[DEBUG] Web Mercator detected, using manual conversion", file=sys.stderr, flush=True)
                        wgs84_bounds = _mercator_to_wgs84_bounds(bounds)
                    elif src_crs.to_epsg() != 4326:
                        print(f"[DEBUG] CRS transform: {src_crs} -> EPSG:4326", file=sys.stderr, flush=True)
                        from pyproj import Transformer
                        transformer = Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True)
                        minx, miny = transformer.transform(bounds[0], bounds[1])
                        maxx, maxy = transformer.transform(bounds[2], bounds[3])
                        wgs84_bounds = (minx, miny, maxx, maxy)
                except Exception as e:
                    print(f"[WARN] CRS transform failed: {str(e)}, using fallback", file=sys.stderr, flush=True)
                    if _is_web_mercator_crs(src_crs):
                        wgs84_bounds = _mercator_to_wgs84_bounds(bounds)
                    else:
                        # 如果转换失败，尝试直接使用原始边界（可能不准确）
                        print(f"[WARN] Using original bounds as fallback", file=sys.stderr, flush=True)
                        wgs84_bounds = bounds
            
            print(f"[DEBUG] WGS84 bounds: {wgs84_bounds}", file=sys.stderr, flush=True)
            
            # 创建边界 GeoJSON
            try:
                bbox_geom = box(wgs84_bounds[0], wgs84_bounds[1], wgs84_bounds[2], wgs84_bounds[3])
                bounds_geojson = {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [wgs84_bounds[0], wgs84_bounds[1]],
                            [wgs84_bounds[2], wgs84_bounds[1]],
                            [wgs84_bounds[2], wgs84_bounds[3]],
                            [wgs84_bounds[0], wgs84_bounds[3]],
                            [wgs84_bounds[0], wgs84_bounds[1]]
                        ]]
                    },
                    "properties": {
                        "name": os.path.basename(tif_path),
                        "type": "raster_bounds"
                    }
                }
            except Exception as e:
                print(f"[ERROR] Failed to create bounds GeoJSON: {str(e)}", file=sys.stderr, flush=True)
                raise
            
            # 获取栅格元数据
            metadata = {
                "width": src.width,
                "height": src.height,
                "count": src.count,
                "dtype": str(src.dtypes[0]),
                "crs": str(src_crs) if src_crs else None,
                "transform": list(src.transform),
                "nodata": src.nodata,
                "bounds": list(wgs84_bounds)
            }
            
            # 读取统计信息（第一个波段）
            try:
                band1 = src.read(1)
                valid_data = band1[np.isfinite(band1)]
                if src.nodata is not None:
                    valid_data = band1[(np.isfinite(band1)) & (band1 != src.nodata)]
                
                if len(valid_data) > 0:
                    stats = {
                        "min": float(np.min(valid_data)),
                        "max": float(np.max(valid_data)),
                        "mean": float(np.mean(valid_data)),
                        "std": float(np.std(valid_data))
                    }
                else:
                    stats = {
                        "min": None,
                        "max": None,
                        "mean": None,
                        "std": None
                    }
            except Exception as e:
                print(f"[WARN] Failed to calculate statistics: {str(e)}", file=sys.stderr, flush=True)
                stats = {"min": None, "max": None, "mean": None, "std": None}
            
            result = {
                "success": True,
                "type": "raster",
                "format": "geotiff",
                "bounds_geojson": bounds_geojson,
                "metadata": metadata,
                "statistics": stats,
                "file_path": tif_path
            }
            
            print(f"[DEBUG] GeoTIFF processing completed successfully", file=sys.stderr, flush=True)
            return result
            
    except Exception as e:
        error_msg = str(e)
        print(f"[ERROR] GeoTIFF processing failed: {error_msg}", file=sys.stderr, flush=True)
        import traceback
        print(f"[ERROR] Traceback:\n{traceback.format_exc()}", file=sys.stderr, flush=True)
        return {
            "success": False,
            "error": error_msg,
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
    ext = os.path.splitext(file_path)[1].lower()
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    
    # Shapefile
    if ext == '.shp':
        output_path = None
        if output_dir:
            output_path = os.path.join(output_dir, f"{base_name}.geojson")
        return shapefile_to_geojson(file_path, output_path)
    
    # GeoJSON (直接读取并验证)
    elif ext in ['.geojson', '.json']:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                geojson_data = json.load(f)
            
            if geojson_data.get('type') in ['FeatureCollection', 'Feature']:
                gdf = gpd.GeoDataFrame.from_features(geojson_data)
                bounds = gdf.total_bounds
                
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
        # 获取地理坐标信息
        result = geotiff_to_mapbox_info(file_path)

        # 生成PNG文件
        png_path = os.path.splitext(file_path)[0] + '.png'
        png_result = geotiff_to_png_tile(file_path, output_path=png_path)

        if png_result['success']:
            result['png_path'] = png_path
            result['has_png'] = True
        return result
    
    # KML (需要转换)
    elif ext == '.kml':
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
            print(f"[ERROR] KML conversion failed: {str(e)}", file=sys.stderr, flush=True)
            return {"success": False, "error": str(e), "type": "vector"}
    else:
        print(f"[ERROR] Unsupported file format: {ext}", file=sys.stderr, flush=True)
        return {
            "success": False,
            "error": f"Unsupported file format: {ext}",
            "supported_formats": [".shp", ".geojson", ".json", ".tif", ".tiff", ".kml"]
        }


if __name__ == "__main__":    
    try:
        if len(sys.argv) < 2:
            print(json.dumps({"error": "Usage: python geo_converter.py <command> <file_path> [output_dir]"}))
            sys.exit(1)
        
        command = sys.argv[1]
        result = None
        
        if command == "convert":
            if len(sys.argv) < 3:
                result = {"error": "File path required"}
            else:
                file_path = sys.argv[2]
                output_dir = sys.argv[3] if len(sys.argv) > 3 else None
                result = convert_to_mapbox(file_path, output_dir)
        
        elif command == "shapefile_to_geojson":
            if len(sys.argv) < 3:
                result = {"error": "Shapefile path required"}
            else:
                file_path = sys.argv[2]
                output_path = sys.argv[3] if len(sys.argv) > 3 else None
                result = shapefile_to_geojson(file_path, output_path)
        
        elif command == "geotiff_info":
            if len(sys.argv) < 3:
                result = {"error": "GeoTIFF path required"}
            else:
                file_path = sys.argv[2]
                result = geotiff_to_mapbox_info(file_path)
        
        else:
            result = {"error": f"Unknown command: {command}"}
        
        # 确保始终输出有效的 JSON
        if result is None:
            result = {"error": "No result generated"}
        
        print(json.dumps(result, ensure_ascii=False))
        sys.stdout.flush()
        
    except Exception as e:
        import traceback
        error_result = {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }
        print(json.dumps(error_result, ensure_ascii=False))
        sys.stdout.flush()
        sys.exit(1)