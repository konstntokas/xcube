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

from typing import Sequence

from xcube.core.store.dataset import DatasetDescriptor
from xcube.core.store.param import ParamValues


class DatasetSearch:
    def __init__(self,
                 search_params: ParamValues,
                 max_results: int = None,
                 offset: int = None):
        self.search_params = dict(search_params or {})
        self.max_results = max_results
        self.offset = offset


class DatasetSearchResult:
    def __init__(self,
                 search: DatasetSearch,
                 offset: int,
                 next_offset: int,
                 service_id: str,
                 datasets: Sequence[DatasetDescriptor]):
        self.search = search
        self.offset = offset
        self.next_offset = next_offset
        self.service_id = service_id
        self.datasets = datasets
