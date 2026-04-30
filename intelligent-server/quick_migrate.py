#!/usr/bin/env python3
"""
快速迁移启动脚本
提供交互式菜单选择迁移模式
"""

import os
import sys
import subprocess
import time
from pathlib import Path

# 添加intelligent-server目录到Python路径
sys.path.insert(0, str(Path(__file__).parent))

def print_header(text):
    """打印标题"""
    print("\n" + "=" * 60)
    print(f"🚀 {text}")
    print("=" * 60 + "\n")

def check_service(url: str, timeout: int = 5) -> bool:
    """检查服务是否运行"""
    import subprocess
    try:
        result = subprocess.run(
            ["curl", "-s", "-m", str(timeout), "-f", url],
            capture_output=True,
            timeout=timeout + 1
        )
        return result.returncode == 0
    except:
        return False

def check_prerequisites():
    """检查前置条件"""
    print_header("检查前置条件")
    
    services = {
        "MongoDB": "mongodb://localhost:27017/",
        "Milvus": "http://localhost:19530/healthz",
        "NestJS": "http://localhost:3000/genai/health"
    }
    
    all_ok = True
    for service_name, url in services.items():
        if check_service(url):
            print(f"✅ {service_name} 运行中")
        else:
            print(f"❌ {service_name} 未运行或无法连接")
            all_ok = False
    
    if not all_ok:
        print("\n⚠️  部分服务未运行。请先启动所需的服务：")
        print("  docker-compose -f docker-compose.milvus.yml up -d")
        print("  npm run start:dev")
        return False
    
    return True

def start_services():
    """启动容器服务"""
    print_header("启动Milvus和MongoDB")
    
    try:
        print("🔄 启动Docker服务...")
        result = subprocess.run(
            ["docker-compose", "-f", "docker-compose.milvus.yml", "up", "-d"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print("✅ Docker服务启动成功")
            print("   等待服务就绪...")
            time.sleep(5)
            
            # 检查服务是否就绪
            for i in range(12):
                if check_service("http://localhost:19530/healthz"):
                    print("✅ Milvus 就绪 ✓")
                    break
                print(f"   等待中... ({i+1}/12)")
                time.sleep(5)
            
            return True
        else:
            print(f"❌ 启动失败: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False

def show_menu():
    """显示主菜单"""
    print_header("选择迁移模式")
    
    modes = {
        "1": {
            "name": "完整迁移 (推荐)",
            "description": "重新生成所有向量到Milvus (使用新的taskType)",
            "cmd": "full"
        },
        "2": {
            "name": "数据迁移",
            "description": "保留原有向量，只迁移数据到Milvus",
            "cmd": "migrate-only"
        },
        "3": {
            "name": "验证数据",
            "description": "检查Milvus中的数据状态",
            "cmd": "verify"
        },
        "4": {
            "name": "启动容器",
            "description": "启动Milvus和MongoDB容器",
            "cmd": "docker"
        },
        "5": {
            "name": "检查前置条件",
            "description": "验证所有服务是否运行",
            "cmd": "check"
        },
        "0": {
            "name": "退出",
            "description": "退出程序",
            "cmd": None
        }
    }
    
    for key, mode in modes.items():
        print(f"{key}. {mode['name']}")
        print(f"   {mode['description']}")
    
    print()
    choice = input("请选择 (0-5): ").strip()
    
    return modes.get(choice, {}).get("cmd")

def run_migration(mode: str):
    """执行迁移"""
    print_header(f"执行迁移: {mode}")
    
    if mode == "docker":
        if start_services():
            print("✅ 服务启动完成")
            return True
        else:
            return False
    
    if mode == "check":
        return check_prerequisites()
    
    # 其他迁移模式
    try:
        # 构建命令
        cmd = [
            sys.executable,
            "migrate_to_milvus.py",
            "--mode", mode
        ]
        
        print(f"执行: {' '.join(cmd)}\n")
        
        result = subprocess.run(cmd, cwd=str(Path(__file__).parent))
        
        if result.returncode == 0:
            print(f"\n✅ {mode}迁移完成")
            return True
        else:
            print(f"\n❌ {mode}迁移失败")
            return False
    
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False

def main():
    print("""
╔════════════════════════════════════════════════════════╗
║                                                        ║
║      MongoDB Embedding 迁移到 Milvus                  ║
║                                                        ║
║      快速启动脚本 - Interactive Migration Tool        ║
║                                                        ║
╚════════════════════════════════════════════════════════╝
    """)
    
    while True:
        mode = show_menu()
        
        if mode is None:
            print("👋 再见！")
            break
        
        if run_migration(mode):
            print("\n✨ 操作成功完成")
        else:
            print("\n⚠️  操作失败，请检查错误信息")
        
        input("\n按Enter继续...")

if __name__ == "__main__":
    main()
