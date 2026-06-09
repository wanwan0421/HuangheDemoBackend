# -*- coding: utf-8 -*-
"""
土地覆盖遥感接口路由

提供：
1. 可用年份查询
2. 土地覆盖图例查询
3. 动态 PNG 瓦片查询
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.core.config import get_available_landcover_years
from app.schemas.landcover import (
    LandcoverYearsResponse,
    LandcoverLegendResponse,
    LandcoverCompositionResponse,
    LandcoverTrendResponse
)
from app.services.landcover_tile_service import LandcoverTileService
from app.styles.landcover_colormap import LANDCOVER_LEGEND
from app.services.landcover_statistics_service import (
    LandcoverStatisticsService,
)


router = APIRouter(
    prefix="/landcover",
    tags=["土地覆盖遥感监测"],
)


@router.get(
    "/years",
    response_model=LandcoverYearsResponse,
    summary="获取可用土地覆盖年份",
)
def get_landcover_years():
    """
    返回当前已经配置且 COG 文件存在的土地覆盖年份。
    """
    years = get_available_landcover_years()

    return {
        "years": years
    }


@router.get(
    "/legend",
    response_model=LandcoverLegendResponse,
    summary="获取土地覆盖分类图例",
)
def get_landcover_legend():
    """
    返回土地覆盖类别及其前端展示颜色。
    """
    return {
        "legend": LANDCOVER_LEGEND
    }


@router.get(
    "/statistics/{year}",
    response_model=LandcoverCompositionResponse,
    summary="获取指定年份土地覆盖面积组成",
)
def get_landcover_statistics_by_year(year: int):
    """
    返回指定年份的土地覆盖面积组成数据，
    用于前端环形图展示。
    """
    try:
        return LandcoverStatisticsService.get_year_composition(year)

    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc
    
@router.get(
    "/trend/{landcover_code}",
    response_model=LandcoverTrendResponse,
    summary="获取指定土地覆盖类型的多年面积变化趋势",
)
def get_landcover_trend(landcover_code: int):
    """
    返回某一土地覆盖类别的多年面积变化趋势，
    用于前端折线图展示。
    """
    try:
        return LandcoverStatisticsService.get_category_trend(
            landcover_code
        )

    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc   

@router.get(
    "/{year}/tiles/{z}/{x}/{y}.png",
    summary="获取指定年份土地覆盖动态瓦片",
)
def get_landcover_tile(
    year: int,
    z: int,
    x: int,
    y: int,
):
    """
    按年份和 XYZ 瓦片坐标，返回土地覆盖 PNG 瓦片。
    """
    try:
        png_bytes = LandcoverTileService.render_tile(
            year=year,
            z=z,
            x=x,
            y=y,
        )

        return Response(
            content=png_bytes,
            media_type="image/png",
        )

    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        return Response(
            content=LandcoverTileService.render_empty_tile(),
            media_type="image/png",
            headers={
                "X-Tile-Status": "empty",
                "Cache-Control": "public, max-age=300",
            },
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"土地覆盖瓦片生成失败：{exc}",
        ) from exc
