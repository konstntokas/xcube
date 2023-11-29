# The MIT License (MIT)
# Copyright (c) 2023 by the xcube team and contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.
import os
import re
import tempfile
from typing import Mapping, Sequence, Optional, Any, Literal, NamedTuple, Union

import numpy as np
import pyproj
import xarray as xr

from xcube.core.gridmapping import GridMapping
from xcube.core.resampling import resample_in_space
from xcube.server.api import ApiError
from xcube.util.timeindex import ensure_time_index_compatible
from xcube.webapi.datasets.context import DatasetsContext
from xcube.webapi.ows.coverages.util import CoveragesRequest


def get_coverage_as_json(ctx: DatasetsContext, collection_id: str):
    """
    Return a JSON representation of the specified coverage

    Currently, the range set component is omitted.

    :param ctx: a dataset context
    :param collection_id: the ID of the collection providing the coverage
    :return: a JSON representation of the coverage
    """
    return {
        'id': collection_id,
        'type': 'CoverageByDomainAndRange',
        'envelope': get_collection_envelope(ctx, collection_id),
        'domainSet': get_coverage_domainset(ctx, collection_id),
        'rangeSet': {
            'type': 'RangeSet',
            # TODO: Wait for next update to API specification before
            #  implementing the data block -- not clear yet whether this
            #  is being deprecated along with the rangeSet endpoint.
            'dataBlock': {'type': 'VDataBlock', 'values': ['TODO']},
        },
        'rangeType': get_coverage_rangetype(ctx, collection_id),
        'metadata': get_collection_metadata(ctx, collection_id),
    }


def get_coverage_data(
    ctx: DatasetsContext,
    collection_id: str,
    query: Mapping[str, Sequence[str]],
    content_type: str,
) -> tuple[Optional[bytes], list[float], pyproj.CRS]:
    """
    Return coverage data from a dataset

    This method currently returns coverage data from a dataset as either
    TIFF or NetCDF. The bbox, datetime, and properties parameters are
    currently handled.

    :param ctx: a datasets context
    :param collection_id: the dataset from which to return the coverage
    :param query: the HTTP query parameters
    :param content_type: the MIME type of the desired output format
    :return: the coverage as bytes in the requested output format, or None
             if the requested output format is not supported
    """

    ds = get_dataset(ctx, collection_id)

    try:
        request = CoveragesRequest(query)
    except ValueError as e:
        raise ApiError.BadRequest(str(e))

    # See https://docs.ogc.org/DRAFTS/19-087.html
    native_crs = get_crs_from_dataset(ds)
    final_crs = request.crs if request.crs is not None else native_crs
    bbox_crs = request.bbox_crs
    subset_crs = request.subset_crs

    if request.properties is not None:
        requested_vars = set(request.properties)
        data_vars = set(map(str, ds.data_vars))
        unrecognized_vars = requested_vars - data_vars
        if unrecognized_vars == set():
            ds = ds.drop_vars(
                list(data_vars - requested_vars - {'crs', 'spatial_ref'})
            )
        else:
            raise ApiError.BadRequest(
                f'The following properties are not present in the coverage '
                f'{collection_id}: {", ".join(unrecognized_vars)}'
            )

    if request.datetime is not None:
        if 'time' not in ds.variables:
            raise ApiError.BadRequest(
                f'"datetime" parameter invalid for coverage "{collection_id}",'
                'which has no "time" dimension.'
            )
        if isinstance(request.datetime, tuple):
            time_slice = slice(*request.datetime)
            time_slice = ensure_time_index_compatible(ds, time_slice)
            ds = ds.sel(time=time_slice)
        else:
            timespec = ensure_time_index_compatible(ds, request.datetime)
            ds = ds.sel(time=timespec, method='nearest').squeeze()

    if request.subset is not None:
        subset_bbox, ds = _apply_subsetting(ds, request.subset, subset_crs)
    else:
        subset_bbox = None

    if request.bbox is not None:
        ds = _apply_bbox(ds, request.bbox, bbox_crs)

    # ds.rio.write_crs(get_crs_from_dataset(ds), inplace=True)

    _assert_coverage_size_ok(ds)

    source_gm = GridMapping.from_dataset(ds, crs=get_crs_from_dataset(ds))
    target_gm = None

    if get_crs_from_dataset(ds) != final_crs:
        target_gm = source_gm.transform(final_crs).to_regular()
    if request.scale_factor is not None:
        if target_gm is None:
            target_gm = source_gm
        target_gm = target_gm.scale(request.scale_factor)
    if request.scale_axes is not None:
        # TODO implement scale-axes
        raise ApiError.NotImplemented(
            'The scale-axes parameter is not yet supported.'
        )
    if request.scale_size:
        # TODO implement scale-size
        raise ApiError.NotImplemented(
            'The scale-size parameter is not yet supported.'
        )

    if target_gm is not None:
        ds = resample_in_space(ds, source_gm=source_gm, target_gm=target_gm)

    # In this case, the transformed native CRS bbox[es] may have been
    # too big, so we re-crop in the final CRS.
    if native_crs != final_crs and request.bbox is not None:
        ds = _apply_bbox(ds, request.bbox, bbox_crs)
    if subset_bbox is not None:
        ds = _apply_bbox(ds, subset_bbox, subset_crs)

    # TODO rename axes to match final CRS?

    media_types = dict(
        tiff={'geotiff', 'image/tiff', 'application/x-geotiff'},
        png={'png', 'image/png'},
        netcdf={'netcdf', 'application/netcdf', 'application/x-netcdf'},
    )
    if content_type in media_types['tiff']:
        content = dataset_to_image(ds, 'tiff')
    elif content_type in media_types['png']:
        content = dataset_to_image(ds, 'png')
    elif content_type in media_types['netcdf']:
        content = dataset_to_netcdf(ds)
    else:
        # It's expected that the caller (server API handler) will catch
        # unhandled types, but we may as well do the right thing if any
        # do slip through.
        raise ApiError.UnsupportedMediaType(
            f'Unsupported media type {content_type}. '
            + 'Available media types: '
            + ', '.join(
                [type_ for value in media_types.values() for type_ in value]
            )
        )
    final_bbox = get_bbox_from_ds(ds)
    if not is_xy(final_crs):
        final_bbox = final_bbox[1], final_bbox[0], final_bbox[3], final_bbox[2]
    return content, final_bbox, final_crs


