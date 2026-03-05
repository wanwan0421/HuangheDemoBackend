# 🔧 Mapbox 地理数据转换 - 快速修复指南

## 问题诊断

如果遇到这个错误：
```
ERROR [DataService] 执行转换脚本时出错: spawn ... ENOENT
ERROR [DataService] 地理数据转换失败，退出码: -4058
```

这通常表示 **Python 环境或依赖未正确配置**。

## ⚡ 快速修复步骤

### 1️⃣ 运行诊断工具（推荐）

```bash
# 在项目根目录运行
python diagnose_env.py
```

该工具会自动：
- ✓ 检查 Python 版本
- ✓ 检查虚拟环境
- ✓ 检查所需依赖
- ✓ 可选：自动安装缺失依赖
- ✓ 测试转换功能

### 2️⃣ 手动修复

如果诊断工具显示缺失依赖，执行：

```bash
# Windows
.venv\Scripts\activate
pip install -r requirements_geo.txt

# macOS / Linux
source .venv/bin/activate
pip install -r requirements_geo.txt
```

### 3️⃣ 验证修复

```bash
# 重新编译
npm run build

# 重启服务
npm run start:dev
```

## 常见问题排查表

| 问题 | 症状 | 解决方案 |
|-----|------|--------|
| 虚拟环境不存在 | `找不到虚拟环境` | 创建虚拟环境：`python -m venv .venv` |
| Python 版本过低 | `Python 3.7+ required` | 升级 Python：访问 python.org |
| 依赖未安装 | 缺失 geopandas、rasterio 等 | `pip install -r requirements_geo.txt` |
| Python 路径错误 | ENOENT 错误 | 运行 `diagnose_env.py` 检查路径 |
| Windows Shell 问题 | 脚本无法执行 | 确保 .venv 在项目根目录 |

## 📋 详细步骤

### 步骤 1: 检查虚拟环境

```bash
# 列出虚拟环境目录
ls -la  # macOS/Linux
dir     # Windows

# 应该看到 .venv 目录
```

### 步骤 2: 激活虚拟环境

```bash
# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# Windows (CMD)
.venv\Scripts\activate.bat

# macOS / Linux
source .venv/bin/activate
```

### 步骤 3: 验证 Python

```bash
python --version    # 应该显示 3.7+
which python        # 应该显示虚拟环境中的 Python
```

### 步骤 4: 安装依赖

```bash
# 查看 requirements_geo.txt
cat requirements_geo.txt

# 安装所有依赖
pip install -r requirements_geo.txt

# 验证安装
python -c "import geopandas, rasterio, shapely; print('依赖安装成功！')"
```

### 步骤 5: 测试转换

```bash
# 运行诊断工具的测试部分
python -c "
import sys
sys.path.insert(0, 'src/data-mapping/python')
from geo_converter import convert_to_mapbox

# 如果没有错误，说明 Python 环境正常
print('✓ Python 环境检查通过')
"
```

## 🔍 深度诊断

如果以上步骤都完成但仍有问题，运行：

```bash
# 1. 检查项目结构
python diagnose_env.py

# 2. 查看 Python 搜索路径
python -c "import sys; print('\n'.join(sys.path))"

# 3. 检查 geo_converter.py 是否可读
ls -la src/data-mapping/python/geo_converter.py

# 4. 手动运行转换脚本
python src/data-mapping/python/geo_converter.py convert test_file.geojson
```

## 🚀 重新启动服务

所有依赖安装完成后：

```bash
# 重新编译
npm run build

# 启动开发服务器
npm run start:dev

# 或启动生产服务器
npm run start
```

## 📝 检查清单

在运行转换前，确保：

- [ ] `.venv` 目录在项目根目录中
- [ ] Python 版本 >= 3.7
- [ ] 虚拟环境已激活
- [ ] 运行过 `pip install -r requirements_geo.txt`
- [ ] `src/data-mapping/python/geo_converter.py` 文件存在
- [ ] 项目已编译：`npm run build`
- [ ] 后端服务已启动

## 🆘 仍需帮助？

如果问题仍未解决，请：

1. 运行 `python diagnose_env.py` 并保存输出
2. 检查项目 `.env` 文件是否有特殊配置
3. 查看 `npm run build` 的输出没有编译错误
4. 检查操作系统和 Python 版本是否受支持

**支持的环境：**
- Python 3.7 - 3.12
- Windows 10+, macOS 10.14+, Linux (Ubuntu 18.04+)

## 📚 相关文档

- [Mapbox 快速入门](MAPBOX_QUICK_START.md)
- [API 详细文档](MAPBOX_CONVERTER_README.md)
- [Python 转换脚本](src/data-mapping/python/geo_converter.py)
