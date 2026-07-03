# -*- coding: utf-8 -*-
"""
土地覆盖统计数据服务

功能：
1. 读取土地覆盖面积统计长表 CSV
2. 提供指定年份的土地覆盖组成数据
3. 提供指定地类的多年面积变化趋势数据
"""

from functools import lru_cache

import pandas as pd

from app.core.config import (
    LANDCOVER_STATISTICS_LONG_CSV,
    LANDCOVER_CLASSES,
)
from app.styles.landcover_colormap import LANDCOVER_LEGEND


class LandcoverStatisticsService:
    """
    土地覆盖面积统计服务
    """

    @staticmethod
    @lru_cache(maxsize=1)
    def load_statistics_dataframe() -> pd.DataFrame:
        """
        读取土地覆盖统计长表。
        使用缓存，避免每个请求都重新读取 CSV。
        """
        if not LANDCOVER_STATISTICS_LONG_CSV.exists():
            raise FileNotFoundError(
                f"土地覆盖统计 CSV 不存在：{LANDCOVER_STATISTICS_LONG_CSV}"
            )

        df = pd.read_csv(LANDCOVER_STATISTICS_LONG_CSV)

        required_columns = {
            "year",
            "landcover_code",
            "landcover_name",
            "pixel_count",
            "area_km2",
            "percentage",
        }

        missing_columns = required_columns - set(df.columns)

        if missing_columns:
            raise ValueError(
                f"土地覆盖统计 CSV 缺少字段：{sorted(missing_columns)}"
            )

        return df

    @staticmethod
    def get_legend_color_map() -> dict[int, str]:
        """
        返回 code -> color 的映射。
        """
        return {
            item["code"]: item["color"]
            for item in LANDCOVER_LEGEND
        }

    @staticmethod
    def get_year_composition(year: int) -> dict:
        """
        获取指定年份土地覆盖面积组成。
        用于前端环形图。
        """
        df = LandcoverStatisticsService.load_statistics_dataframe()
        year_df = df[df["year"] == year].copy()

        if year_df.empty:
            raise KeyError(f"未找到 {year} 年土地覆盖统计数据")

        color_map = LandcoverStatisticsService.get_legend_color_map()

        year_df = year_df.sort_values("landcover_code")

        items = []

        for _, row in year_df.iterrows():
            code = int(row["landcover_code"])

            items.append({
                "code": code,
                "name": str(row["landcover_name"]),
                "areaKm2": round(float(row["area_km2"]), 2),
                "percentage": round(float(row["percentage"]), 2),
                "color": color_map.get(code, "#94A3B8"),
            })

        total_area_km2 = round(
            float(year_df["area_km2"].sum()),
            2
        )

        return {
            "year": year,
            "totalAreaKm2": total_area_km2,
            "items": items,
        }

    @staticmethod
    def get_category_trend(landcover_code: int) -> dict:
        """
        获取某一类土地覆盖的多年面积变化趋势。
        用于前端折线图。
        """
        if landcover_code not in LANDCOVER_CLASSES:
            raise KeyError(f"不存在的土地覆盖类别编码：{landcover_code}")

        df = LandcoverStatisticsService.load_statistics_dataframe()

        category_df = df[
            df["landcover_code"] == landcover_code
        ].copy()

        if category_df.empty:
            raise KeyError(
                f"未找到地类编码 {landcover_code} 的统计数据"
            )

        category_df = category_df.sort_values("year")

        series = []

        for _, row in category_df.iterrows():
            series.append({
                "year": int(row["year"]),
                "areaKm2": round(float(row["area_km2"]), 2),
                "percentage": round(float(row["percentage"]), 2),
            })

        color_map = LandcoverStatisticsService.get_legend_color_map()

        return {
            "code": landcover_code,
            "name": LANDCOVER_CLASSES[landcover_code],
            "color": color_map.get(landcover_code, "#2563EB"),
            "unit": "km²",
            "series": series,
        }