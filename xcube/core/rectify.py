# The MIT License (MIT)
# Copyright (c) 2020 by the xcube development team and contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of
# this software and associated documentation files (the "Software"), to deal in
# the Software without restriction, including without limitation the rights to
# use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
# of the Software, and to permit persons to whom the Software is furnished to do
# so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
import math
from typing import Mapping, Optional, Sequence, Tuple, Union

import dask.array as da
import numba as nb
import numpy as np
import xarray as xr

from xcube.core.geocoding import GeoCoding
from xcube.core.imgeom import ImageGeom
from xcube.core.select import select_spatial_subset
from xcube.util.dask import compute_array_from_func


def rectify_dataset(dataset: xr.Dataset,
                    var_names: Union[str, Sequence[str]] = None,
                    geo_coding: GeoCoding = None,
                    xy_names: Tuple[str, str] = None,
                    output_geom: ImageGeom = None,
                    is_y_axis_inverted: bool = False,
                    tile_size: Union[int, Tuple[int, int]] = None,
                    load_xy: bool = False,
                    load_vars: bool = False,
                    compute_subset: bool = True,
                    uv_delta: float = 1e-3) -> Optional[xr.Dataset]:
    """
    Reproject *dataset* using its per-pixel x,y coordinates or the given *geo_coding*.

    The function expects *dataset* to have either one- or two-dimensional coordinate variables
    that provide spatial x,y coordinates for every data variable with the same spatial dimensions.

    For example, a dataset may comprise variables with spatial dimensions ``var(..., y_dim, x_dim)``, then one
    the function expects coordinates to be provided in two forms:

    1. One-dimensional ``x_var(x_dim)`` and ``y_var(y_dim)`` (coordinate) variables.
    2. Two-dimensional ``x_var(y_dim, x_dim)`` and ``y_var(y_dim, x_dim)`` (coordinate) variables.

    If *output_geom* is given and defines a tile size or *tile_size* is given, and the number of tiles
    is greater than one in the output's x- or y-direction, then the returned dataset will be composed of lazy,
    chunked dask arrays. Otherwise the returned dataset will be composed of ordinary numpy arrays.

    :param dataset: Source dataset.
    :param var_names: Optional variable name or sequence of variable names.
    :param geo_coding: Optional dataset geo-coding.
    :param xy_names: Optional tuple of the x- and y-coordinate variables in *dataset*. Ignored if *geo_coding* is given.
    :param output_geom: Optional output geometry. If not given, output geometry will be computed
        to spatially fit *dataset* and to retain its spatial resolution.
    :param is_y_axis_inverted: Whether the y-axis labels in the output should be in inverse order.
    :param tile_size: Optional tile size for the output.
    :param load_xy: Compute x,y coordinates and load into memory before the actual rectification process.
        May improve runtime performance at the cost of higher memory consumption.
    :param load_vars: Compute source variables and load into memory before the actual rectification process.
        May improve runtime performance at the cost of higher memory consumption.
    :param uv_delta: A normalized value that is used to determine whether x,y coordinates in the output are contained
        in the triangles defined by the input x,y coordinates.
        The higher this value, the more inaccurate the rectification will be.
    :return: a reprojected dataset, or None if the requested output does not intersect with *dataset*.
    """
    src_geo_coding = geo_coding if geo_coding is not None else GeoCoding.from_dataset(dataset, xy_names=xy_names)
    src_x, src_y = src_geo_coding.xy
    src_attrs = dict(dataset.attrs)

    if output_geom is None:
        output_geom = ImageGeom.from_dataset(dataset, geo_coding=src_geo_coding)
    elif compute_subset:
        dataset_subset = select_spatial_subset(dataset,
                                               xy_bbox=output_geom.xy_bbox,
                                               ij_border=1,
                                               xy_border=output_geom.xy_res,
                                               geo_coding=src_geo_coding)
        if dataset_subset is None:
            return None
        if dataset_subset is not dataset:
            src_geo_coding = GeoCoding.from_dataset(dataset_subset)
            src_x, src_y = src_geo_coding.x, src_geo_coding.y
            dataset = dataset_subset

    if tile_size is not None:
        output_geom = output_geom.derive(tile_size=tile_size)

    src_vars = select_variables(dataset, var_names, geo_coding=src_geo_coding)

    if load_xy:
        # This is NOT faster:
        src_x = src_x.compute()
        src_y = src_y.compute()
        src_geo_coding = src_geo_coding.derive(x=src_x, y=src_y)

    if output_geom.is_tiled:
        get_dst_src_ij_array = _get_dst_src_ij_array_dask
        get_dst_var_array = _get_dst_var_array_dask
    else:
        get_dst_src_ij_array = _get_dst_src_ij_array_numpy
        get_dst_var_array = _get_dst_var_array_numpy

    dst_src_ij_array = get_dst_src_ij_array(src_geo_coding,
                                            output_geom,
                                            is_y_axis_inverted,
                                            uv_delta)

    dst_dims = src_geo_coding.xy_names[::-1]
    dst_ds_coords = output_geom.coord_vars(xy_names=src_geo_coding.xy_names,
                                           is_lon_normalized=src_geo_coding.is_lon_normalized,
                                           is_y_axis_inverted=is_y_axis_inverted)
    dst_vars = dict()
    for src_var_name, src_var in src_vars.items():
        if load_vars:
            # This is NOT faster:
            src_var = src_var.compute()

        dst_var_dims = src_var.dims[0:-2] + dst_dims
        dst_var_coords = {d: src_var.coords[d] for d in dst_var_dims if d in src_var.coords}
        dst_var_coords.update({d: dst_ds_coords[d] for d in dst_var_dims if d in dst_ds_coords})
        dst_var_array = get_dst_var_array(src_var,
                                          dst_src_ij_array,
                                          fill_value=np.nan)
        dst_var = xr.DataArray(dst_var_array,
                               dims=dst_var_dims,
                               coords=dst_var_coords,
                               attrs=src_var.attrs)
        dst_vars[src_var_name] = dst_var
    return xr.Dataset(dst_vars, coords=dst_ds_coords, attrs=src_attrs)


