"""
测试地理数据转换功能
使用示例数据测试各种格式的转换
"""
import json
import sys
import os

# 添加路径以便导入 geo_converter
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src', 'data-mapping', 'python'))

try:
    from geo_converter import (
        shapefile_to_geojson,
        geotiff_to_mapbox_info,
        convert_to_mapbox
    )
    print("✓ 成功导入 geo_converter 模块")
except ImportError as e:
    print(f"✗ 导入失败: {e}")
    print("\n请确保已安装所需的 Python 依赖:")
    print("pip install -r requirements_geo.txt")
    sys.exit(1)

def test_dependencies():
    """测试所需依赖是否已安装"""
    print("\n检查依赖...")
    dependencies = {
        'geopandas': 'geopandas',
        'rasterio': 'rasterio',
        'shapely': 'shapely.geometry',
        'numpy': 'numpy',
        'PIL': 'PIL',
    }
    
    missing = []
    for name, module in dependencies.items():
        try:
            __import__(module)
            print(f"  ✓ {name}")
        except ImportError:
            print(f"  ✗ {name} (缺失)")
            missing.append(name)
    
    if missing:
        print(f"\n缺少依赖: {', '.join(missing)}")
        print("请运行: pip install -r requirements_geo.txt")
        return False
    
    return True

def create_test_geojson():
    """创建一个测试 GeoJSON 文件"""
    test_data = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [116.4074, 39.9042]  # 北京
                },
                "properties": {
                    "name": "北京",
                    "type": "测试点"
                }
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [116.3, 39.8],
                        [116.5, 39.8],
                        [116.5, 40.0],
                        [116.3, 40.0],
                        [116.3, 39.8]
                    ]]
                },
                "properties": {
                    "name": "测试区域"
                }
            }
        ]
    }
    
    test_file = 'test_data.geojson'
    with open(test_file, 'w', encoding='utf-8') as f:
        json.dump(test_data, f, ensure_ascii=False, indent=2)
    
    return test_file

def test_geojson_conversion():
    """测试 GeoJSON 转换"""
    print("\n测试 GeoJSON 转换...")
    try:
        test_file = create_test_geojson()
        result = convert_to_mapbox(test_file)
        
        if result['success']:
            print(f"  ✓ GeoJSON 转换成功")
            print(f"    - 要素数量: {result['feature_count']}")
            print(f"    - 边界: {result['bounds']}")
        else:
            print(f"  ✗ 转换失败: {result.get('error')}")
        
        # 清理测试文件
        if os.path.exists(test_file):
            os.remove(test_file)
        
        return result['success']
    except Exception as e:
        print(f"  ✗ 测试失败: {e}")
        return False

def print_summary():
    """打印使用说明"""
    print("\n" + "="*60)
    print("地理数据转换功能测试完成!")
    print("="*60)
    print("\n后端 API 端点:")
    print("  POST /api/data/upload-and-convert  - 上传并转换文件")
    print("  POST /api/data/convert             - 转换已有文件")
    print("  POST /api/data/convert-batch       - 批量转换")
    print("\n支持的格式:")
    print("  矢量: .shp, .geojson, .json, .kml")
    print("  栅格: .tif, .tiff")
    print("\n详细文档:")
    print("  - MAPBOX_CONVERTER_README.md    - API 文档")
    print("  - MAPBOX_FRONTEND_EXAMPLE.js    - 前端集成示例")
    print("\n安装依赖:")
    print("  pip install -r requirements_geo.txt")
    print("="*60 + "\n")

if __name__ == '__main__':
    print("="*60)
    print("地理数据转换功能测试")
    print("="*60)
    
    # 测试依赖
    if not test_dependencies():
        sys.exit(1)
    
    # 测试转换功能
    test_geojson_conversion()
    
    # 打印总结
    print_summary()
