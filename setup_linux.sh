#!/bin/bash
# Mapbox 地理数据转换 - macOS/Linux 一键安装脚本

echo ""
echo "================================================"
echo "  Mapbox 地理数据转换环境配置"
echo "================================================"
echo ""

# 检查虚拟环境
if [ ! -d ".venv" ]; then
    echo "[*] 创建虚拟环境..."
    python3 -m venv .venv
    if [ $? -ne 0 ]; then
        echo "[!] 创建虚拟环境失败"
        echo "    请确保已安装 Python 3.7+"
        exit 1
    fi
fi

# 激活虚拟环境
echo "[*] 激活虚拟环境..."
source .venv/bin/activate

# 检查 Python 版本
PYTHON_VER=$(python --version 2>&1)
echo "[✓] Python 版本: $PYTHON_VER"

# 安装依赖
echo "[*] 安装 Python 依赖..."
echo "    这可能需要几分钟..."
pip install -q -r requirements_geo.txt
if [ $? -ne 0 ]; then
    echo "[!] 依赖安装失败"
    echo "    请尝试手动运行: pip install -r requirements_geo.txt"
    exit 1
fi
echo "[✓] 依赖安装成功"

# 验证依赖
echo ""
echo "[*] 验证依赖..."
python -c "import geopandas, rasterio, shapely, numpy, pandas; print('[✓] 所有依赖都已安装')" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "[!] 依赖验证失败"
    exit 1
fi

# 测试脚本
echo ""
echo "[*] 测试转换脚本..."
if [ ! -f "src/data-mapping/python/geo_converter.py" ]; then
    echo "[!] 找不到转换脚本: src/data-mapping/python/geo_converter.py"
    exit 1
fi
echo "[✓] 转换脚本文件正常"

# 编译项目
echo ""
echo "[*] 编译 TypeScript 项目..."
npm run build >/dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "[!] 编译失败，请运行: npm run build"
    exit 1
fi
echo "[✓] 项目编译成功"

# 完成
echo ""
echo "================================================"
echo "  环境配置完成！"
echo "================================================"
echo ""
echo "[✓] 虚拟环境已创建"
echo "[✓] 所有 Python 依赖已安装"
echo "[✓] 项目已编译"
echo ""
echo "下一步:"
echo "  1. 虚拟环境已激活，可以直接运行:"
echo "     npm run start:dev"
echo ""
echo "  2. 在另一个终端测试 API:"
echo "     curl -X POST http://localhost:3000/api/data/upload-and-convert"
echo ""
echo "================================================"
echo ""
