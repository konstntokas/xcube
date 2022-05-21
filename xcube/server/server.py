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

import copy
import logging
from typing import Optional, Any, Dict, Mapping

import tornado.ioloop
import tornado.web

from xcube.constants import EXTENSION_POINT_SERVER_APIS
from xcube.server.api import Api
from xcube.server.api import ApiHandler
from xcube.server.api import SERVER_CONTEXT_ATTR_NAME
from xcube.server.config import BASE_SERVER_CONFIG_SCHEMA
from xcube.server.config import ServerConfig
from xcube.server.context import ApiContext
from xcube.server.context import Context
from xcube.server.context import ServerContext
from xcube.util.extension import ExtensionRegistry
from xcube.util.extension import get_extension_registry


class Server:

    def __init__(
            self,
            server_config: ServerConfig,
            io_loop: Optional[tornado.ioloop.IOLoop] = None,
            extension_registry: Optional[ExtensionRegistry] = None
    ):
        self._server_apis = self.get_server_apis(extension_registry)

        api_config_schemas = {
            api_name: api.config_schema
            for api_name, api in self._server_apis.items()
            if api.config_schema is not None
        }

        server_config_schema = copy.deepcopy(BASE_SERVER_CONFIG_SCHEMA)
        server_config_schema.properties.update(**api_config_schemas)
        self._server_config_schema = server_config_schema

        handlers = []
        for server_api in self._server_apis.values():
            for route in server_api.routes:
                api_route_path = route[0]
                api_handler_cls = route[1]
                if not issubclass(api_handler_cls, ApiHandler):
                    raise ValueError(f'API {server_api.name!r}:'
                                     f' route {api_route_path}:'
                                     f' handler must be instance of'
                                     f' {ApiHandler.__name__}')
                api_handler_cls.api_name = server_api.name
            handlers.extend(server_api.routes)

        self._configure_tornado_logger()

        self._io_loop = io_loop or tornado.ioloop.IOLoop.current()
        self._application = tornado.web.Application(handlers)

        api_contexts = dict()
        server_context = ServerContext(server_config, api_contexts)
        for api_name, api in self._server_apis.items():
            api_context = api.create_context(server_context)
            if api_context is not None:
                if not isinstance(api_context, ApiContext):
                    raise ValueError(f'API {api_name}:'
                                     f' context must be instance of'
                                     f' {ApiContext.__name__}')
                api_contexts[api_name] = api_context
                setattr(server_context, api_name, api_context)

        self._server_context = server_context
        setattr(self._application,
                SERVER_CONTEXT_ATTR_NAME,
                server_context)

    def start(self):
        self._application.listen(self._server_config["port"],
                                 address=self._server_config["address"])
        for api in self._server_apis.values():
            api.on_start(self._server_context, self._io_loop)
        self._io_loop.start()

    def stop(self):
        for api in self._server_apis.values():
            api.on_stop(self._server_context, self._io_loop)
        self._io_loop.stop()

    def change_config(
            self,
            server_config: ServerConfig
    ):
        next_server_config = self._server_config_schema.from_instance(
            server_config
        )
        self._server_context.on_config_change(next_server_config)

    @property
    def config(self) -> Mapping[str, Any]:
        return self._server_config

    @property
    def context(self) -> Context:
        return self._server_context

    @classmethod
    def get_server_apis(
            cls,
            extension_registry: Optional[ExtensionRegistry] = None
    ) -> Dict[str, Api]:
        extension_registry = extension_registry \
                             or get_extension_registry()

        server_apis = {
            ext.name: ext.component
            for ext in extension_registry.find_extensions(
                EXTENSION_POINT_SERVER_APIS
            )
        }

        def count_api_deps(api: Api) -> int:
            dep_sum = 0
            for api_name in api.dependencies:
                dep_sum += count_api_deps(server_apis[api_name]) + 1
            return dep_sum

        api_dep_counts = {
            api.name: count_api_deps(api)
            for api in server_apis.values()
        }

        return {
            api.name: api
            for api in sorted(server_apis.values(),
                              key=lambda api: api_dep_counts[api.name])
        }

    @staticmethod
    def _configure_tornado_logger():
        # Configure Tornado logger to use configured root handlers.
        # For some reason, Tornado's log records will not arrive at
        # the root logger.
        tornado_logger = logging.getLogger('tornado')
        for h in list(tornado_logger.handlers):
            tornado_logger.removeHandler(h)
            h.close()
        for h in list(logging.root.handlers):
            tornado_logger.addHandler(h)
        tornado_logger.setLevel(logging.root.level)
