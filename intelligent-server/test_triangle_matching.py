"""
三角匹配系统测试脚本（批量处理模式）

测试流程：
1. 批量扫描数据文件（可选）
2. 执行三角匹配对齐
3. 查询对齐状态和会话信息
4. 运行完整工作流
"""

import requests
import json
import time

# API基础地址
BASE_URL = "http://localhost:8000"


def print_section(title):
    """打印分节标题"""
    print("\n" + "="*60)
    print(f" {title}")
    print("="*60)


def test_parse_requirement():
    """测试1: 阶段1 - 解析需求并推荐模型"""
    print_section("测试1: 阶段1 - 解析需求并推荐模型")
    
    url = f"{BASE_URL}/api/triangle-matching/parse-requirement"
    payload = {
        "user_request": "我需要模拟黄河流域2020-2023年的水文过程，包括降水、蒸发、径流等变量"
    }
    
    print(f"请求URL: {url}")
    print(f"请求数据: {json.dumps(payload, ensure_ascii=False, indent=2)}")
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        result = response.json()
        
        print(f"响应状态: {response.status_code}")
        print(f"响应数据: {json.dumps(result, ensure_ascii=False, indent=2)}")
        
        session_id = result.get("session_id")
        model_name = result.get("model_contract", {}).get("model_name", "")

        print(f"\n✓ 阶段1完成！")
        print(f"  Session ID: {session_id}")
        print(f"  推荐模型: {model_name}")
        
        return session_id
    
    except requests.exceptions.RequestException as e:
        print(f"\n✗ 请求失败: {e}")
        return None

def test_scan_and_align(session_id):
    """测试2: 阶段2 - 扫描数据并对齐检查"""
    print_section("测试2: 阶段2 - 扫描数据并对齐检查")
    
    if not session_id:
        print("✗ 缺少 session_id，跳过测试")
        return
    
    url = f"{BASE_URL}/api/triangle-matching/scan-and-align"
    payload = {
        "session_id": session_id,
        "file_paths": [
            "uploads/test/precipitation_2020_2023.nc",
            "uploads/test/dem_huanghe.tif",
            "uploads/test/evaporation_2020_2023.csv"
        ]
    }
    
    print(f"请求URL: {url}")
    print(f"请求数据: {json.dumps(payload, ensure_ascii=False, indent=2)}")
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        result = response.json()
        
        print(f"响应状态: {response.status_code}")
        print(f"响应数据: {json.dumps(result, ensure_ascii=False, indent=2)}")
        
        alignment_status = result.get("alignment_status")
        can_run_now = result.get("can_run_now")
        go_no_go = result.get("go_no_go")

        print(f"\n✓ 阶段2完成！")
        print(f"  对齐状态: {alignment_status}")
        print(f"  Go/No-Go: {go_no_go}")
        print(f"  可直接执行: {can_run_now}")
        
    except requests.exceptions.RequestException as e:
        print(f"\n✗ 请求失败: {e}")

def test_get_status(session_id):
    """测试3: 查询对齐状态"""
    print_section("测试3: 查询对齐状态")
    
    if not session_id:
        print("✗ 缺少 session_id")
        return
    
    url = f"{BASE_URL}/api/triangle-matching/status/{session_id}"
    
    print(f"请求URL: {url}")
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        result = response.json()
        
        print(f"响应状态: {response.status_code}")
        print(f"响应数据: {json.dumps(result, ensure_ascii=False, indent=2)}")
        
        alignment_status = result.get("alignment_status", {})
        status = alignment_status.get("status", "unknown")
        score = alignment_status.get("overall_score", 0.0)
        
        print(f"\n✓ 对齐状态: {status}")
        print(f"✓ 对齐得分: {score}")
        
    except requests.exceptions.RequestException as e:
        print(f"\n✗ 请求失败: {e}")


def test_scan_data():
    """测试4: 批量扫描数据文件"""
    print_section("测试4: 批量扫描数据文件（预览）")
    
    url = f"{BASE_URL}/api/triangle-matching/scan-data"
    
    # 批量扫描文件
    file_paths = [
        "uploads/test/temperature_2020.tif",
        "uploads/test/soil_moisture.nc"
    ]
    
    print(f"请求URL: {url}")
    print(f"请求数据: {json.dumps(file_paths, ensure_ascii=False, indent=2)}")
    
    try:
        response = requests.post(url, json=file_paths)
        response.raise_for_status()
        result = response.json()
        
        print(f"响应状态: {response.status_code}")
        print(f"响应数据: {json.dumps(result, ensure_ascii=False, indent=2)}")
        
        count = result.get("count", 0)
        print(f"\n✓ 成功扫描 {count} 个文件")
        
    except requests.exceptions.RequestException as e:
        print(f"\n✗ 请求失败: {e}")


