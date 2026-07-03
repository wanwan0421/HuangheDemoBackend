import re
import os
from pathlib import Path


# =========================================================
# 1. 服务基础配置
# =========================================================

PROJECT_NAME = "Remote Sensing Tile Server"

API_PREFIX = "/api/remote-sensing"

# 前端开发地址，后续做跨域时会用到
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


# =========================================================
# 2. 土地覆盖 COG 数据配置
# =========================================================

LANDCOVER_COG_DIR = Path(
    os.getenv(
        "LANDCOVER_COG_DIR",
        r"D:\huanghe-data-display\04_processed_data\remote_sensing"
        r"\landcover_huanghe\04_cog_all_years",
    )
)

LANDCOVER_COG_FILE_PATTERN = re.compile(
    r"^landcover_huanghe_(\d{4})_cog\.tif$",
    re.IGNORECASE,
)


# =========================================================
# 3. 土地覆盖类别配置
# =========================================================

LANDCOVER_CLASSES = {
    1: "耕地",
    2: "森林",
    3: "灌木",
    4: "草原",
    5: "水域",
    6: "冰雪",
    7: "裸地",
    8: "不透水面",
    9: "湿地",
}


# =========================================================
# 4. 工具函数
# =========================================================

def scan_landcover_cog_files() -> dict[int, Path]:
    """
    扫描 COG 目录，根据文件名自动构建 {year: path} 映射。
    """
    if not LANDCOVER_COG_DIR.exists():
        return {}

    landcover_cog_files: dict[int, Path] = {}

    for cog_path in sorted(LANDCOVER_COG_DIR.glob("*.tif")):
        match = LANDCOVER_COG_FILE_PATTERN.match(cog_path.name)
        if not match:
            continue

        year = int(match.group(1))
        landcover_cog_files[year] = cog_path

    return landcover_cog_files


LANDCOVER_COG_FILES = scan_landcover_cog_files()


def get_available_landcover_years() -> list[int]:
    """
    返回当前目录中扫描到的、可用的土地覆盖年份。
    """
    return sorted(LANDCOVER_COG_FILES)


def get_landcover_cog_path(year: int) -> Path:
    """
    根据年份获取 COG 文件路径。
    如果该年份未扫描到，则抛出 KeyError。
    """
    if year not in LANDCOVER_COG_FILES:
        raise KeyError(f"未配置 {year} 年的土地覆盖 COG 文件")

    return LANDCOVER_COG_FILES[year]


# =========================================================
# 5. 土地覆盖统计结果文件配置
# =========================================================

LANDCOVER_STATISTICS_DIR = Path(
    os.getenv(
        "LANDCOVER_STATISTICS_DIR",
        r"D:\huanghe-data-display\04_processed_data\remote_sensing"
        r"\landcover_huanghe\statistics",
    )
)

LANDCOVER_STATISTICS_LONG_CSV = (
    LANDCOVER_STATISTICS_DIR
    / "landcover_area_statistics_all_years_long.csv"
)

LANDCOVER_STATISTICS_WIDE_CSV = (
    LANDCOVER_STATISTICS_DIR
    / "landcover_area_statistics_all_years_wide.csv"
)
