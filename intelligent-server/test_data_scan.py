"""
测试简化的数据分析LLM辅助端点
"""

import requests
import json

BASE_URL = "http://localhost:8000"

# 测试用例：CSV文件带坐标（模拟NestJS的初步分析结果）
test_csv_with_coords = {
    "file_path": "/data/sample_locations.csv",
    "extension": ".csv",
    "initial_form": "Vector",
    "initial_confidence": 0.75,
    "headers": ["id", "longitude", "latitude", "temperature", "humidity", "date"],
    "sample_rows": [
        {"id": 1, "longitude": 110.5, "latitude": 30.2, "temperature": 25.5, "humidity": 65, "date": "2024-01-01"},
        {"id": 2, "longitude": 110.6, "latitude": 30.3, "temperature": 26.1, "humidity": 62, "date": "2024-01-02"},
        {"id": 3, "longitude": 110.7, "latitude": 30.4, "temperature": 24.8, "humidity": 68, "date": "2024-01-03"}
    ],
    "dimensions": None,
    "spatial_info": {"detected_coords": True},
    "temporal_info": {"detected_time": True},
    "detected_metadata": {
        "columns_count": 6,
        "rows_count": 1000
    }
}

# 测试用例2：NetCDF栅格数据
test_netcdf_raster = {
    "file_path": "/data/temperature_grid.nc",
    "extension": ".nc",
    "initial_form": "Raster",
    "initial_confidence": 0.65,
    "headers": ["lat", "lon", "time", "temperature"],
    "sample_rows": [],
    "dimensions": {
        "lat": 180,
        "lon": 360,
        "time": 365
    },
    "spatial_info": {"detected_coords": True},
    "temporal_info": {"detected_time": True},
    "detected_metadata": {
        "resolution": "1.0 degree",
        "unit": "Celsius"
    }
}

def test_data_refine():
    """测试数据分析LLM辅助端点"""
    print("=" * 60)
    print("测试数据分析LLM辅助端点")
    print("=" * 60)
    
    test_cases = [
        ("CSV with coordinates", test_csv_with_coords),
        ("NetCDF Raster", test_netcdf_raster)
    ]
    
    for test_name, test_data in test_cases:
        print(f"\n测试: {test_name}")
        print("-" * 40)
        
        try:
            response = requests.post(
                f"{BASE_URL}/api/agents/data-refine",
                json=test_data,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ 状态: {result.get('status')}")
                print(f"📊 修正后的数据形式: {result.get('form')}")
                print(f"📈 修正后的置信度: {result.get('confidence'):.2f}")
                print(f"📝 补全的详情: {json.dumps(result.get('details', {}), ensure_ascii=False, indent=2)}")
                
                if result.get('corrections'):
                    print(f"🔧 修正说明:")
                    for correction in result.get('corrections', []):
                        print(f"   - {correction}")
                
                if result.get('completions'):
                    print(f"✨ 补全说明:")
                    for completion in result.get('completions', []):
                        print(f"   - {completion}")
            else:
                print(f"❌ 错误: {response.status_code}")
                print(response.text)
        
        except Exception as e:
            print(f"❌ 异常: {str(e)}")
        
        print()

if __name__ == "__main__":
    test_data_refine()

