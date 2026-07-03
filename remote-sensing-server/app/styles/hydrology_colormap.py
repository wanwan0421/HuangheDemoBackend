"""
Hydrology raster color styling and legend metadata.
"""

from __future__ import annotations

import numpy as np


# Fixed classes so the whole map keeps a stable visual meaning.
# The first matching upper bound wins.
RUNOFF_CLASSES = [
    {"max": 0.0, "label": "0", "color": "#D6EFFF", "rgb": (214, 239, 255)},
    {"max": 50.0, "label": "50", "color": "#2F80ED", "rgb": (47, 128, 237)},
    {"max": 100.0, "label": "100", "color": "#27AE60", "rgb": (39, 174, 96)},
    {"max": 300.0, "label": "300", "color": "#F2C94C", "rgb": (242, 201, 76)},
    {"max": 1000.0, "label": "1000", "color": "#F2994A", "rgb": (242, 153, 74)},
    {"max": 3000.0, "label": "3000", "color": "#EB5757", "rgb": (235, 87, 87)},
    {"max": float("inf"), "label": ">3000", "color": "#C0392B", "rgb": (192, 57, 43)},
]

RUNOFF_LEGEND = {
    "title": "月平均径流量",
    "unit": "mm/day",
    "items": [
        {"label": item["label"], "color": item["color"]}
        for item in RUNOFF_CLASSES[:-1]
    ],
    "lowLabel": "低",
    "highLabel": "高",
}


def colorize_runoff(band: np.ndarray, valid_mask: np.ndarray) -> np.ndarray:
    """
    Convert runoff values to a fixed RGB class map.
    """
    rgb = np.zeros((3, *band.shape), dtype=np.uint8)

    if not np.any(valid_mask):
        return rgb

    for runoff_class in RUNOFF_CLASSES:
        class_mask = valid_mask & (band <= runoff_class["max"])
        if not np.any(class_mask):
            continue

        for channel_index, channel_value in enumerate(runoff_class["rgb"]):
            rgb[channel_index] = np.where(
                class_mask,
                channel_value,
                rgb[channel_index],
            )

        valid_mask = valid_mask & ~class_mask
        if not np.any(valid_mask):
            break

    return rgb