def _assert_coverage_size_ok(ds):
    size_limit = 4000 * 4000  # TODO make this configurable
    h_dim = _get_h_dim(ds)
    v_dim = _get_v_dim(ds)
    for d in h_dim, v_dim:
        size = ds.dims[d]
        if size == 0:
            # Requirement 8C currently specifies a 204 rather than 404 here,
            # but spec will soon be updated to allow 404 as an alternative.
            # (J. Jacovella-St-Louis, pers. comm., 2023-11-27).
            raise ApiError.NotFound(
                f'Requested coverage contains no data: {d} has zero size.'
            )
    if (h_size := ds.dims[h_dim]) * (y_size := ds.dims[v_dim]) > size_limit:
        raise ApiError.ContentTooLarge(
            f'Requested coverage is too large:'
            f'{h_size} × {y_size} > {size_limit}.'
        )


_IndexerTuple = NamedTuple(
    'Indexers',
    [
        ('indices', dict[str, Any]),  # non-geographic single-valued specifiers
        ('slices', dict[str, slice]),  # non-geographic range specifiers
        ('x', Optional[Any]),  # x or longitude specifier (if any)
        ('y', Optional[Any]),  # y or latitude specifier (if any)
    ],
)


def _crs_axis_name_to_dim_name(axis_name: str, ds: xr.Dataset) -> str:
    # The spec says "The axis name SHALL correspond to one of the axis [sic]
    # of the Coordinate Reference System (CRS) of the coverage", but does not
    # define in what manner it must "correspond". The most practical solution
    # (especially since many CRSs in the wild don't define axis names) seems
    # to be to be as liberal as possible in try to interpret an axis
    # specifier, falling back on the name itself if its entry in the CRS
    # is uninformative or absent.

    crs = get_crs_from_dataset(ds)
    axis = _get_crs_axis_by_name(crs, axis_name)

    if axis is not None:
        abbrev = axis.abbrev[:3].lower()
        if abbrev in {'x', 'e', 'lon'}:
            return _get_h_dim(ds)
        if abbrev in {'y', 'n', 'lat'}:
            return _get_v_dim(ds)

        name = axis.name.lower()
        if name in {'easting', 'geocentric x'}:
            return _get_h_dim(ds)
        if name in {'northing', 'geocentric y'}:
            return _get_v_dim(ds)

        direction = axis.direction.lower()
        if direction == 'east':
            return _get_h_dim(ds)
        if direction == 'north':
            return _get_v_dim(ds)

    # If we can't find or parse the axis, we check the provided name against
    # some commonly used names to decide whether it's horizontal or vertical.

    if axis_name[:3].lower() in {'x', 'e', 'lon', 'eas'}:
        return _get_h_dim(ds)
    if axis_name[:3].lower() in {'y', 'n', 'lat', 'nor'}:
        return _get_v_dim(ds)

    # As a final fallback, we look for a dimension with the supplied name
    # -- first case-sensitive, then case-insensitive.

    if axis_name in ds.dims:
        return axis_name
    for d in ds.dims:
        if str(d).lower() == axis_name.lower():
            return str(d)

    raise ApiError.BadRequest(
        f"Couldn't find a dataset dimension "
        f'corresponding to the axis "{axis_name}".'
    )


