@echo off
REM Mapbox 地理数据转换 - Windows 一键安装脚本

echo.
echo ================================================
echo  Mapbox 地理数据转换环境配置
echo ================================================
echo.

REM 检查虚拟环境
if not exist ".venv" (
    echo [*] 创建虚拟环境...
    python -m venv .venv
    if errorlevel 1 (
        echo [!] 创建虚拟环境失败
        echo     请确保已安装 Python 3.7+
        pause
        exit /b 1
    )
)

REM 激活虚拟环境
echo [*] 激活虚拟环境...
call .venv\Scripts\activate.bat

REM 检查 Python 版本
for /f "tokens=*" %%i in ('python --version') do set PYTHON_VER=%%i
echo [✓] Python 版本: %PYTHON_VER%

REM 安装依赖
echo [*] 安装 Python 依赖...
echo     这可能需要几分钟...
pip install -q -r requirements_geo.txt
if errorlevel 1 (
    echo [!] 依赖安装失败
    echo     请尝试手动运行: pip install -r requirements_geo.txt
    pause
    exit /b 1
)
echo [✓] 依赖安装成功

REM 验证依赖
echo.
echo [*] 验证依赖...
python -c "import geopandas, rasterio, shapely, numpy, pandas; print('[✓] 所有依赖都已安装')" 2>nul
if errorlevel 1 (
    echo [!] 依赖验证失败
    pause
    exit /b 1
)

REM 测试脚本
echo.
echo [*] 测试转换脚本...
if not exist "src\data-mapping\python\geo_converter.py" (
    echo [!] 找不到转换脚本: src\data-mapping\python\geo_converter.py
    pause
    exit /b 1
)
echo [✓] 转换脚本文件正常

REM 编译项目
echo.
echo [*] 编译 TypeScript 项目...
call npm run build >nul 2>&1
if errorlevel 1 (
    echo [!] 编译失败，请运行: npm run build
    pause
    exit /b 1
)
echo [✓] 项目编译成功

REM 完成
echo.
echo ================================================
echo  环境配置完成！
echo ================================================
echo.
echo [✓] 虚拟环境已创建
echo [✓] 所有 Python 依赖已安装
echo [✓] 项目已编译
echo.
echo 下一步:
echo   1. 启动后端服务:
echo      npm run start:dev
echo.
echo   2. 测试 API (在另一个终端):
echo      curl -X POST http://localhost:3000/api/data/upload-and-convert
echo.
echo ================================================
echo.

pause