def test_rescan_data():
    """测试5: 增量重扫数据文件"""
    print_section("测试5: 增量重扫数据文件")

    url = f"{BASE_URL}/api/triangle-matching/rescan-data"
    payload = {
        "file_paths": [
            "uploads/test/temperature_2020.tif",
            "uploads/test/soil_moisture.nc"
        ]
    }

    print(f"请求URL: {url}")
    print(f"请求数据: {json.dumps(payload, ensure_ascii=False, indent=2)}")

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        result = response.json()

        print(f"响应状态: {response.status_code}")
        print(f"响应数据: {json.dumps(result, ensure_ascii=False, indent=2)}")

        rescan_result = result.get("rescan_result", {})
        changed_count = len(rescan_result.get("changed_files", []))
        print(f"\n✓ 增量重扫完成，变化文件数: {changed_count}")

    except requests.exceptions.RequestException as e:
        print(f"\n✗ 请求失败: {e}")


def test_get_session(session_id):
    """测试4: 查看完整会话信息"""
    print_section("测试4: 查看完整会话信息")
    
    if not session_id:
        print("✗ 缺少 session_id")
        return
    
    url = f"{BASE_URL}/api/triangle-matching/session/{session_id}"
    
    print(f"请求URL: {url}")
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        result = response.json()
        
        print(f"响应状态: {response.status_code}")
        print(f"响应数据: {json.dumps(result, ensure_ascii=False, indent=2)}")
        
        print(f"\n✓ 会话信息获取成功！")
        
    except requests.exceptions.RequestException as e:
        print(f"\n✗ 请求失败: {e}")


def test_run_workflow():
    """测试6: 运行完整四Agent工作流"""
    print_section("测试6: 运行完整四Agent工作流")
    
    url = f"{BASE_URL}/api/triangle-matching/run-workflow"
    payload = {
        "user_request": "我需要评估长江中下游地区的洪水风险，时间范围是2015-2020年夏季汛期",
        "file_paths": [
            "uploads/test/dem_yangtze.tif",
            "uploads/test/rainfall_summer_2015_2020.csv"
        ]
    }
    
    print(f"请求URL: {url}")
    print(f"请求数据: {json.dumps(payload, ensure_ascii=False, indent=2)}")
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        result = response.json()
        
        print(f"响应状态: {response.status_code}")
        print(f"响应数据: {json.dumps(result, ensure_ascii=False, indent=2)}")
        
        print(f"\n✓ 工作流执行成功！")
        
    except requests.exceptions.RequestException as e:
        print(f"\n✗ 请求失败: {e}")


def test_get_data_profiles():
    """测试7: 获取所有数据画像"""
    print_section("测试7: 获取所有数据画像（缓存）")
    
    url = f"{BASE_URL}/api/triangle-matching/data-profiles"
    
    print(f"请求URL: {url}")
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        result = response.json()
        
        print(f"响应状态: {response.status_code}")
        print(f"响应数据: {json.dumps(result, ensure_ascii=False, indent=2)}")
        
        data_profiles = result.get("data_profiles", {})
        total = data_profiles.get("total_count", 0)
        
        print(f"\n✓ 共有 {total} 个数据画像")
        
    except requests.exceptions.RequestException as e:
        print(f"\n✗ 请求失败: {e}")


def main():
    """主测试流程（批量处理模式）"""
    print("\n" + "🚀 三角匹配系统测试（两阶段模式）".center(60, "="))
    print(f"基础URL: {BASE_URL}")
    
    # 测试1: 阶段1 - 解析需求并推荐模型
    session_id = test_parse_requirement()
    
    if session_id:
        time.sleep(1)
        
        # 测试2: 阶段2 - 扫描数据并对齐
        test_scan_and_align(session_id)
        time.sleep(1)
       
        # 测试3: 查询状态
        test_get_status(session_id)
        time.sleep(1)
        
        # 查看完整会话
        test_get_session(session_id)

    # 测试4: 独立的数据扫描测试（预览功能）
    time.sleep(1)
    test_scan_data()

    # 测试5: 增量重扫测试
    time.sleep(1)
    test_rescan_data()

    # 测试6: 运行完整工作流
    time.sleep(1)
    test_run_workflow()

    # 测试7: 获取所有数据画像
    time.sleep(1)
    test_get_data_profiles()
    
    print("\n" + "✓ 所有测试完成！".center(60, "=") + "\n")


if __name__ == "__main__":
    main()
