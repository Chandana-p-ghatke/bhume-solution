#!/usr/bin/env python3
"""Boundary-aware plot correction.

This is intentionally a compact method, not a hand-tuned map:

1. Estimate the village-wide cadastre drift from the public example truths.
2. For every plot, search translations near that drift.
3. Prefer translations whose polygon outline falls on the rough boundary-hint raster.
4. Calibrate confidence from boundary support, peak sharpness, plot size, and agreement
   with the global drift. Weak/ambiguous cases are flagged and left at the official shape.
"""

from __future__ import annotations

import argparse
import math
import statistics
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from pyproj import Transformer
from scipy.ndimage import gaussian_filter
from shapely.affinity import translate
from shapely.geometry import LineString, MultiLineString
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shp_transform

from bhume import load, score, write_predictions


@dataclass
class ShiftModel:
    dx: float
    dy: float
    residual_m: float
    search_m: float


def utm_for(geom: BaseGeometry) -> str:
    lon = geom.centroid.x
    return f"EPSG:{32600 + int((lon + 180) // 6) + 1}"


def estimate_shift(village) -> ShiftModel:
    if village.example_truths is None:
        raise ValueError("example_truths.geojson is needed to estimate the village drift")

    crs = utm_for(village.example_truths.geometry.iloc[0])
    official = village.plots.to_crs(crs)
    truth = village.example_truths.to_crs(crs)

    dxs, dys = [], []
    for plot_number in truth.index:
        if plot_number not in official.index:
            continue
        oc = official.loc[plot_number, "geometry"].centroid
        tc = truth.loc[plot_number, "geometry"].centroid
        dxs.append(tc.x - oc.x)
        dys.append(tc.y - oc.y)

    if not dxs:
        raise ValueError("no overlapping example truths")

    dx = statistics.median(dxs)
    dy = statistics.median(dys)
    residuals = [math.hypot(x - dx, y - dy) for x, y in zip(dxs, dys)]
    residual_m = statistics.median(residuals) if residuals else 0.0
    search_m = min(28.0, max(8.0, residual_m * 2.5 + 6.0))
    return ShiftModel(dx=dx, dy=dy, residual_m=residual_m, search_m=search_m)


def densify_lines(geom: BaseGeometry, spacing_m: float) -> tuple[np.ndarray, np.ndarray]:
    boundary = geom.boundary
    lines: list[LineString] = []
    if isinstance(boundary, LineString):
        lines = [boundary]
    elif isinstance(boundary, MultiLineString):
        lines = list(boundary.geoms)
    else:
        lines = [g for g in getattr(boundary, "geoms", []) if isinstance(g, LineString)]

    xs, ys = [], []
    for line in lines:
        if line.length <= 0:
            continue
        n = max(8, int(math.ceil(line.length / spacing_m)))
        for d in np.linspace(0, line.length, n, endpoint=False):
            p = line.interpolate(float(d))
            xs.append(p.x)
            ys.append(p.y)
    return np.asarray(xs), np.asarray(ys)


def candidate_shifts(model: ShiftModel, resolution_m: float) -> list[tuple[float, float]]:
    coarse_step = max(3.0, resolution_m * 3.0)
    fine_step = max(1.2, resolution_m * 1.25)
    coarse = np.arange(-model.search_m, model.search_m + 0.01, coarse_step)
    fine = np.arange(-coarse_step, coarse_step + 0.01, fine_step)

    shifts = {(round(model.dx + float(x), 3), round(model.dy + float(y), 3)) for x in coarse for y in coarse}
    shifts.update((round(model.dx + float(x), 3), round(model.dy + float(y), 3)) for x in fine for y in fine)
    shifts.add((round(model.dx, 3), round(model.dy, 3)))
    return sorted(shifts)


def score_shift(
    response: np.ndarray,
    transform,
    xs: np.ndarray,
    ys: np.ndarray,
    dx: float,
    dy: float,
) -> float:
    inv = ~transform
    cols, rows = inv * (xs + dx, ys + dy)
    rows = np.rint(rows).astype(np.int32)
    cols = np.rint(cols).astype(np.int32)
    ok = (rows >= 0) & (rows < response.shape[0]) & (cols >= 0) & (cols < response.shape[1])
    if ok.mean() < 0.85:
        return -1.0
    vals = response[rows[ok], cols[ok]]
    return float(vals.mean() * ok.mean())