def _get_dst_src_ij_array_numpy(src_geo_coding: GeoCoding,
                                output_geom: ImageGeom,
                                is_dst_y_axis_inverted: bool,
                                uv_delta: float) -> np.ndarray:
    dst_width = output_geom.width
    dst_height = output_geom.height
    dst_shape = 2, dst_height, dst_width
    dst_src_ij_values = np.full(dst_shape, np.nan, dtype=np.float64)
    dst_x_min = output_geom.x_min
    dst_y_min = output_geom.y_min
    dst_xy_res = output_geom.xy_res
    _compute_source_pixels(src_geo_coding.x.values,
                           src_geo_coding.y.values,
                           0,
                           0,
                           dst_src_ij_values,
                           dst_x_min,
                           dst_y_min,
                           dst_xy_res,
                           uv_delta=uv_delta)
    if is_dst_y_axis_inverted:
        dst_src_ij_values = dst_src_ij_values[:, ::-1, :]
    return dst_src_ij_values


def _get_dst_src_ij_array_dask(src_geo_coding: GeoCoding,
                               output_geom: ImageGeom,
                               is_dst_y_axis_inverted: bool,
                               uv_delta: float) -> da.Array:
    dst_width = output_geom.width
    dst_height = output_geom.height
    dst_tile_width = output_geom.tile_width
    dst_tile_height = output_geom.tile_height
    dst_var_shape = 2, dst_height, dst_width
    dst_var_chunks = 2, dst_tile_height, dst_tile_width

    dst_x_min = output_geom.x_min
    dst_y_min = output_geom.y_min
    dst_xy_res = output_geom.xy_res

    dst_xy_bboxes = output_geom.xy_bboxes
    src_ij_bboxes = src_geo_coding.ij_bboxes(dst_xy_bboxes, xy_border=dst_xy_res, ij_border=1)

    return compute_array_from_func(_compute_source_pixels_block,
                                   dst_var_shape,
                                   dst_var_chunks,
                                   np.float64,
                                   ctx_arg_names=[
                                       'dtype',
                                       'block_id',
                                       'block_shape',
                                       'block_slices',
                                   ],
                                   args=(
                                       src_geo_coding.x,
                                       src_geo_coding.y,
                                       src_ij_bboxes,
                                       dst_x_min,
                                       dst_y_min,
                                       dst_xy_res,
                                       is_dst_y_axis_inverted,
                                       uv_delta
                                   ),
                                   name='ij_pixels',
                                   )


