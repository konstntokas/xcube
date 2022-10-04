# The MIT License (MIT)
# Copyright (c) 2022 by the xcube development team and contributors
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

import unittest
from typing import Optional

import matplotlib.cm
import matplotlib.colors
import numpy as np
import pyproj
import xarray as xr

from xcube.core.mldataset import BaseMultiLevelDataset
from xcube.core.mldataset import MultiLevelDataset
from xcube.core.tile import compute_rgba_tile
from xcube.core.tile import compute_tiles
from xcube.core.tilingscheme import GEOGRAPHIC_CRS_NAME
from xcube.core.tilingscheme import WEB_MERCATOR_CRS_NAME
from xcube.util.cmaps import ColormapProvider

nan = np.nan


class ColormapProviderMock(ColormapProvider):

    def get_cmap(self,
                 cm_name: str,
                 num_colors: Optional[int] = None):
        return cm_name, matplotlib.cm.get_cmap(cm_name, lut=num_colors)


CMAP_PROVIDER = ColormapProviderMock()


class Tile2Test(unittest.TestCase):

    @staticmethod
    def _get_ml_dataset(crs_name: str) -> MultiLevelDataset:
        crs = pyproj.CRS.from_string(crs_name)
        geo_crs = pyproj.CRS.from_string(GEOGRAPHIC_CRS_NAME)
        transformer = pyproj.Transformer.from_crs(
            geo_crs, crs, always_xy=True
        )
        (x1, x2), (y1, y2) = transformer.transform(
            (-180, 180),
            (-85.051129, 85.051129)
        )

        data = np.array(
            [[
                [5, 1, 1, 1, 1, 2, 2, 2, 2, 6],
                [1, 5, 1, 1, 1, 2, 2, 2, 6, 2],
                [1, 1, 5, 1, 1, 2, 2, 6, 2, 2],
                [1, 1, 1, 5, 1, 2, 6, 2, 2, 2],
                [1, 1, 1, 1, 5, 6, 2, 2, 2, 2],
                [3, 3, 3, 3, 6, 5, 4, 4, 4, 4],
                [3, 3, 3, 6, 3, 4, 5, 4, 4, 4],
                [3, 3, 6, 3, 3, 4, 4, 5, 4, 4],
                [3, 6, 3, 3, 3, 4, 4, 4, 5, 4],
                [6, 3, 3, 3, 3, 4, 4, 4, 4, 5],
            ]],
            dtype=np.float32
        )
        a_data = np.where(data != 6, data + 0, np.nan)
        b_data = np.where(data != 5, data + 1, np.nan)
        c_data = np.where(data != 4, data + 2, np.nan)
        h, w = a_data.shape[-2:]
        res = (x2 - x1) / w
        x1 += 0.5 * res
        x2 -= 0.5 * res
        y1 += 0.5 * res
        y2 -= 0.5 * res

        var_a = xr.DataArray(a_data, dims=['time', 'y', 'x'])
        var_b = xr.DataArray(b_data, dims=['time', 'y', 'x'])
        var_c = xr.DataArray(c_data, dims=['time', 'y', 'x'])
        spatial_ref = xr.DataArray(
            0, attrs=pyproj.CRS.from_string(crs_name).to_cf()
        )

        ds = xr.Dataset(
            data_vars=dict(
                var_a=var_a,
                var_b=var_b,
                var_c=var_c,
                spatial_ref=spatial_ref
            ),
            coords=dict(
                time=xr.DataArray(np.array([0]), dims='time'),
                y=xr.DataArray(np.linspace(y1, y2, h), dims='y'),
                x=xr.DataArray(np.linspace(x1, x2, w), dims='x')
            )
        )
        # ds = ds.chunk(dict(x=4, y=3))
        return BaseMultiLevelDataset(ds)