def _get_crs_axis_by_name(crs: pyproj.CRS, name: str):
    for axis in crs.axis_info:
        if axis.abbrev == name or axis.name == name:
            return axis
    return None


def _apply_subsetting(
    ds: xr.Dataset, subset_spec: dict, subset_crs: pyproj.CRS
) -> tuple[list[float], xr.Dataset]:
    indexers = _parse_subset_specifier(subset_spec, ds)

    # TODO: for geographic subsetting, also handle single-value (non-slice)
    #  indices and half-open slices.

    bbox = None
    if (indexers.x, indexers.y) != (None, None):
        bbox, ds = _apply_geographic_subsetting(ds, subset_crs, indexers)
    if indexers.slices:
        ds = ds.sel(indexers=indexers.slices)
    if indexers.indices:
        ds = ds.sel(indexers=indexers.indices, method='nearest')

    return bbox, ds


def _apply_geographic_subsetting(
    ds, subset_crs, indexers
) -> tuple[list[float], xr.Dataset]:
    # 1. transform native extent to a whole-dataset bbox in subset_crs.
    # We'll use this to fill in "full extent" values if geographic
    # subsetting is only specified in one dimension.
    full_bbox_native = get_bbox_from_ds(ds)
    native_crs = get_crs_from_dataset(ds)
    full_bbox_subset_crs = _transform_bbox(
        full_bbox_native, native_crs, subset_crs
    )

    # 2. Find horizontal and/or vertical ranges in indexers, falling back to
    # values from whole-dataset bbox if a complete bbox is not specified.
    h_range = (
        indexers.x
        if indexers.x is not None
        else slice(full_bbox_subset_crs[0], full_bbox_subset_crs[2])
    )
    v_range = (
        indexers.y
        if indexers.y is not None
        else slice(full_bbox_subset_crs[1], full_bbox_subset_crs[3])
    )

    # 3. Using the ranges determined from the indexers and whole-dataset bbox,
    # construct the requested bbox in the subsetting CRS.
    bbox_subset_crs = [
        h_range.start,
        v_range.start,
        h_range.stop,
        v_range.stop,
    ]

    # 4. Transform requested bbox from subsetting CRS to dataset-native CRS.
    bbox_native_crs = _transform_bbox(bbox_subset_crs, subset_crs, native_crs)

    # 6. Apply the dataset-native bbox using sel.
    h_dim = _get_h_dim(ds)
    v_dim = _get_v_dim(ds)
    ds = ds.sel(
        indexers={
            h_dim: slice(bbox_native_crs[0], bbox_native_crs[2]),
            v_dim: slice(
                *_correct_inverted_y_range(
                    ds, v_dim, (bbox_native_crs[1], bbox_native_crs[3])
                )
            ),
        }
    )
    return bbox_subset_crs, ds


def get_bbox_from_ds(ds: xr.Dataset):
    h, v = ds[_get_h_dim(ds)], ds[_get_v_dim(ds)]
    bbox = list(map(float, [h[0], v[0], h[-1], v[-1]]))
    _ensure_bbox_y_ascending(bbox)
    return bbox


def _find_geographic_parameters(
    names: list[str],
) -> tuple[Optional[str], Optional[str]]:
    x, y = None, None
    for name in names:
        if name.lower()[:3] in ['x', 'e', 'eas', 'lon']:
            x = name
        if name.lower()[:3] in ['y', 'n', 'nor', 'lat']:
            y = name
    return x, y


def _transform_bbox(
    bbox: list[float], source_crs: pyproj.CRS, dest_crs: pyproj.CRS
) -> list[float]:
    if source_crs == dest_crs:
        return bbox
    else:
        transformer = pyproj.Transformer.from_crs(
            source_crs, dest_crs, always_xy=True
        )
        bbox_ = bbox.copy()
        _ensure_bbox_y_ascending(bbox_)
        return list(transformer.transform_bounds(*bbox_))