def confidence_for(
    best_score: float,
    second_score: float,
    best_dx: float,
    best_dy: float,
    model: ShiftModel,
    area_m2: float,
) -> float:
    peak_gap = max(0.0, best_score - second_score)
    support = min(1.0, best_score / 0.24)
    distinct = min(1.0, peak_gap / 0.025)
    drift_agreement = math.exp(-math.hypot(best_dx - model.dx, best_dy - model.dy) / max(6.0, model.search_m))
    size_term = min(1.0, max(0.35, math.sqrt(max(area_m2, 1.0)) / 85.0))
    conf = 0.12 + 0.38 * support + 0.25 * distinct + 0.15 * drift_agreement + 0.10 * size_term
    return round(max(0.0, min(0.98, conf)), 3)


def predict(village_dir: str | Path) -> gpd.GeoDataFrame:
    village = load(village_dir)
    model = estimate_shift(village)
    metric_crs = utm_for(village.plots.geometry.iloc[0])
    plots_m = village.plots.to_crs(metric_crs)

    if village.boundaries_path is None:
        shifted = plots_m.copy()
        shifted["geometry"] = shifted.geometry.apply(lambda g: translate(g, model.dx, model.dy))
        out = shifted.to_crs("EPSG:4326")
        out["status"] = "corrected"
        out["confidence"] = 0.45
        out["method_note"] = f"global shift only dx={model.dx:.1f}m dy={model.dy:.1f}m"
        return out[["plot_number", "status", "confidence", "method_note", "geometry"]]

    with rasterio.open(village.boundaries_path) as src:
        hints = src.read(1).astype(np.float32) / 255.0
        response = gaussian_filter(hints, sigma=1.6)
        response = response / max(float(response.max()), 1e-6)
        to_hint = Transformer.from_crs(metric_crs, src.crs, always_xy=True)
        shifts = candidate_shifts(model, abs(src.res[0]))

        rows = []
        for plot_number, row in plots_m.iterrows():
            geom_m = row.geometry
            geom_h = shp_transform(lambda x, y, z=None: to_hint.transform(x, y), geom_m)
            xs, ys = densify_lines(geom_h, spacing_m=max(2.0, abs(src.res[0]) * 2.0))
            if len(xs) < 8:
                status = "flagged"
                geom_out = village.plots.loc[plot_number, "geometry"]
                conf = None
                note = "flagged: too few boundary samples"
            else:
                scores = [(score_shift(response, src.transform, xs, ys, dx, dy), dx, dy) for dx, dy in shifts]
                scores.sort(reverse=True)
                best, second = scores[0], scores[1] if len(scores) > 1 else (-1.0, model.dx, model.dy)
                best_score, best_dx, best_dy = best
                conf = confidence_for(best_score, second[0], best_dx, best_dy, model, float(geom_m.area))

                if conf < 0.48 or best_score < 0.065:
                    status = "flagged"
                    geom_out = village.plots.loc[plot_number, "geometry"]
                    conf = None
                    note = f"flagged: weak/ambiguous boundary support score={best_score:.3f}"
                else:
                    status = "corrected"
                    corrected_m = translate(geom_m, best_dx, best_dy)
                    geom_out = gpd.GeoSeries([corrected_m], crs=metric_crs).to_crs("EPSG:4326").iloc[0]
                    note = (
                        f"local boundary shift dx={best_dx:.1f}m dy={best_dy:.1f}m "
                        f"score={best_score:.3f} gap={best_score - second[0]:.3f}"
                    )

            rows.append(
                {
                    "plot_number": str(plot_number),
                    "status": status,
                    "confidence": conf,
                    "method_note": note,
                    "geometry": geom_out,
                }
            )

    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("village_dir", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    preds = predict(args.village_dir)
    out = write_predictions(args.out or args.village_dir / "predictions.geojson", preds)
    print(f"wrote {len(preds)} predictions -> {out}")

    village = load(args.village_dir)
    if village.example_truths is not None:
        print(score(preds, village))


if __name__ == "__main__":
    main()