class ComputeTilesTest(Tile2Test, unittest.TestCase):

    def test_compute_rgba_tile_with_color_mapping(self):
        crs_name = WEB_MERCATOR_CRS_NAME
        ml_ds = self._get_ml_dataset(crs_name)
        tiles = compute_tiles(
            ml_ds,
            ('var_a', 'var_b', 'var_c'),
            (-180, -90, 180, 90),
            tile_crs=GEOGRAPHIC_CRS_NAME,
            tile_size=10,
            level=0,
            non_spatial_labels={'time': 0},
            tile_enlargement=0
        )
        self.assertIsInstance(tiles, list)
        self.assertEqual(3, len(tiles))
        for i in range(3):
            self.assertIsInstance(tiles[i], np.ndarray)
            self.assertEqual(np.float32, tiles[i].dtype)
            self.assertEqual((10, 10), tiles[i].shape)
        np.testing.assert_equal(
            tiles[0],
            np.array(
                [
                    [5., 5., 1., 1., 1., 1., 2., 2., 2., nan],
                    [1., 1., 5., 1., 1., 1., 2., 2., nan, 2.],
                    [1., 1., 1., 5., 1., 1., 2., nan, 2., 2.],
                    [1., 1., 1., 5., 1., 1., 2., nan, 2., 2.],
                    [1., 1., 1., 1., 5., 5., nan, 2., 2., 2.],
                    [1., 1., 1., 1., 5., 5., nan, 2., 2., 2.],
                    [3., 3., 3., 3., nan, nan, 5., 4., 4., 4.],
                    [3., 3., 3., 3., nan, nan, 5., 4., 4., 4.],
                    [3., 3., 3., nan, 3., 3., 4., 5., 4., 4.],
                    [nan, nan, 3., 3., 3., 3., 4., 4., 4., 5.]
                ],
                dtype=np.float32
            )
        )
        np.testing.assert_equal(
            tiles[1],
            np.array(
                [
                    [nan, nan, 2., 2., 2., 2., 3., 3., 3., 7.],
                    [2., 2., nan, 2., 2., 2., 3., 3., 7., 3.],
                    [2., 2., 2., nan, 2., 2., 3., 7., 3., 3.],
                    [2., 2., 2., nan, 2., 2., 3., 7., 3., 3.],
                    [2., 2., 2., 2., nan, nan, 7., 3., 3., 3.],
                    [2., 2., 2., 2., nan, nan, 7., 3., 3., 3.],
                    [4., 4., 4., 4., 7., 7., nan, 5., 5., 5.],
                    [4., 4., 4., 4., 7., 7., nan, 5., 5., 5.],
                    [4., 4., 4., 7., 4., 4., 5., nan, 5., 5.],
                    [7., 7., 4., 4., 4., 4., 5., 5., 5., nan]
                ],
                dtype=np.float32
            )
        )
        np.testing.assert_equal(
            tiles[2],
            np.array(
                [
                    [7., 7., 3., 3., 3., 3., 4., 4., 4., 8.],
                    [3., 3., 7., 3., 3., 3., 4., 4., 8., 4.],
                    [3., 3., 3., 7., 3., 3., 4., 8., 4., 4.],
                    [3., 3., 3., 7., 3., 3., 4., 8., 4., 4.],
                    [3., 3., 3., 3., 7., 7., 8., 4., 4., 4.],
                    [3., 3., 3., 3., 7., 7., 8., 4., 4., 4.],
                    [5., 5., 5., 5., 8., 8., 7., nan, nan, nan],
                    [5., 5., 5., 5., 8., 8., 7., nan, nan, nan],
                    [5., 5., 5., 8., 5., 5., nan, 7., nan, nan],
                    [8., 8., 5., 5., 5., 5., nan, nan, nan, 7.]
                ],
                dtype=np.float32
            )
        )


