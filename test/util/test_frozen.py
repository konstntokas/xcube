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

import pytest

from xcube.util.frozen import FrozenDict
from xcube.util.frozen import FrozenList
from xcube.util.frozen import freeze_value


class FrozenDictTest(unittest.TestCase):
    FLAT = dict(a=7, b=True)
    NESTED = dict(a=7, b=True, c=FLAT, d=[FLAT, FLAT])

    def test_deep(self):
        dct = FrozenDict.deep(self.FLAT)
        self.assertFlatOk(dct)
        dct = FrozenDict.deep(self.NESTED)
        self.assertNestedOk(dct)

    def assertFlatOk(self, dct: dict):
        self.assertEqual(self.FLAT, dct)
        with pytest.raises(TypeError, match="dict is read-only"):
            dct['x'] = 'Take this'
        with pytest.raises(TypeError, match="dict is read-only"):
            del dct['a']
        with pytest.raises(TypeError, match="dict is read-only"):
            dct.update(x='Take this')
        with pytest.raises(TypeError, match="dict is read-only"):
            dct.pop('a')
        with pytest.raises(TypeError, match="dict is read-only"):
            dct.popitem()
        with pytest.raises(TypeError, match="dict is read-only"):
            dct.clear()

    def assertNestedOk(self, dct: dict):
        self.assertFlatOk(dct['c'])
        self.assertFlatOk(dct['d'][0])
        self.assertFlatOk(dct['d'][1])

        with pytest.raises(TypeError, match="dict is read-only"):
            dct['c'] = 3

        with pytest.raises(TypeError, match="list is read-only"):
            dct['d'][0] = 3


class FrozenListTest(unittest.TestCase):
    FLAT = ['A', 'B', 'C']
    NESTED = [1, True, FLAT, [FLAT, FLAT]]

    def test_deep(self):
        lst = FrozenList.deep(self.FLAT)
        self.assertFlatOk(lst)
        lst = FrozenList.deep(self.NESTED)
        self.assertNestedOk(lst)

    def assertFlatOk(self, lst: list):
        self.assertEqual(self.FLAT, lst)
        with pytest.raises(TypeError, match="list is read-only"):
            lst.append('X')
        with pytest.raises(TypeError, match="list is read-only"):
            lst.extend(['X'])
        with pytest.raises(TypeError, match="list is read-only"):
            lst.clear()
        with pytest.raises(TypeError, match="list is read-only"):
            lst.reverse()
        with pytest.raises(TypeError, match="list is read-only"):
            lst.sort()
        with pytest.raises(TypeError, match="list is read-only"):
            lst.remove('A')
        with pytest.raises(TypeError, match="list is read-only"):
            lst.insert(1, 'X')
        with pytest.raises(TypeError, match="list is read-only"):
            lst[1] = 'Take this'
        with pytest.raises(TypeError, match="list is read-only"):
            lst *= 3
        with pytest.raises(TypeError, match="list is read-only"):
            lst += ['X']

    def assertNestedOk(self, lst: list):
        self.assertFlatOk(lst[2])
        self.assertFlatOk(lst[3][0])
        self.assertFlatOk(lst[3][1])

        with pytest.raises(TypeError, match="list is read-only"):
            lst[2] = 'X'

        with pytest.raises(TypeError, match="list is read-only"):
            lst[3][0] = 'X'


class FreezeValueTest(unittest.TestCase):
    def test_primitives(self):
        self.assertEqual(True, freeze_value(True))
        self.assertEqual(26, freeze_value(26))
        self.assertEqual('X', freeze_value('X'))

    def test_sequences(self):
        self.assertEqual([1, 2, 3], freeze_value([1, 2, 3]))
        self.assertIsInstance(freeze_value([1, 2, 3]), FrozenList)

        self.assertEqual([1, 2, 3], freeze_value((1, 2, 3)))
        self.assertIsInstance(freeze_value((1, 2, 3)), FrozenList)

    def test_dict(self):
        self.assertEqual({'x': 32, 'y': 42}, freeze_value({'x': 32, 'y': 42}))
        self.assertIsInstance(freeze_value({'x': 32, 'y': 42}), FrozenDict)
