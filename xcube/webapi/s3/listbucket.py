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

import datetime
import hashlib
import time
from typing import Dict, Any, List, Mapping

_CONTENT_LENGTH_DUMMY = -1
_LAST_MODIFIED_DUMMY = str(datetime.datetime.utcfromtimestamp(time.time()))


def list_s3_bucket_v2(object_storage: Mapping[str, bytes],
                      bucket_name: str = None,
                      delimiter: str = None,
                      prefix: str = None,
                      max_keys: int = None,
                      start_after: str = None,
                      continuation_token: str = None,
                      storage_class: str = None,
                      last_modified: str = None) -> Dict:
    """Implements AWS GET Bucket (List Objects) Version 2
    (https://docs.aws.amazon.com/AmazonS3/latest/API/v2-RESTBucketGET.html)
    for the local filesystem.

    :param object_storage: mapping from path-like keys to byte-objects.
    :param bucket_name: The bucket name, defaults to "s3bucket"
    :param delimiter: A delimiter is a character you use to group keys.
        If you specify a prefix, all of the keys that contain the same string
        between the prefix and the first occurrence of the delimiter after
        the prefix are grouped under a single result element called
        CommonPrefixes.
        If you don't specify the prefix parameter, the substring starts
        at the beginning of the key.
        The keys that are grouped under the CommonPrefixes result element
        are not returned elsewhere in the response.
        Refer to AWS docs for details. No default.
    :param prefix: Limits the response to keys that begin with the
        specified prefix.
        You can use prefixes to separate a bucket into different
        groupings of keys. (You can think of using prefix to make groups
        in the same way you'd use a folder in a file system.)
        Refer to AWS docs for details. No default.
    :param max_keys: Sets the maximum number of keys returned
        in the response body.
        If you want to retrieve fewer than the default 1000 keys,
        you can add this to your request.
        The response might contain fewer keys, but it never contains more.
        If there are additional keys that satisfy the search criteria,
        but these keys were not returned because max-keys was exceeded,
        the response contains <IsTruncated>true</IsTruncated>.
        To return the additional keys, see NextContinuationToken.
        Refer to AWS docs for details. Defaults to 1000.
    :param start_after: If you want the API to return key names after
        a specific object key in your key space, you can add this parameter.
        Amazon S3 lists objects in UTF-8 character encoding
        in lexicographical order. Refer to AWS docs for details.
        No default.
    :param continuation_token: When the response to this API call is
        truncated (that is, the IsTruncated response element value is true),
        the response also includes the NextContinuationToken element.
        To list the next set of objects,
        you can use the NextContinuationToken element in the next request
        as the continuation-token.
        Refer to AWS docs for details. No default.
    :param storage_class: Refer to AWS docs for details.
        Defaults to "STANDARD".
    :param last_modified: For testing only: always use this value
        for the "LastModified" entry of results
    :return: A dictionary that represents the contents of a
        "ListBucketResult". Refer to AWS docs for details.
    """
    bucket_name = bucket_name or 's3'
    max_keys = max_keys or 1000
    start_after = None if continuation_token else start_after
    storage_class = storage_class or 'STANDARD'

    contents_list = []
    next_continuation_token = None
    continuation_token_seen = continuation_token is None
    start_key_seen = start_after is None
    common_prefixes_list = []
    common_prefixes_set = set()

    token = 0

    for key in iter(object_storage):

        token += 1

        if len(contents_list) == max_keys:
            next_continuation_token = token
            break

        if key == start_after:
            start_key_seen = True
            continue

        if token == continuation_token:
            continuation_token_seen = True

        if not continuation_token_seen or not start_key_seen:
            continue

        if prefix and not key.startswith(prefix):
            continue

        if delimiter:
            index = key.find(delimiter, len(prefix) if prefix else 0)
            if index >= 0:
                key = key[:index + len(delimiter)]
                if key not in common_prefixes_set:
                    common_prefixes_set.add(key)
                    common_prefixes_list.append(key)
                continue

        item = dict(
            Key=key,
            Size=_CONTENT_LENGTH_DUMMY,
            LastModified=last_modified or _LAST_MODIFIED_DUMMY,
            ETag=str_to_etag(key),
            StorageClass=storage_class
        )
        contents_list.append(item)

    list_bucket_result: Dict[str, Any] = dict(
        Name=bucket_name,
        Prefix=prefix,
        StartAfter=start_after,
        MaxKeys=max_keys,
        Delimiter=delimiter,
        IsTruncated=next_continuation_token is not None,
        ContinuationToken=continuation_token
    )
    if next_continuation_token is not None:
        list_bucket_result.update(
            NextContinuationToken=next_continuation_token
        )
    if contents_list:
        list_bucket_result.update(
            Contents=contents_list
        )
    if common_prefixes_list:
        list_bucket_result.update(
            CommonPrefixes=[dict(Prefix=prefix)
                            for prefix in common_prefixes_list]
        )
    return list_bucket_result


