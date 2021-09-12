# The MIT License (MIT)
# Copyright (c) 2021 by the xcube development team and contributors
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

import json
import os.path
import time
from typing import Type, TypeVar, Dict, Any, Optional, List, Tuple, Union

import requests

from xcube.util.assertions import assert_instance
from xcube.util.jsonschema import JsonObject
from xcube.util.progress import observe_progress
from .config import ServiceConfig
from .response import CubeGeneratorProgress
from .response import CubeGeneratorState
from .response import CubeGeneratorToken
from .response import CubeInfoWithCostsResult
from ..error import CubeGeneratorError
from ..generator import CubeGenerator
from ..request import CubeGeneratorRequest
from ..request import CubeGeneratorRequestLike
from ..response import CubeGeneratorResult
from ..response import CubeInfoResult
from ..response import GenericCubeGeneratorResult

_BASE_HEADERS = {
    "Accept": "application/json",
    # "Content-Type": "application/json",
}

R = TypeVar('R', bound=JsonObject)


class RemoteCubeGenerator(CubeGenerator):
    """
    A cube generator that uses a remote cube generator remote.

    Creates cube views from one or more cube stores, resamples them to a
    common grid, optionally performs some cube transformation, and writes
    the resulting cube to some target cube store.

    :param service_config: An remote configuration object.
    :param verbosity: Level of verbosity, 0 means off.
    :param raise_on_error: Whether to raise a CubeGeneratorError
        exception on generator failures. If False, the default,
        the returned result will have the "status" field set to "error"
        while other fields such as "message", "traceback", "output"
        provide more failure details.
    """

    def __init__(self,
                 service_config: ServiceConfig,
                 progress_period: float = 1.0,
                 raise_on_error: bool = False,
                 verbosity: int = 0):
        super().__init__(raise_on_error=raise_on_error,
                         verbosity=verbosity)
        assert_instance(service_config, ServiceConfig, 'service_config')
        assert_instance(progress_period, (int, float), 'progress_period')
        self._service_config: ServiceConfig = service_config
        self._access_token: Optional[str] = service_config.access_token
        self._progress_period: float = progress_period

    def endpoint_op(self, op_path: str) -> str:
        return f'{self._service_config.endpoint_url}{op_path}'

    @property
    def auth_headers(self) -> Dict:
        access_token = self.access_token
        if access_token is not None:
            return {
                **_BASE_HEADERS,
                'Authorization': f'Bearer {self.access_token}',
            }
        return dict(_BASE_HEADERS)

    @property
    def access_token(self) -> Optional[str]:
        if self._access_token is None:
            if self._service_config.client_id is None \
                    and self._service_config.client_secret is None:
                return None

            request_data = {
                "audience": self._service_config.endpoint_url,
                "client_id": self._service_config.client_id,
                "client_secret": self._service_config.client_secret,
                "grant_type": "client-credentials",
            }
            response = requests.post(self.endpoint_op('oauth/token'),
                                     json=request_data,
                                     headers=_BASE_HEADERS)
            token_response: CubeGeneratorToken = \
                self._parse_response(response,
                                     CubeGeneratorToken,
                                     request_data=request_data)
            self._access_token = token_response.access_token
        return self._access_token

    def _get_cube_info(self, request: CubeGeneratorRequestLike) \
            -> CubeInfoResult:
        request = CubeGeneratorRequest.normalize(request).for_service()
        request_data = request.to_dict()
        response = requests.post(self.endpoint_op('cubegens/info'),
                                 json=request_data,
                                 headers=self.auth_headers)
        response_type = CubeInfoWithCostsResult \
            if self._access_token else CubeInfoResult
        return self._parse_response(response,
                                    response_type=response_type,
                                    request_data=request_data)

    def _generate_cube(self, request: CubeGeneratorRequestLike) \
            -> CubeGeneratorResult:
        request = CubeGeneratorRequest.normalize(request).for_service()
        response = self._submit_gen_request(request)
        cubegen_id, result, _ = \
            self._get_cube_generator_result(response)
        if result is not None:
            return result

        last_worked = 0
        with observe_progress('Generating cube', 100) as cm:
            while True:
                time.sleep(self._progress_period)

                response = requests.get(
                    self.endpoint_op(f'cubegens/{cubegen_id}'),
                    headers=self.auth_headers
                )
                _, result, progress = \
                    self._get_cube_generator_result(response)
                if result is not None:
                    return result

                if progress is not None and len(progress) > 0:
                    progress_state = progress[0].state
                    total_work = progress_state.total_work
                    progress = progress_state.progress or 0
                    worked = progress * total_work
                    work = 100 * ((worked - last_worked) / total_work)
                    if work > 0:
                        cm.worked(work)
                        last_worked = worked

    def _submit_gen_request(self, request: CubeGeneratorRequest):
        request_dict = request.to_dict()

        user_code_path = request_dict \
            .get('code_config', {}) \
            .get('file_set', {}) \
            .get('path')

        if user_code_path:
            user_code_filename = os.path.basename(user_code_path)
            request_dict['code_config']['file_set']['path'] \
                = user_code_filename
            return requests.put(
                self.endpoint_op('cubegens/code'),
                headers=self.auth_headers,
                files={
                    'body': (
                        'request.json',
                        json.dumps(request_dict, indent=2),
                        'application/json'
                    ),
                    'user_code': (
                        user_code_filename,
                        open(user_code_path, 'rb'),
                        'application/octet-stream'
                    )
                }
            )
        else:
            return requests.put(
                self.endpoint_op('cubegens'),
                json=request_dict,
                headers=self.auth_headers
            )

    @staticmethod
    def _get_data_id(request: CubeGeneratorRequest, default: str) -> CubeGeneratorResult:
        data_id = request.output_config.data_id
        return data_id if data_id else default

    def _get_cube_generator_result(
            self,
            response: requests.Response,
            request_data: Dict[str, Any] = None
    ) -> Tuple[str,
               Optional[CubeGeneratorResult],
               Optional[List[CubeGeneratorProgress]]]:
        state = self._get_cube_generator_state(response, request_data)
        result = None
        if state.status.succeeded:
            if isinstance(state.result, CubeGeneratorResult):
                result = state.result.derive(status_code=response.status_code,
                                             output=state.output)
            else:
                raise self._new_unexpected_response_error(
                    response,
                    msg='missing result'
                )
        elif state.status.failed:
            if isinstance(state.result, CubeGeneratorResult):
                result = state.result.derive(status='error',
                                             status_code=response.status_code,
                                             output=state.output)
            else:
                result = CubeGeneratorResult(
                    status='error',
                    status_code=response.status_code,
                    output=state.output
                )
        return state.cubegen_id, result, state.progress

    def _get_cube_generator_state(
            self,
            response: requests.Response,
            request_data: Dict[str, Any] = None
    ) -> CubeGeneratorState:
        return self._parse_response(response,
                                    CubeGeneratorState,
                                    request_data=request_data)

    def _parse_response(self,
                        response: requests.Response,
                        response_type: Type[R],
                        request_data: Dict[str, Any] = None) -> R:
        # noinspection PyBroadException
        try:
            response_data = response.json()
        except BaseException as e:
            raise self._new_unexpected_response_error(
                response, msg=e
            ) from e

        if not isinstance(response_data, dict):
            raise self._new_unexpected_response_error(
                response, msg='no result or unexpected result type'
            )

        if self._verbosity >= 3:
            self.__dump_json(response.request.method,
                             response.url,
                             request_data,
                             response_data)

        # noinspection PyBroadException
        try:
            result = response_type.from_dict(response_data)
        except BaseException as e:
            raise self._new_unexpected_response_error(
                response, msg=e
            ) from e

        if isinstance(result, GenericCubeGeneratorResult):
            result = result.derive(status_code=response.status_code)

        return result

    @classmethod
    def _new_unexpected_response_error(
            cls,
            response: requests.Response,
            msg: Union[None, str, BaseException] = None
    ) -> RuntimeError:
        return RuntimeError(f'Internal error: unexpected response'
                            f' from API call {response.url},'
                            f' status code {response.status_code}: {msg}')

    @classmethod
    def __dump_json(cls, method, url, request_data, response_data):
        """
        Dump debug info as JSON to stdout.

        Used for debugging only.
        """
        url_line = f'{method} {url}:'
        request_line = 'Request:'
        response_line = 'Response:'

        print('=' * len(url_line))
        print(url_line)
        print('=' * len(url_line))
        print('-' * len(request_line))
        print(request_line)
        print('-' * len(request_line))
        print(json.dumps(request_data, indent=2))
        print('-' * len(response_line))
        print(response_line)
        print('-' * len(response_line))
        print(json.dumps(response_data, indent=2))

    def _return_or_raise(self,
                         remote_result: Optional[Dict[str, Any]] = None,
                         message: Optional[str] = None,
                         output: Optional[List[str]] = None,
                         traceback: Optional[List[str]] = None):
        if remote_result:
            message = remote_result.get('message', message)
            output = remote_result.get('output', output)
            traceback = remote_result.get('traceback', traceback)
        if self._raise_on_error:
            raise CubeGeneratorError(message,
                                     remote_output=output,
                                     remote_traceback=traceback)
        return CubeGeneratorResult(status='error',
                                   message=message,
                                   output=output,
                                   traceback=traceback)