class ComputeRgbaTileTest(Tile2Test, unittest.TestCase):

    def test_compute_rgba_tile_with_color_mapping(self):
        crs_name = WEB_MERCATOR_CRS_NAME
        ml_ds = self._get_ml_dataset(crs_name)
        args = [
            ml_ds,
            'var_a',
            0, 0, 0,
            CMAP_PROVIDER
        ]
        kwargs = dict(
            crs_name=crs_name,
            tile_size=10,
            cmap_name="gray",
            value_ranges=(0, 10),
            non_spatial_labels={'time': 0},
            tile_enlargement=0
        )
        tile = compute_rgba_tile(*args, **kwargs, format='numpy')
        self.assertIsInstance(tile, np.ndarray)
        self.assertEqual(np.uint8, tile.dtype)
        self.assertEqual((10, 10, 4), tile.shape)
        r = tile[:, :, 0]
        g = tile[:, :, 1]
        b = tile[:, :, 2]
        a = tile[:, :, 3]
        np.testing.assert_equal(
            r,
            np.array(
                [[0, 0, 76, 76, 76, 76, 102, 102, 102, 128],
                 [76, 76, 0, 76, 76, 76, 102, 102, 128, 102],
                 [76, 76, 76, 0, 76, 76, 102, 128, 102, 102],
                 [76, 76, 76, 76, 0, 0, 128, 102, 102, 102],
                 [25, 25, 25, 25, 128, 128, 0, 51, 51, 51],
                 [25, 25, 25, 25, 128, 128, 0, 51, 51, 51],
                 [25, 25, 25, 128, 25, 25, 51, 0, 51, 51],
                 [25, 25, 128, 25, 25, 25, 51, 51, 0, 51],
                 [128, 128, 25, 25, 25, 25, 51, 51, 51, 0],
                 [128, 128, 25, 25, 25, 25, 51, 51, 51, 0]],
                dtype=np.uint8
            )
        )
        np.testing.assert_equal(r, g)
        np.testing.assert_equal(r, b)
        np.testing.assert_equal(
            a,
            np.array(
                [[0, 0, 255, 255, 255, 255, 255, 255, 255, 255],
                 [255, 255, 0, 255, 255, 255, 255, 255, 255, 255],
                 [255, 255, 255, 0, 255, 255, 255, 255, 255, 255],
                 [255, 255, 255, 255, 0, 0, 255, 255, 255, 255],
                 [255, 255, 255, 255, 255, 255, 0, 255, 255, 255],
                 [255, 255, 255, 255, 255, 255, 0, 255, 255, 255],
                 [255, 255, 255, 255, 255, 255, 255, 0, 255, 255],
                 [255, 255, 255, 255, 255, 255, 255, 255, 0, 255],
                 [255, 255, 255, 255, 255, 255, 255, 255, 255, 0],
                 [255, 255, 255, 255, 255, 255, 255, 255, 255, 0]],
                dtype=np.uint8
            )
        )

        tile = compute_rgba_tile(*args, **kwargs, format='png')
        self.assertIsInstance(tile, bytes)

    def test_compute_rgba_tile_with_components(self):
        crs_name = WEB_MERCATOR_CRS_NAME
        ml_ds = self._get_ml_dataset(crs_name)
        args = [
            ml_ds,
            ('var_a', 'var_b', 'var_c'),
            0, 0, 0,
            CMAP_PROVIDER
        ]
        kwargs = dict(
            crs_name=crs_name,
            tile_size=10,
            value_ranges=(0, 10),
            non_spatial_labels={'time': 0},
            tile_enlargement=0
        )
        tile = compute_rgba_tile(*args, **kwargs, format='numpy')
        self.assertIsInstance(tile, np.ndarray)
        self.assertEqual(np.uint8, tile.dtype)
        self.assertEqual((10, 10, 4), tile.shape)
        r = tile[:, :, 0]
        g = tile[:, :, 1]
        b = tile[:, :, 2]
        a = tile[:, :, 3]
        np.testing.assert_equal(
            r,
            np.array(
                [[0, 0, 76, 76, 76, 76, 102, 102, 102, 127],
                 [76, 76, 0, 76, 76, 76, 102, 102, 127, 102],
                 [76, 76, 76, 0, 76, 76, 102, 127, 102, 102],
                 [76, 76, 76, 76, 0, 0, 127, 102, 102, 102],
                 [25, 25, 25, 25, 127, 127, 0, 51, 51, 51],
                 [25, 25, 25, 25, 127, 127, 0, 51, 51, 51],
                 [25, 25, 25, 127, 25, 25, 51, 0, 51, 51],
                 [25, 25, 127, 25, 25, 25, 51, 51, 0, 51],
                 [127, 127, 25, 25, 25, 25, 51, 51, 51, 0],
                 [127, 127, 25, 25, 25, 25, 51, 51, 51, 0]],
                dtype=np.uint8
            )
        )
        np.testing.assert_equal(
            g,
            np.array(
                [[178, 178, 102, 102, 102, 102, 127, 127, 127, 0],
                 [102, 102, 178, 102, 102, 102, 127, 127, 0, 127],
                 [102, 102, 102, 178, 102, 102, 127, 0, 127, 127],
                 [102, 102, 102, 102, 178, 178, 0, 127, 127, 127],
                 [51, 51, 51, 51, 0, 0, 178, 76, 76, 76],
                 [51, 51, 51, 51, 0, 0, 178, 76, 76, 76],
                 [51, 51, 51, 0, 51, 51, 76, 178, 76, 76],
                 [51, 51, 0, 51, 51, 51, 76, 76, 178, 76],
                 [0, 0, 51, 51, 51, 51, 76, 76, 76, 178],
                 [0, 0, 51, 51, 51, 51, 76, 76, 76, 178]],
                dtype=np.uint8
            )
        )
        np.testing.assert_equal(
            b,
            np.array(
                [[204, 204, 127, 127, 127, 127, 0, 0, 0, 178],
                 [127, 127, 204, 127, 127, 127, 0, 0, 178, 0],
                 [127, 127, 127, 204, 127, 127, 0, 178, 0, 0],
                 [127, 127, 127, 127, 204, 204, 178, 0, 0, 0],
                 [76, 76, 76, 76, 178, 178, 204, 102, 102, 102],
                 [76, 76, 76, 76, 178, 178, 204, 102, 102, 102],
                 [76, 76, 76, 178, 76, 76, 102, 204, 102, 102],
                 [76, 76, 178, 76, 76, 76, 102, 102, 204, 102],
                 [178, 178, 76, 76, 76, 76, 102, 102, 102, 204],
                 [178, 178, 76, 76, 76, 76, 102, 102, 102, 204]],
                dtype=np.uint8
            )
        )
        np.testing.assert_equal(
            a,
            np.array(
                [[0, 0, 255, 255, 255, 255, 0, 0, 0, 0],
                 [255, 255, 0, 255, 255, 255, 0, 0, 0, 0],
                 [255, 255, 255, 0, 255, 255, 0, 0, 0, 0],
                 [255, 255, 255, 255, 0, 0, 0, 0, 0, 0],
                 [255, 255, 255, 255, 0, 0, 0, 255, 255, 255],
                 [255, 255, 255, 255, 0, 0, 0, 255, 255, 255],
                 [255, 255, 255, 0, 255, 255, 255, 0, 255, 255],
                 [255, 255, 0, 255, 255, 255, 255, 255, 0, 255],
                 [0, 0, 255, 255, 255, 255, 255, 255, 255, 0],
                 [0, 0, 255, 255, 255, 255, 255, 255, 255, 0]],
                dtype=np.uint8
            )
        )

        tile = compute_rgba_tile(*args, **kwargs, format='png')
        self.assertIsInstance(tile, bytes)
