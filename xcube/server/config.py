#  The MIT License (MIT)
#  Copyright (c) 2022 by the xcube development team and contributors
#
#  Permission is hereby granted, free of charge, to any person obtaining a
#  copy of this software and associated documentation files (the "Software"),
#  to deal in the Software without restriction, including without limitation
#  the rights to use, copy, modify, merge, publish, distribute, sublicense,
#  and/or sell copies of the Software, and to permit persons to whom the
#  Software is furnished to do so, subject to the following conditions:
#
#  The above copyright notice and this permission notice shall be included in
#  all copies or substantial portions of the Software.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
#  FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
#  DEALINGS IN THE SOFTWARE.

from xcube.constants import DEFAULT_SERVER_ADDRESS
from xcube.constants import DEFAULT_SERVER_PORT
from xcube.util.jsonschema import JsonIntegerSchema
from xcube.util.jsonschema import JsonObjectSchema
from xcube.util.jsonschema import JsonStringSchema

BASE_SERVER_CONFIG_SCHEMA = JsonObjectSchema(
    properties=dict(
        port=JsonIntegerSchema(default=DEFAULT_SERVER_PORT),
        address=JsonStringSchema(default=DEFAULT_SERVER_ADDRESS),
    ),
    # We allow for other configuration settings contributed
    # by APIs. If these APIs are currently not in use,
    # validation would fail.
    # TODO: just warn, if any settings are encountered that
    #   are not covered by the current APIs config schemas.
    additional_properties=True,
)

