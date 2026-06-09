# -*- coding: utf-8 -*-
from io import BytesIO
from pathlib import Path

from PIL import Image
from rio_tiler.errors import TileOutsideBounds
from rio_tiler.io import Reader

from app.core.config import get_landcover_cog_path
from app.styles.landcover_colormap import LANDCOVER_COLORMAP


class LandcoverTileService:
    @staticmethod
    def get_cog_path(year: int) -> Path:
        cog_path = get_landcover_cog_path(year)

        if not cog_path.exists():
            raise FileNotFoundError(
                f"{year} 骞村湡鍦拌鐩?COG 鏂囦欢涓嶅瓨鍦細{cog_path}"
            )

        return cog_path

    @staticmethod
    def render_tile(year: int, z: int, x: int, y: int) -> bytes:
        cog_path = LandcoverTileService.get_cog_path(year)

        try:
            with Reader(str(cog_path)) as cog:
                image = cog.tile(x, y, z)
                return image.render(
                    img_format="PNG",
                    colormap=LANDCOVER_COLORMAP,
                )
        except TileOutsideBounds as exc:
            raise ValueError(
                f"鐡︾墖瓒呭嚭 {year} 骞村湡鍦拌鐩栧浘灞傝寖鍥达細z={z}, x={x}, y={y}"
            ) from exc

    @staticmethod
    def render_empty_tile(size: int = 256) -> bytes:
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()
