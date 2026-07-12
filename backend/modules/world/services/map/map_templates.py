from __future__ import annotations

import random
from typing import Any

# 默认地形
_BLANK_TERRAIN = "grassland"


def _generate_blank_tiles(width: int, height: int) -> list[dict[str, Any]]:
    """空白模板：全 grassland。"""
    return [
        {"hex_q": q, "hex_r": r, "terrain_type": _BLANK_TERRAIN, "elevation": 0}
        for q in range(width)
        for r in range(height)
    ]


def _generate_continent_tiles(width: int, height: int) -> list[dict[str, Any]]:
    """大陆模板：中心陆地 + 边缘水。

    简化算法：用到中心的距离判断，内部随机 grassland/forest，边缘 water。
    确定性（seed 固定）避免每次创建结果不同。
    """
    rng = random.Random(42)
    cx, cy = width / 2, height / 2
    max_dist = (width**2 + height**2) ** 0.5 / 2
    tiles: list[dict[str, Any]] = []
    for q in range(width):
        for r in range(height):
            dist = ((q - cx) ** 2 + (r - cy) ** 2) ** 0.5 / max_dist
            if dist > 0.85:
                terrain = "water"
            elif dist > 0.7:
                terrain = rng.choice(["water", "desert", "grassland"])
            elif dist < 0.2:
                terrain = rng.choice(["mountain", "forest"])
            else:
                terrain = rng.choice(["grassland", "forest", "grassland"])
            tiles.append(
                {"hex_q": q, "hex_r": r, "terrain_type": terrain, "elevation": 0}
            )
    return tiles


def _generate_islands_tiles(width: int, height: int) -> list[dict[str, Any]]:
    """群岛模板：散布小岛 + 大量水。"""
    rng = random.Random(7)
    tiles: list[dict[str, Any]] = []
    for q in range(width):
        for r in range(height):
            # 约 25% 陆地，散布成岛
            if rng.random() < 0.25:
                terrain = rng.choice(["grassland", "forest", "mountain"])
            else:
                terrain = "water"
            tiles.append(
                {"hex_q": q, "hex_r": r, "terrain_type": terrain, "elevation": 0}
            )
    return tiles


_TEMPLATES = {
    "blank": _generate_blank_tiles,
    "continent": _generate_continent_tiles,
    "islands": _generate_islands_tiles,
}


def generate_template_tiles(
    width: int,
    height: int,
    template: str | None,
) -> list[dict[str, Any]]:
    """按模板生成初始 tile。未知模板回退 blank。"""
    if template and template in _TEMPLATES:
        return _TEMPLATES[template](width, height)
    return _generate_blank_tiles(width, height)


def generate_detail_tiles(width: int, height: int) -> list[dict[str, Any]]:
    """详图快速生成：中心 3 圈 city + 外 1 圈 road + 其余随机 grassland/forest。

    以网格中心为圆心，用六边形距离（近似欧氏距离足够 P0）。
    """
    rng = random.Random(123)
    cx, cy = width / 2, height / 2
    city_radius = min(width, height) * 0.18  # 约 3 圈
    road_radius = city_radius * 1.4
    tiles: list[dict[str, Any]] = []
    for q in range(width):
        for r in range(height):
            dist = ((q - cx) ** 2 + (r - cy) ** 2) ** 0.5
            if dist <= city_radius:
                terrain = "city"
            elif dist <= road_radius:
                terrain = "road"
            else:
                terrain = rng.choice(["grassland", "forest"])
            tiles.append(
                {"hex_q": q, "hex_r": r, "terrain_type": terrain, "elevation": 0}
            )
    return tiles
