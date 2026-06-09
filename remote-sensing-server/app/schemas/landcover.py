# -*- coding: utf-8 -*-
"""
土地覆盖遥感模块接口返回结构
"""

from pydantic import BaseModel


class LandcoverYearsResponse(BaseModel):
    """
    可用土地覆盖年份响应
    """
    years: list[int]


class LandcoverLegendItem(BaseModel):
    """
    单个土地覆盖图例项
    """
    code: int
    name: str
    color: str


class LandcoverLegendResponse(BaseModel):
    """
    土地覆盖图例响应
    """
    legend: list[LandcoverLegendItem]
    

class LandcoverCompositionItem(BaseModel):
    """
    单个土地覆盖面积组成项
    """
    code: int
    name: str
    areaKm2: float
    percentage: float
    color: str


class LandcoverCompositionResponse(BaseModel):
    """
    某一年土地覆盖面积组成响应
    """
    year: int
    totalAreaKm2: float
    items: list[LandcoverCompositionItem]


class LandcoverTrendPoint(BaseModel):
    """
    土地覆盖趋势图中的单个年份点
    """
    year: int
    areaKm2: float
    percentage: float


class LandcoverTrendResponse(BaseModel):
    """
    某一地类多年变化趋势响应
    """
    code: int
    name: str
    color: str
    unit: str
    series: list[LandcoverTrendPoint]