def _get_dst_var_array_numpy(src_var: xr.DataArray,
                             dst_src_ij_array: np.ndarray,
                             fill_value: Union[int, float, complex] = np.nan) -> np.ndarray:
    return _get_dst_var_array_numpy_numba(src_var.values, dst_src_ij_array, fill_value)


@nb.njit(nogil=True, cache=True)
def _get_dst_var_array_numpy_numba(src_var: np.ndarray,
                                   dst_src_ij_array: np.ndarray,
                                   fill_value: Union[int, float, complex] = np.nan) -> np.ndarray:
    dst_width = dst_src_ij_array.shape[-1]
    dst_height = dst_src_ij_array.shape[-2]
    dst_shape = src_var.shape[:-2] + (dst_height, dst_width)
    dst_values = np.full(dst_shape, fill_value, dtype=src_var.dtype)
    _extract_source_pixels(src_var,
                           dst_src_ij_array,
                           dst_values)
    return dst_values


def _get_dst_var_array_dask(src_var: xr.DataArray,
                            dst_src_ij_array: np.ndarray,
                            fill_value: Union[int, float, complex] = np.nan) -> da.Array:
    return da.map_blocks(_get_dst_var_array_numpy_numba,
                         src_var.values,
                         dst_src_ij_array,
                         fill_value,
                         dtype=src_var.dtype,
                         drop_axis=0)


def _compute_source_pixels_block(dtype: np.dtype,
                                 block_id: int,
                                 block_shape: Tuple[int, int],
                                 block_slices: Tuple[Tuple[int, int], Tuple[int, int], Tuple[int, int]],
                                 src_x: xr.DataArray,
                                 src_y: xr.DataArray,
                                 src_ij_bboxes: np.ndarray,
                                 dst_x_min: float,
                                 dst_y_min: float,
                                 dst_xy_res: float,
                                 is_dst_y_axis_inverted: bool,
                                 uv_delta: float) -> np.ndarray:
    dst_src_ij_block = np.full(block_shape, np.nan, dtype=dtype)
    _, (dst_y_slice_start, _), (dst_x_slice_start, _) = block_slices
    src_ij_bbox = src_ij_bboxes[block_id]
    src_i_min, src_j_min, src_i_max, src_j_max = src_ij_bbox
    if src_i_min == -1:
        return dst_src_ij_block
    src_x_values = src_x[src_j_min:src_j_max + 1, src_i_min:src_i_max + 1].values
    src_y_values = src_y[src_j_min:src_j_max + 1, src_i_min:src_i_max + 1].values
    _compute_source_pixels(src_x_values,
                           src_y_values,
                           src_i_min,
                           src_j_min,
                           dst_src_ij_block,
                           dst_x_min + dst_x_slice_start * dst_xy_res,
                           dst_y_min + dst_y_slice_start * dst_xy_res,
                           dst_xy_res,
                           uv_delta)
    if is_dst_y_axis_inverted:
        dst_src_ij_block = dst_src_ij_block[:, ::-1, :]
    return dst_src_ij_block


def select_variables(dataset,
                     var_names: Union[str, Sequence[str]] = None,
                     geo_coding: GeoCoding = None,
                     xy_names: Tuple[str, str] = None) -> Mapping[str, xr.DataArray]:
    """
    Select variables from *dataset*.

    :param dataset: Source dataset.
    :param var_names: Optional variable name or sequence of variable names.
    :param geo_coding: Optional dataset geo-coding.
    :param xy_names: Optional tuple of the x- and y-coordinate variables in *dataset*. Ignored if *geo_coding* is given.
    :return: The selected variables as a variable name to ``xr.DataArray`` mapping
    """
    geo_coding = geo_coding if geo_coding is not None else GeoCoding.from_dataset(dataset, xy_names=xy_names)
    src_x = geo_coding.x
    x_name, y_name = geo_coding.xy_names
    if var_names is None:
        var_names = [var_name for var_name, var in dataset.data_vars.items()
                     if var_name not in (x_name, y_name) and _is_2d_var(var, src_x)]
    elif isinstance(var_names, str):
        var_names = (var_names,)
    elif len(var_names) == 0:
        raise ValueError(f'empty var_names')
    src_vars = {}
    for var_name in var_names:
        src_var = dataset[var_name]
        if not _is_2d_var(src_var, src_x):
            raise ValueError(
                f"cannot reproject variable {var_name!r} as its shape or dimensions "
                f"do not match those of {x_name!r} and {y_name!r}")
        src_vars[var_name] = src_var
    return src_vars