def list_s3_bucket_v1(object_storage: Mapping[str, bytes],
                      bucket_name: str = None,
                      delimiter: str = None,
                      prefix: str = None,
                      max_keys: int = None,
                      marker: str = None,
                      storage_class: str = None,
                      last_modified: str = None) -> Dict:
    """Implements AWS GET Bucket (List Objects) Version 1
    (https://docs.aws.amazon.com/AmazonS3/latest/API/RESTBucketGET.html)
    for the local filesystem.

    :param object_storage: mapping from path-like keys to byte-objects.
    :param bucket_name: The bucket name, defaults to "s3bucket"
    :param delimiter: A delimiter is a character you use to group keys.
        If you specify a prefix, all of the keys that contain the same string
        between the prefix and the first occurrence of the delimiter after
        the prefix are grouped under a single result element called 
        CommonPrefixes.
        If you don't specify the prefix parameter, the substring starts 
        at the beginning of the key.
        The keys that are grouped under the CommonPrefixes result 
        element are not returned elsewhere in the response.
        Refer to AWS docs for details. No default.
    :param prefix: Limits the response to keys that begin with the 
        specified prefix.
        You can use prefixes to separate a bucket into different 
        groupings of keys. (You can think of using prefix to make groups
        in the same way you'd use a folder in a file system.)
        Refer to AWS docs for details. No default.
    :param max_keys: Sets the maximum number of keys returned in the 
        response body. If you want to retrieve fewer than the default 
        1000 keys, you can add this to your request.
        The response might contain fewer keys, but it never contains more.
        If there are additional keys that satisfy the search criteria, 
        but these keys were not returned because max-keys was exceeded, 
        the response contains <IsTruncated>true</IsTruncated>.
        To return the additional keys, see NextMarker.
        Refer to AWS docs for details.
    :param marker: Indicates the object key to start with when listing 
        objects in a bucket. All objects are listed in the dictionary order.
        Refer to AWS docs for details. No default.
    :param storage_class: Refer to AWS docs for details. 
        Defaults to "STANDARD".
    :param last_modified: For testing only: always use this value 
        for the "LastModified" entry of results
    :return: A dictionary that represents the contents of
        a "ListBucketResult". Refer to AWS docs for details.
    """
    bucket_name = bucket_name or 's3'
    max_keys = max_keys or 1000
    storage_class = storage_class or 'STANDARD'

    contents_list = []
    is_truncated = False
    next_marker = None
    marker_seen = marker is None
    common_prefixes_list = []
    common_prefixes_set = set()

    for key in iter(object_storage):

        if len(contents_list) == max_keys:
            is_truncated = True
            next_marker = key
            break

        if key == marker:
            marker_seen = True

        if not marker_seen:
            continue

        if prefix and not key.startswith(prefix):
            continue

        if delimiter:
            index = key.find(delimiter, len(prefix) if prefix else 0)
            if index >= 0:
                key = key[:index + len(delimiter)]
                if key not in common_prefixes_set:
                    common_prefixes_set.add(key)
                    common_prefixes_list.append(key)
                continue

        item = dict(
            Key=key,
            Size=_CONTENT_LENGTH_DUMMY,
            LastModified=last_modified or _LAST_MODIFIED_DUMMY,
            ETag=str_to_etag(key),
            StorageClass=storage_class
        )
        contents_list.append(item)

    list_bucket_result: Dict[str, Any] = dict(
        Name=bucket_name,
        Prefix=prefix,
        Marker=marker,
        MaxKeys=max_keys,
        Delimiter=delimiter,
        IsTruncated=is_truncated
    )
    if is_truncated:
        list_bucket_result.update(NextMarker=next_marker)
    if contents_list:
        list_bucket_result.update(Contents=contents_list)
    if common_prefixes_list:
        list_bucket_result.update(
            CommonPrefixes=[dict(Prefix=prefix)
                            for prefix in common_prefixes_list]
        )
    return list_bucket_result


def list_bucket_result_to_xml(list_bucket_result):
    return dict_to_xml(
        'ListBucketResult',
        list_bucket_result,
        root_element_attrs=dict(
            xmlns="http://s3.amazonaws.com/doc/2006-03-01/"
        )
    )


def dict_to_xml(root_element_name: str,
                content_dict: Dict,
                root_element_attrs: Dict = None) -> str:
    lines = []
    _value_to_xml(lines, root_element_name, content_dict,
                  element_attrs=root_element_attrs)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + '\n'.join(lines)


def _value_to_xml(lines: List[str],
                  element_name: str,
                  element_value: Any,
                  element_attrs: Dict = None,
                  indent: int = 0):
    attrs = ''
    if element_attrs:
        for attr_name, attr_value in element_attrs.items():
            attrs += f' {attr_name}=\"{_value_to_text(attr_value)}\"'
    if element_value is None:
        lines.append(f'{indent * "  "}<{element_name}{attrs}/>')
    elif isinstance(element_value, dict):
        lines.append(f'{indent * "  "}<{element_name}{attrs}>')
        for sub_element_name, sub_element_value in element_value.items():
            _value_to_xml(lines,
                          sub_element_name,
                          sub_element_value,
                          indent=indent + 1)
        lines.append(f'{indent * "  "}</{element_name}>')
    elif isinstance(element_value, list):
        for item in element_value:
            _value_to_xml(lines,
                          element_name,
                          item,
                          indent=indent)
    else:
        lines.append(f'{indent * "  "}'
                     f'<{element_name}{attrs}>'
                     f'{_value_to_text(element_value)}'
                     f'</{element_name}>')


def _value_to_text(value) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


def mtime_to_str(mtime) -> str:
    return str(datetime.datetime.fromtimestamp(mtime))


def str_to_etag(s) -> str:
    return '"' + hashlib.md5(bytes(s, encoding='utf-8')).hexdigest() + '"'
