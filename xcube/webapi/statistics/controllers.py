from collections.abc import Mapping
from typing import Any

import numpy as np
import shapely

from xcube.constants import LOG
from xcube.core.geom import get_dataset_geometry
from xcube.core.geom import mask_dataset_by_geometry
from xcube.server.api import ApiError
from xcube.util.perf import measure_time_cm
from .context import StatisticsContext


NAN_RESULT = {
    "count": 0,
    "minimum": "nan",
    "maximum": "nan",
    "mean": "nan",
    "deviation": "nan",
}


def compute_statistics(
    ctx: StatisticsContext,
    ds_id: str,
    var_name: str,
    geo_json: dict[str, Any],
    params: Mapping[str, str],
):
    params = dict(params)
    time = params.pop("time")
    trace_perf = params.pop("debug", "1" if ctx.datasets_ctx.trace_perf else "0") == "1"
    measure_time = measure_time_cm(logger=LOG, disabled=not trace_perf)
    with measure_time("Computing statistics"):
        return _compute_statistics(ctx, ds_id, var_name, time, geo_json)


def _compute_statistics(
    ctx: StatisticsContext,
    ds_id: str,
    var_name: str,
    time: str,
    geo_json: dict[str, Any],
):
    ml_dataset = ctx.datasets_ctx.get_ml_dataset(ds_id)
    dataset = ml_dataset.get_dataset(0)
    grid_mapping = ml_dataset.grid_mapping

    try:
        geometry = shapely.geometry.shape(geo_json)
    except (TypeError, ValueError) as e:
        raise ApiError.BadRequest("Invalid GeoJSON geometry encountered") from e

    dataset = dataset.sel(time=time)

    x_name, y_name = grid_mapping.xy_dim_names
    if isinstance(geometry, shapely.geometry.Point):
        bounds = get_dataset_geometry(dataset)
        if not bounds.contains(geometry):
            return NAN_RESULT
        indexers = {x_name: geometry.x, y_name: geometry.y}
        dataset = dataset.sel(**indexers, method="Nearest")
        value = float(dataset[var_name].values)
        return {
            "count": 1,
            "minimum": value,
            "maximum": value,
            "mean": value,
            "deviation": 0.0,
        }

    dataset = mask_dataset_by_geometry(dataset, geometry)
    if dataset is None:
        return NAN_RESULT

    var = dataset[var_name]
    count = int(np.count_nonzero(~np.isnan(var)))
    if count == 0:
        return NAN_RESULT

    minimum = float(var.min())
    maximum = float(var.max())
    h_values, h_bins = np.histogram(var, 100, range=(minimum, maximum), density=True)

    return {
        "count": count,
        "minimum": minimum,
        "maximum": maximum,
        "mean": float(var.mean()),
        "deviation": float(var.std()),
        "histogram": {
            "values": [float(v) for v in h_values],
            "bins": [float(v) for v in h_bins],
        },
    }
