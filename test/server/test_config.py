# The MIT License (MIT)
# Copyright (c) 2022 by the xcube team and contributors
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

from xcube.server.config import get_reverse_url_prefix
from xcube.server.config import get_url_prefix


class ConfigTest(unittest.TestCase):
    def test_get_url_prefix(self):
        self.assertEqual('',
                         get_url_prefix(dict()))
        self.assertEqual('',
                         get_url_prefix(dict(url_prefix='')))
        self.assertEqual('',
                         get_url_prefix(dict(url_prefix=None)))
        self.assertEqual('',
                         get_url_prefix(dict(url_prefix='/')))
        self.assertEqual('',
                         get_url_prefix(dict(url_prefix='//')))

        self.assertEqual('/api/v1',
                         get_url_prefix(dict(url_prefix='api/v1')))
        self.assertEqual('/api/v1',
                         get_url_prefix(dict(url_prefix='/api/v1')))
        self.assertEqual('/api/v1',
                         get_url_prefix(dict(url_prefix='api/v1/')))
        self.assertEqual('/api/v1',
                         get_url_prefix(dict(url_prefix='/api/v1/')))
        self.assertEqual('/api/v1',
                         get_url_prefix(dict(url_prefix='/api/v1//')))
        self.assertEqual('/api/v1',
                         get_url_prefix(dict(url_prefix='//api/v1//')))
        self.assertEqual('/api/v1',
                         get_url_prefix(dict(url_prefix='///api/v1//')))

    def test_get_reverse_url_prefix(self):
        self.assertEqual('',
                         get_reverse_url_prefix(dict()))
        self.assertEqual('',
                         get_reverse_url_prefix(dict(reverse_url_prefix='')))
        self.assertEqual('',
                         get_reverse_url_prefix(
                             dict(reverse_url_prefix=None)))
        self.assertEqual('',
                         get_reverse_url_prefix(dict(reverse_url_prefix='/')))
        self.assertEqual('',
                         get_reverse_url_prefix(
                             dict(reverse_url_prefix='//')))

        self.assertEqual('/proxy/9192',
                         get_reverse_url_prefix(
                             dict(reverse_url_prefix='proxy/9192')))
        self.assertEqual('/proxy/9192',
                         get_reverse_url_prefix(
                             dict(reverse_url_prefix='/proxy/9192')))
        self.assertEqual('/proxy/9192',
                         get_reverse_url_prefix(
                             dict(reverse_url_prefix='proxy/9192/')))
        self.assertEqual('/proxy/9192',
                         get_reverse_url_prefix(
                             dict(reverse_url_prefix='/proxy/9192/')))
        self.assertEqual('/proxy/9192',
                         get_reverse_url_prefix(
                             dict(reverse_url_prefix='/proxy/9192//')))
        self.assertEqual('/proxy/9192',
                         get_reverse_url_prefix(
                             dict(reverse_url_prefix='//proxy/9192//')))
        self.assertEqual('/proxy/9192',
                         get_reverse_url_prefix(
                             dict(reverse_url_prefix='///proxy/9192//')))

        self.assertEqual('/api/v1',
                         get_reverse_url_prefix(dict(url_prefix='api/v1')))
        self.assertEqual('/proxy/9192',
                         get_reverse_url_prefix(
                             dict(reverse_url_prefix='/proxy/9192',
                                  url_prefix='/api/v1')))
