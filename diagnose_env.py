#!/usr/bin/env python3
"""
诊断 Mapbox 地理数据转换功能的依赖和环境
帮助快速定位和解决问题
"""
import os
import sys
import subprocess
import platform

def print_header(text):
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60)

def print_section(text):
    print(f"\n→ {text}")

def run_command(cmd, description=""):
    """执行命令并返回结果"""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=10
        )
        if description:
            print(f"  {description}")
        if result.returncode == 0:
            print(f"  ✓ 成功")
            return True, result.stdout.strip()
        else:
            print(f"  ✗ 失败: {result.stderr.strip()}")
            return False, result.stderr.strip()
    except Exception as e:
        print(f"  ✗ 执行错误: {str(e)}")
        return False, str(e)

def check_python():
    """检查 Python 版本"""
    print_section("检查 Python 环境")
    print(f"  Python 版本: {sys.version}")
    print(f"  Python 路径: {sys.executable}")
    print(f"  Python 位置: {os.path.dirname(sys.executable)}")
    
    if sys.version_info < (3, 7):
        print("  ⚠️  警告: Python 应该是 3.7 或更高版本")
        return False
    return True

def check_venv():
    """检查虚拟环境"""
    print_section("检查虚拟环境")
    
    project_root = os.getcwd()
    venv_paths = [
        os.path.join(project_root, '.venv'),
        os.path.join(project_root, 'venv'),
    ]
    
    for venv_path in venv_paths:
        if os.path.exists(venv_path):
            print(f"  ✓ 找到虚拟环境: {venv_path}")
            
            # Windows
            if platform.system() == "Windows":
                python_exe = os.path.join(venv_path, 'Scripts', 'python.exe')
            else:
                python_exe = os.path.join(venv_path, 'bin', 'python')
            
            if os.path.exists(python_exe):
                print(f"    ✓ Python 可执行文件: {python_exe}")
                return True, python_exe
            else:
                print(f"    ✗ 找不到 Python 可执行文件: {python_exe}")
    
    print("  ✗ 未找到虚拟环境")
    print("  建议: 创建虚拟环境")
    if platform.system() == "Windows":
        print("    python -m venv .venv")
        print("    .venv\\Scripts\\activate")
    else:
        print("    python3 -m venv .venv")
        print("    source .venv/bin/activate")
    
    return False, None

def check_dependencies():
    """检查所需的 Python 依赖"""
    print_section("检查 Python 依赖")
    
    required_packages = [
        ('geopandas', 'geopandas'),
        ('rasterio', 'rasterio'),
        ('shapely', 'shapely'),
        ('numpy', 'numpy'),
        ('pandas', 'pandas'),
        ('PIL', 'Pillow'),
        ('xarray', 'xarray'),
        ('h5py', 'h5py'),
    ]
    
    missing = []
    for import_name, package_name in required_packages:
        try:
            __import__(import_name)
            print(f"  ✓ {package_name}")
        except ImportError:
            print(f"  ✗ {package_name} (缺失)")
            missing.append(package_name)
    
    return len(missing) == 0, missing

def check_geo_converter():
    """检查 geo_converter.py 脚本"""
    print_section("检查地理数据转换脚本")
    
    script_path = os.path.join(
        os.getcwd(),
        'src', 'data-mapping', 'python', 'geo_converter.py'
    )
    
    if os.path.exists(script_path):
        print(f"  ✓ 脚本存在: {script_path}")
        return True
    else:
        print(f"  ✗ 脚本不存在: {script_path}")
        return False

def test_conversion(python_exe, venv_found):
    """测试转换功能"""
    print_section("测试地理数据转换")
    
    if not venv_found or not python_exe:
        print("  ⚠️  跳过测试，因为未找到合适的 Python 环境")
        return False
    
    test_geojson = """{
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [0, 0]},
            "properties": {"name": "test"}
        }]
    }"""
    
    test_file = "test_conversion.geojson"
    try:
        with open(test_file, 'w') as f:
            f.write(test_geojson)
        
        script_path = os.path.join(
            os.getcwd(),
            'src', 'data-mapping', 'python', 'geo_converter.py'
        )
        
        cmd = f'"{python_exe}" "{script_path}" convert "{os.path.abspath(test_file)}"'
        success, output = run_command(cmd, "运行转换测试...")
        
        if success:
            import json
            try:
                result = json.loads(output)
                if result.get('success'):
                    print(f"    要素数量: {result.get('feature_count', 'N/A')}")
                    return True
            except:
                pass
        
        return False
    except Exception as e:
        print(f"  ✗ 测试失败: {str(e)}")
        return False
    finally:
        if os.path.exists(test_file):
            os.remove(test_file)

def install_dependencies():
    """安装未缺失的依赖"""
    print_section("安装依赖")
    
    has_venv, python_exe = check_venv()
    if not has_venv or not python_exe:
        print("  ✗ 未找到虚拟环境，无法安装依赖")
        return False
    
    print(f"  使用 Python: {python_exe}")
    
    req_file = "requirements_geo.txt"
    if os.path.exists(req_file):
        cmd = f'"{python_exe}" -m pip install -r {req_file}'
        print(f"  执行: {cmd}")
        success, output = run_command(cmd, "安装依赖...")
        return success
    else:
        print(f"  ✗ 找不到 {req_file}")
        return False

def main():
    print_header("Mapbox 地理数据转换 - 环境诊断")
    
    # 检查 Python 版本
    python_ok = check_python()
    
    # 检查虚拟环境
    venv_ok, python_exe = check_venv()
    
    # 检查脚本
    script_ok = check_geo_converter()
    
    # 检查依赖
    deps_ok, missing_deps = check_dependencies()
    
    # 总结
    print_header("诊断总结")
    
    print("\n状态:")
    print(f"  Python 版本: {'✓' if python_ok else '✗'}")
    print(f"  虚拟环境: {'✓' if venv_ok else '✗'}")
    print(f"  脚本文件: {'✓' if script_ok else '✗'}")
    print(f"  依赖包: {'✓' if deps_ok else '✗'}")
    
    if not deps_ok:
        print(f"\n缺失的依赖: {', '.join(missing_deps)}")
        print("\n建议:")
        print(f"  1. 激活虚拟环境:")
        if platform.system() == "Windows":
            print(f"     .venv\\Scripts\\activate")
        else:
            print(f"     source .venv/bin/activate")
        print(f"  2. 安装依赖:")
        print(f"     pip install -r requirements_geo.txt")
        
        response = input("\n是否现在安装依赖? (y/n): ")
        if response.lower() == 'y':
            if install_dependencies():
                print("\n✓ 依赖安装成功!")
                # 重新检查
                deps_ok, _ = check_dependencies()
            else:
                print("\n✗ 依赖安装失败，请手动安装")
    
    # 测试
    if venv_ok and script_ok and deps_ok:
        test_ok = test_conversion(python_exe, venv_ok)
        if test_ok:
            print("\n✓ 所有检查都通过了！你的环境已准备就绪。")
        else:
            print("\n⚠️  有些检查失败，请查看上面的错误信息。")
    else:
        print("\n⚠️  存在环境问题，请先解决上面的问题。")
    
    print("\n" + "=" * 60 + "\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n中止诊断。")
        sys.exit(0)
    except Exception as e:
        print(f"\n诊断出错: {e}")
        sys.exit(1)