def _apply_bbox(ds: xr.Dataset, bbox: list[float], bbox_crs: pyproj.CRS):
    crs_ds = get_crs_from_dataset(ds)

    # TODO: refactor -- use _transform_bbox
    if crs_ds != bbox_crs:
        transformer = pyproj.Transformer.from_crs(
            bbox_crs, crs_ds, always_xy=True
        )
        _ensure_bbox_y_ascending(bbox)
        bbox = transformer.transform_bounds(*bbox)
    h_dim = _get_h_dim(ds)
    v_dim = _get_v_dim(ds)
    v_slice = _correct_inverted_y_range(ds, v_dim, (bbox[1], bbox[3]))
    ds = ds.sel({h_dim: slice(bbox[0], bbox[2]), v_dim: slice(*v_slice)})
    return ds


def _ensure_bbox_y_ascending(bbox: list):
    if bbox[1] > bbox[3]:
        bbox[1], bbox[3] = bbox[3], bbox[1]


def _get_h_dim(ds: xr.Dataset):
    return [
        d for d in list(map(str, ds.dims)) if d[:3].lower() in {'x', 'lon'}
    ][0]


def _get_v_dim(ds: xr.Dataset):
    return [
        d for d in list(map(str, ds.dims)) if d[:3].lower() in {'y', 'lat'}
    ][0]


def _reproject_if_needed(ds: xr.Dataset, target_crs: str):
    source_crs = get_crs_from_dataset(ds)
    if source_crs == pyproj.CRS(target_crs):
        return ds
    else:
        source_gm = GridMapping.from_dataset(ds).to_regular()
        target_gm_irregular = source_gm.transform(target_crs)
        target_gm = target_gm_irregular.to_regular()
        ds = resample_in_space(ds, source_gm=source_gm, target_gm=target_gm)
        if 'crs' not in ds.variables:
            ds['crs'] = 0
        ds.crs.attrs['spatial_ref'] = target_crs
        return ds


def _parse_subset_specifier(
        subset_spec: dict[str, Union[str, tuple[Optional[str], Optional[str]]]],
        ds: xr.Dataset) -> _IndexerTuple:
    specifiers = {}
    for axis, value in subset_spec.items():
        # First try matching with quotation marks
        if isinstance(value, str):
            if axis == 'time':
                specifiers[axis] = ensure_time_index_compatible(ds, value)
            else:
                try:
                    # Parse to float if possible
                    specifiers[axis] = float(value)
                except ValueError:
                    specifiers[axis] = value
        else:
            low, high = value
            low = None if low == '*' else low
            high = None if high == '*' else high
            if axis == 'time':
                specifiers[axis] = ensure_time_index_compatible(
                    ds, slice(low, high)
                )
            else:
                # TODO Handle non-float arguments
                low = float(low)
                high = float(high)
                low, high = _correct_inverted_y_range(
                    ds, _crs_axis_name_to_dim_name(axis, ds), (low, high)
                )
                specifiers[axis] = slice(low, high)

    # Find and extract geographic parameters, if any. These have to be
    # handled specially, since they refer to axis names in the subsetting
    # CRS rather than dimension names in the dataset.
    x_param, y_param = _find_geographic_parameters(list(specifiers))
    x_value = specifiers.pop(x_param) if x_param is not None else None
    y_value = specifiers.pop(y_param) if y_param is not None else None

    # Separate index and slice (i.e. single-value and range) specifiers
    indices = {k: v for k, v in specifiers.items() if not isinstance(v, slice)}
    slices = {k: v for k, v in specifiers.items() if isinstance(v, slice)}

    return _IndexerTuple(indices, slices, x_value, y_value)


def _correct_inverted_y_range(
    ds: xr.Dataset, axis: str, range_: tuple[float, float]
) -> tuple[float, float]:
    x0, x1 = range_
    # Make sure latitude slice direction matches axis direction.
    # (For longitude, a descending-order slice is valid.)
    if (
        None not in range_
        and axis[:3].lower() in {'lat', 'nor', 'y'}
        and (x0 < x1) != (ds[axis][0] < ds[axis][-1])
    ):
        x0, x1 = x1, x0
    return x0, x1


