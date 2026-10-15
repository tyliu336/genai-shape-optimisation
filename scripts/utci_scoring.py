"""Score a folder of UTCI heatmap images.

The crop boxes are based on the images used in this project. If the Grasshopper
export size changes, update LEGEND_BBOX and DATA_BBOX before running the script.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
import pandas as pd


LEGEND_BBOX = (1787, 112, 1848, 1240)
DATA_BBOX = (678, 579, 1357, 969)
UTCI_MIN = 5.94
UTCI_MAX = 8.38
TARGET_COMFORT = 15.0
HOT_THRESHOLD = 7.10


def crop(image: np.ndarray, bbox: tuple[int, int, int, int]) -> np.ndarray:
    x1, y1, x2, y2 = bbox
    return image[y1:y2, x1:x2]


def extract_legend(image_rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    legend = crop(image_rgb, LEGEND_BBOX)
    rows = []
    for row in legend:
        non_white = np.linalg.norm(row - 255, axis=1) > 30
        rows.append(np.mean(row[non_white] if non_white.any() else row, axis=0))

    colors = np.asarray(rows, dtype=np.float32)
    red = np.array([220, 60, 40])
    if np.linalg.norm(colors[0] - red) < np.linalg.norm(colors[-1] - red):
        values = np.linspace(UTCI_MAX, UTCI_MIN, len(colors))
    else:
        values = np.linspace(UTCI_MIN, UTCI_MAX, len(colors))
    return colors, values.astype(np.float32)


def heatmap_values(
    image_bgr: np.ndarray,
    legend_colors: np.ndarray,
    legend_values: np.ndarray,
) -> tuple[np.ndarray, tuple[int, int]]:
    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    data = crop(image_rgb, DATA_BBOX)
    pixels = data.reshape(-1, 3).astype(np.float32)
    nearest_parts = []
    for start in range(0, len(pixels), 4096):
        block = pixels[start : start + 4096]
        distances = np.linalg.norm(
            block[:, None, :] - legend_colors[None, :, :], axis=2
        )
        nearest_parts.append(np.argmin(distances, axis=1))
    nearest = np.concatenate(nearest_parts)
    return legend_values[nearest], data.shape[:2]


def normalize(values: np.ndarray) -> np.ndarray:
    minimum, maximum = np.min(values), np.max(values)
    if abs(maximum - minimum) < 1e-6:
        return np.ones_like(values)
    return (values - minimum) / (maximum - minimum)


def score_folder(input_dir: Path, output_csv: Path) -> pd.DataFrame:
    files = sorted(
        path
        for path in input_dir.iterdir()
        if path.suffix.lower() in {".png", ".jpg", ".jpeg"}
    )
    if not files:
        raise ValueError(f"No heatmap images found in {input_dir}")

    first = cv2.imread(str(files[0]))
    if first is None:
        raise ValueError(f"Could not read {files[0]}")
    legend_colors, legend_values = extract_legend(
        cv2.cvtColor(first, cv2.COLOR_BGR2RGB)
    )

    records = []
    comfort_distance = []
    hotspot_ratio = []
    spatial_change = []

    for path in files:
        image = cv2.imread(str(path))
        if image is None:
            continue
        values, (height, width) = heatmap_values(
            image, legend_colors, legend_values
        )
        grid = values.reshape(height, width)
        gradient_x = cv2.Sobel(grid, cv2.CV_32F, 1, 0, ksize=3)
        gradient_y = cv2.Sobel(grid, cv2.CV_32F, 0, 1, ksize=3)

        mean_utci = float(np.mean(values))
        comfort_distance.append(abs(mean_utci - TARGET_COMFORT))
        hotspot_ratio.append(float(np.mean(values > HOT_THRESHOLD)))
        spatial_change.append(float(np.mean(np.abs(gradient_x) + np.abs(gradient_y))))
        records.append({"image": path.name, "utci_mean": mean_utci})

    s1 = 1 - normalize(np.asarray(comfort_distance))
    s2 = 1 - normalize(np.asarray(hotspot_ratio))
    s3 = 1 - normalize(np.asarray(spatial_change))

    result = pd.DataFrame(records)
    result["comfort_score"] = s1
    result["hotspot_score"] = s2
    result["smoothness_score"] = s3
    result["final_score"] = 0.5 * s1 + 0.3 * s2 + 0.2 * s3
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_csv, index=False, encoding="utf-8-sig")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output_csv", type=Path)
    args = parser.parse_args()
    print(score_folder(args.input_dir, args.output_csv).to_string(index=False))


if __name__ == "__main__":
    main()
