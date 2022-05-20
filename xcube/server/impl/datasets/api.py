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

from typing import Any, Optional, Mapping

from xcube.server.api import Api
from xcube.server.context import Context
from .config import DATASETS_CONFIG_SCHEMA
from .context import DatasetsContext


class DatasetApi(Api[DatasetsContext]):

    def __init__(self):
        super().__init__('datasets', config_schema=DATASETS_CONFIG_SCHEMA)

    def get_context(self,
                    next_api_config: Any,
                    prev_api_context: Optional[DatasetsContext],
                    next_server_config: Mapping[str, Any],
                    prev_server_context: Optional[Context]) -> DatasetsContext:
        if prev_api_context
        return DatasetsContext(next_api_config)


api = DatasetApi()