def dataset_to_image(
    ds: xr.Dataset, image_format: Literal['png', 'tiff'] = 'png'
) -> bytes:
    """
    Return an in-memory bitmap (TIFF or PNG) representing a dataset

    :param ds: a dataset
    :param image_format: image format to generate ("png" or "tiff")
    :return: TIFF-formatted bytes representing the dataset
    """

    if image_format == 'png':
        for var in ds.data_vars:
            # rasterio's PNG driver only supports these data types.
            if ds[var].dtype not in {np.uint8, np.uint16}:
                ds[var] = ds[var].astype(np.uint16, casting='unsafe')

    ds = ds.squeeze()

    with tempfile.TemporaryDirectory() as tempdir:
        path = os.path.join(tempdir, 'out.' + image_format)
        ds = ds.drop_vars(
            names=['crs', 'spatial_ref'], errors='ignore'
        ).squeeze()
        if len(ds.data_vars) == 1:
            ds[list(ds.data_vars)[0]].rio.to_raster(path)
        else:
            ds.rio.to_raster(path)
        with open(path, 'rb') as fh:
            data = fh.read()
    return data


def dataset_to_netcdf(ds: xr.Dataset) -> bytes:
    """
    Return an in-memory NetCDF representing a dataset

    :param ds: a dataset
    :return: NetCDF-formatted bytes representing the dataset
    """
    with tempfile.TemporaryDirectory() as tempdir:
        path = os.path.join(tempdir, 'out.nc')
        ds.to_netcdf(path)
        with open(path, 'rb') as fh:
            data = fh.read()
    return data


def get_coverage_domainset(ctx: DatasetsContext, collection_id: str):
    """
    Return the domain set of a dataset-backed coverage

    The domain set is the set of input parameters (e.g. geographical extent,
    time span) for which a coverage is defined.

    :param ctx: a datasets context
    :param collection_id: the dataset for which to return the domain set
    :return: a dictionary representing an OGC API - Coverages domain set
    """
    ds = get_dataset(ctx, collection_id)
    grid_limits = dict(
        type='GridLimits',
        srsName=f'http://www.opengis.net/def/crs/OGC/0/Index{len(ds.dims)}D',
        axisLabels=list(ds.dims),
        axis=[_get_grid_limits_axis(ds, dim) for dim in ds.dims],
    )
    grid = dict(
        type='GeneralGridCoverage',
        srsName=get_crs_from_dataset(ds).to_string(),
        axisLabels=list(ds.dims.keys()),
        axis=_get_axes_properties(ds),
        gridLimits=grid_limits,
    )
    return dict(type='DomainSet', generalGrid=grid)


def get_collection_metadata(ctx: DatasetsContext, collection_id: str):
    """
    Return a metadata dictionary for a dataset

    The metadata is taken directly from the dataset attributes.

    :param ctx: a datasets context
    :param collection_id: the dataset for which to return the metadata
    :return: a dictionary of metadata keys and values
    """
    ds = get_dataset(ctx, collection_id)
    return ds.attrs


def get_dataset(ctx: DatasetsContext, collection_id: str):
    """
    Get a dataset from a datasets context

    :param ctx: a datasets context
    :param collection_id: the ID of a dataset in the context
    :return: the dataset
    """
    ml_dataset = ctx.get_ml_dataset(collection_id)
    ds = ml_dataset.get_dataset(0)
    assert isinstance(ds, xr.Dataset)
    return ds


def _get_axes_properties(ds: xr.Dataset) -> list[dict]:
    return [_get_axis_properties(ds, dim) for dim in ds.dims]


def _get_axis_properties(ds: xr.Dataset, dim: str) -> dict[str, Any]:
    axis = ds.coords[dim]
    if np.issubdtype(axis.dtype, np.datetime64):
        lower_bound = np.datetime_as_string(axis[0])
        upper_bound = np.datetime_as_string(axis[-1])
    else:
        lower_bound, upper_bound = axis[0].item(), axis[-1].item()
    return dict(
        type='RegularAxis',
        axisLabel=dim,
        lowerBound=lower_bound,
        upperBound=upper_bound,
        resolution=abs((axis[-1] - axis[0]).item() / len(axis)),
        uomLabel=get_units(ds, dim),
    )


def _get_grid_limits_axis(ds: xr.Dataset, dim: str) -> dict[str, Any]:
    return dict(
        type='IndexAxis', axisLabel=dim, lowerBound=0, upperBound=len(ds[dim])
    )


