# -*- coding: utf-8 -*-
"""
Hydrology runoff tile APIs.
"""

from pathlib import Path
import csv
import os
import re

import numpy as np
from fastapi import APIRouter, HTTPException, Response
from rio_tiler.errors import TileOutsideBounds
from rio_tiler.io import Reader
from rio_tiler.utils import render

from app.styles.hydrology_colormap import RUNOFF_LEGEND, colorize_runoff


router = APIRouter(
    prefix="/hydrology",
    tags=["水文径流监测"],
)


RUNOFF_COG_DIR = Path(
    os.getenv(
        "RUNOFF_COG_DIR",
        r"D:\huanghe-data-display\04_processed_data\hydrology\03_monthly_mean_cog",
    )
)

RUNOFF_STATISTICS_CSV = Path(
    os.getenv(
        "RUNOFF_STATISTICS_CSV",
        r"D:\huanghe-data-display\04_processed_data\hydrology\statistics\runoff_monthly_statistics.csv",
    )
)


def parse_year_month_from_name(file_path: Path):
    """
    Parse year and month from file names like:
    runoff_1979_01.tif
    yr_1979_01.tif
    runoff-1979-01.tif
    """
    name = file_path.stem
    match = re.search(r"(19\d{2}|20\d{2})[_-]?(\d{2})", name)

    if not match:
        return None, None

    year = int(match.group(1))
    month = int(match.group(2))

    if month < 1 or month > 12:
        return None, None

    return year, month


def find_runoff_cog(year: int, month: int) -> Path:
    for tif_path in RUNOFF_COG_DIR.rglob("*.tif"):
        file_year, file_month = parse_year_month_from_name(tif_path)
        if file_year == year and file_month == month:
            return tif_path

    raise HTTPException(
        status_code=404,
        detail=f"没有找到 {year} 年 {month:02d} 月的径流 COG 文件",
    )


@router.get("/years", summary="获取可用径流年份")
def get_runoff_years():
    years = set()

    if not RUNOFF_COG_DIR.exists():
        raise HTTPException(
            status_code=500,
            detail=f"径流 COG 目录不存在：{RUNOFF_COG_DIR}",
        )

    for tif_path in RUNOFF_COG_DIR.rglob("*.tif"):
        year, _ = parse_year_month_from_name(tif_path)
        if year is not None:
            years.add(year)

    return {"years": sorted(list(years))}


@router.get("/months/{year}", summary="获取某一年可用径流月份")
def get_runoff_months(year: int):
    months = set()

    if not RUNOFF_COG_DIR.exists():
        raise HTTPException(
            status_code=500,
            detail=f"径流 COG 目录不存在：{RUNOFF_COG_DIR}",
        )

    for tif_path in RUNOFF_COG_DIR.rglob("*.tif"):
        file_year, file_month = parse_year_month_from_name(tif_path)
        if file_year == year and file_month is not None:
            months.add(file_month)

    return {
        "year": year,
        "months": sorted(list(months)),
    }


@router.get("/statistics/{year}/{month}", summary="获取某年某月径流统计信息")
def get_runoff_statistics(year: int, month: int):
    if not RUNOFF_STATISTICS_CSV.exists():
        raise HTTPException(
            status_code=404,
            detail=f"径流统计表不存在：{RUNOFF_STATISTICS_CSV}",
        )

    with open(RUNOFF_STATISTICS_CSV, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        for row in reader:
            row_year = int(row.get("year", 0))
            row_month = int(row.get("month", 0))
            if row_year == year and row_month == month:
                return row

    raise HTTPException(
        status_code=404,
        detail=f"没有找到 {year} 年 {month:02d} 月的径流统计信息",
    )


@router.get("/legend", summary="获取径流图例")
def get_runoff_legend():
    return RUNOFF_LEGEND


@router.get(
    "/runoff/{year}/{month}/tiles/{z}/{x}/{y}.png",
    summary="获取径流量月平均栅格瓦片",
)
def get_runoff_tile(year: int, month: int, z: int, x: int, y: int):
    """
    Render monthly runoff as a bright pseudocolor raster tile.
    """
    cog_path = find_runoff_cog(year, month)

    try:
        with Reader(str(cog_path)) as src:
            tile = src.tile(x, y, z)
    except TileOutsideBounds:
        empty = np.zeros((1, 256, 256), dtype="uint8")
        image = render(
            empty,
            mask=np.zeros((256, 256), dtype="uint8"),
            img_format="PNG",
        )
        return Response(content=image, media_type="image/png")
    try:
        
        data = tile.data.astype("float32")
        mask = tile.mask
        band = data[0]
        valid = np.isfinite(band) & (mask > 0)

        if not np.any(valid):
            empty = np.zeros((1, 256, 256), dtype="uint8")
            image = render(
                empty,
                mask=np.zeros((256, 256), dtype="uint8"),
                img_format="PNG",
            )
            return Response(content=image, media_type="image/png")

        rgb = colorize_runoff(band, valid)

        image = render(
            rgb,
            mask=mask,
            img_format="PNG",
        )

        return Response(content=image, media_type="image/png")

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"生成径流瓦片失败：{str(e)}",
        )