def _is_2d_var(var: xr.DataArray, two_d_coord_var: xr.DataArray) -> bool:
    return var.ndim >= 2 and var.shape[-2:] == two_d_coord_var.shape and var.dims[-2:] == two_d_coord_var.dims


@nb.njit(nogil=True, cache=True)
def _compute_source_pixels(src_x: np.ndarray,
                           src_y: np.ndarray,
                           src_i_min: int,
                           src_j_min: int,
                           dst_src_ij: np.ndarray,
                           dst_x0: float,
                           dst_y0: float,
                           dst_res: float,
                           uv_delta: float = 1e-3):
    src_width = src_x.shape[-1]
    src_height = src_x.shape[-2]

    dst_width = dst_src_ij.shape[-1]
    dst_height = dst_src_ij.shape[-2]

    dst_px = np.zeros(4, dtype=src_x.dtype)
    dst_py = np.zeros(4, dtype=src_y.dtype)

    dst_src_ij[:, :, :] = np.nan

    u_min = v_min = -uv_delta
    uv_max = 1.0 + 2 * uv_delta

    for src_j0 in range(src_height - 1):
        for src_i0 in range(src_width - 1):
            src_i1 = src_i0 + 1
            src_j1 = src_j0 + 1

            dst_px[0] = dst_p0x = src_x[src_j0, src_i0]
            dst_px[1] = dst_p1x = src_x[src_j0, src_i1]
            dst_px[2] = dst_p2x = src_x[src_j1, src_i0]
            dst_px[3] = dst_p3x = src_x[src_j1, src_i1]

            dst_py[0] = dst_p0y = src_y[src_j0, src_i0]
            dst_py[1] = dst_p1y = src_y[src_j0, src_i1]
            dst_py[2] = dst_p2y = src_y[src_j1, src_i0]
            dst_py[3] = dst_p3y = src_y[src_j1, src_i1]

            dst_pi = np.floor((dst_px - dst_x0) / dst_res).astype(np.int64)
            dst_pj = np.floor((dst_py - dst_y0) / dst_res).astype(np.int64)

            dst_i_min = np.min(dst_pi)
            dst_i_max = np.max(dst_pi)
            dst_j_min = np.min(dst_pj)
            dst_j_max = np.max(dst_pj)

            if dst_i_max < 0 \
                    or dst_j_max < 0 \
                    or dst_i_min >= dst_width \
                    or dst_j_min >= dst_height:
                continue

            if dst_i_min < 0:
                dst_i_min = 0

            if dst_i_max >= dst_width:
                dst_i_max = dst_width - 1

            if dst_j_min < 0:
                dst_j_min = 0

            if dst_j_max >= dst_height:
                dst_j_max = dst_height - 1

            # u from p0 right to p1, v from p0 down to p2
            det_a = _fdet(dst_p0x, dst_p0y, dst_p1x, dst_p1y, dst_p2x, dst_p2y)
            # u from p3 left to p2, v from p3 up to p1
            det_b = _fdet(dst_p3x, dst_p3y, dst_p2x, dst_p2y, dst_p1x, dst_p1y)

            if np.isnan(det_a) or np.isnan(det_b):
                # print('no plane at:', src_i0, src_j0)
                continue

            for dst_j in range(dst_j_min, dst_j_max + 1):
                dst_y = dst_y0 + (dst_j + 0.5) * dst_res
                for dst_i in range(dst_i_min, dst_i_max + 1):
                    dst_x = dst_x0 + (dst_i + 0.5) * dst_res

                    # TODO: use two other combinations,
                    #       if one of the dst_px<n>,dst_py<n> pairs is missing.

                    src_i = src_j = -1

                    if det_a != 0.0:
                        u = _fu(dst_x, dst_y, dst_p0x, dst_p0y, dst_p2x, dst_p2y) / det_a
                        v = _fv(dst_x, dst_y, dst_p0x, dst_p0y, dst_p1x, dst_p1y) / det_a
                        if u >= u_min and v >= v_min and u + v <= uv_max:
                            src_i = src_i0 + _fclamp(u, 0.0, 1.0)
                            src_j = src_j0 + _fclamp(v, 0.0, 1.0)
                    if src_i == -1 and det_b != 0.0:
                        u = _fu(dst_x, dst_y, dst_p3x, dst_p3y, dst_p1x, dst_p1y) / det_b
                        v = _fv(dst_x, dst_y, dst_p3x, dst_p3y, dst_p2x, dst_p2y) / det_b
                        if u >= u_min and v >= v_min and u + v <= uv_max:
                            src_i = src_i1 - _fclamp(u, 0.0, 1.0)
                            src_j = src_j1 - _fclamp(v, 0.0, 1.0)
                    if src_i != -1:
                        dst_src_ij[0, dst_j, dst_i] = src_i_min + src_i
                        dst_src_ij[1, dst_j, dst_i] = src_j_min + src_j