def get_units(ds: xr.Dataset, dim: str) -> str:
    coord = ds.coords[dim]
    if hasattr(coord, 'attrs') and 'units' in coord.attrs:
        return coord.attrs['units']
    if np.issubdtype(coord, np.datetime64):
        return np.datetime_data(coord)[0]
    # TODO: as a fallback for spatial axes, we could try matching dimensions
    #  to CRS axes and take the unit from the CRS definition.
    return 'unknown'


def get_crs_from_dataset(ds: xr.Dataset) -> pyproj.CRS:
    """
    Return the CRS of a dataset as a string. The CRS is taken from the
    metadata of the crs or spatial_ref variables, if available.
    "EPSG:4326" is used as a fallback.

    :param ds: a dataset
    :return: a string representation of the dataset's CRS, or "EPSG:4326"
             if the CRS cannot be determined
    """
    for var_name in 'crs', 'spatial_ref':
        if var_name in ds.variables:
            var = ds[var_name]
            for attr_name in 'spatial_ref', 'crs_wkt':
                if attr_name in var.attrs:
                    crs_string = ds[var_name].attrs[attr_name]
                    return pyproj.CRS(crs_string)
    return pyproj.CRS('EPSG:4326')


def get_coverage_rangetype(
    ctx: DatasetsContext, collection_id: str
) -> dict[str, list]:
    """
    Return the range type of a dataset

    The range type describes the data types of the dataset's variables
    """
    ds = get_dataset(ctx, collection_id)
    result = dict(type='DataRecord', field=[])
    for var_name in ds.data_vars:
        result['field'].append(
            dict(
                type='Quantity',
                name=var_name,
                description=get_dataarray_description(ds[var_name]),
                encodingInfo=dict(
                    dataType=dtype_to_opengis_datatype(ds[var_name].dtype)
                ),
            )
        )
    return result


def dtype_to_opengis_datatype(dt: np.dtype) -> str:
    """
    Convert a NumPy dtype to an equivalent OpenGIS type identifier string.

    :param dt: a NumPy dtype
    :return: an equivalent OpenGIS type identifier string, or an empty string
             if the dtype is not recognized
    """
    nbits = 8 * np.dtype(dt).itemsize
    int_size_map = {8: 'Byte', 16: 'Short', 32: 'Int', 64: 'Long'}
    prefix = 'http://www.opengis.net/def/dataType/OGC/0/'
    if np.issubdtype(dt, np.floating):
        opengis_type = f'{prefix}float{nbits}'
    elif np.issubdtype(dt, np.signedinteger):
        opengis_type = f'{prefix}signed{int_size_map[nbits]}'
    elif np.issubdtype(dt, np.unsignedinteger):
        opengis_type = f'{prefix}unsigned{int_size_map[nbits]}'
    elif 'datetime64' in str(dt):
        opengis_type = 'http://www.opengis.net/def/bipm/UTC'
    else:
        opengis_type = ''  # TODO decide what to do in this case
    return opengis_type


def get_dataarray_description(da: xr.DataArray) -> str:
    """
    Return a string describing a DataArray, either from an attribute or,
    as a fallback, from its name attribute.

    :param da: a DataArray
    :return: a string describing the DataArray
    """
    if hasattr(da, 'attrs'):
        for attr in ['description', 'long_name', 'standard_name', 'name']:
            if attr in da.attrs:
                return da.attrs[attr]
    return str(da.name)


def get_collection_envelope(ds_ctx, collection_id):
    """
    Return the OGC API - Coverages envelope of a dataset.

    The envelope comprises the extents of all the dataset's dimensions.

    :param ds_ctx: a datasets context
    :param collection_id: a dataset ID within the given context
    :return: the envelope of the specified dataset
    """
    ds = get_dataset(ds_ctx, collection_id)
    return {
        'type': 'EnvelopeByAxis',
        'srsName': get_crs_from_dataset(ds).to_string(),
        'axisLabels': list(ds.dims.keys()),
        'axis': _get_axes_properties(ds),
    }


def is_xy(crs: pyproj.CRS) -> bool:
    """Try to determine whether a CRS has x-y axis order"""
    x_index = None
    y_index = None
    x_re = re.compile('^x|lon|east', flags=re.IGNORECASE)
    y_re = re.compile('^y|lat|north', flags=re.IGNORECASE)

    for i, axis in enumerate(crs.axis_info):
        for prop in 'name', 'abbrev', 'direction':
            if x_re.search(getattr(axis, prop)):
                x_index = i
            elif y_re.search(getattr(axis, prop)):
                y_index = i

    if x_index is not None and y_index is not None:
        return x_index < y_index
    else:
        return True  # assume xy