@nb.njit(nogil=True, cache=True)
def _extract_source_pixels(src_values: np.ndarray,
                           dst_src_ij: np.ndarray,
                           dst_values: np.ndarray):
    src_width = src_values.shape[-1]
    src_height = src_values.shape[-2]

    dst_width = dst_values.shape[-1]
    dst_height = dst_values.shape[-2]

    src_i_min = 0
    src_j_min = 0
    src_i_max = src_width - 1
    src_j_max = src_height - 1

    for dst_j in range(dst_height):
        for dst_i in range(dst_width):
            src_i_f = dst_src_ij[0, dst_j, dst_i]
            src_j_f = dst_src_ij[1, dst_j, dst_i]
            if np.isnan(src_i_f) or np.isnan(src_j_f):
                continue
            src_i = math.floor(src_i_f + 0.49999)
            src_j = math.floor(src_j_f + 0.49999)
            u = src_i_f - src_i
            v = src_j_f - src_j
            if u > 0.5:
                src_i = _iclamp(src_i + 1, src_i_min, src_i_max)
            if v > 0.5:
                src_j = _iclamp(src_j + 1, src_j_min, src_j_max)
            dst_values[..., dst_j, dst_i] = src_values[..., src_j, src_i]


@nb.njit('float64(float64, float64, float64, float64, float64, float64)', nogil=True, inline='always')
def _fdet(px0: float, py0: float, px1: float, py1: float, px2: float, py2: float) -> float:
    return (px0 - px1) * (py0 - py2) - (px0 - px2) * (py0 - py1)


@nb.njit('float64(float64, float64, float64, float64, float64, float64)', nogil=True, inline='always')
def _fu(px: float, py: float, px0: float, py0: float, px2: float, py2: float) -> float:
    return (px0 - px) * (py0 - py2) - (py0 - py) * (px0 - px2)


@nb.njit('float64(float64, float64, float64, float64, float64, float64)', nogil=True, inline='always')
def _fv(px: float, py: float, px0: float, py0: float, px1: float, py1: float) -> float:
    return (py0 - py) * (px0 - px1) - (px0 - px) * (py0 - py1)


@nb.njit('float64(float64, float64, float64)', nogil=True, inline='always')
def _fclamp(x: float, x_min: float, x_max: float) -> float:
    return x_min if x < x_min else (x_max if x > x_max else x)


@nb.njit('int64(int64, int64, int64)', nogil=True, inline='always')
def _iclamp(x: int, x_min: int, x_max: int) -> int:
    return x_min if x < x_min else (x_max if x > x_max else x)


def _millis(seconds: float) -> int:
    return round(1000 * seconds)