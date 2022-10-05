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

import concurrent.futures
import inspect
from abc import ABC, abstractmethod
from typing import Any, List, Optional, Tuple, Dict, Type, Sequence, \
    Generic, TypeVar, Union, Callable, Awaitable, Mapping

from .asyncexec import AsyncExecution
from ..util.assertions import assert_instance
from ..util.assertions import assert_true
from ..util.frozen import FrozenDict
from ..util.jsonschema import JsonObjectSchema

_SERVER_CONTEXT_ATTR_NAME = '__xcube_server_context'
_HTTP_METHODS = {'head', 'get', 'post', 'put', 'delete', 'options'}

ArgT = TypeVar('ArgT')
ReturnT = TypeVar('ReturnT')
# API Context type variable
ServerContextT = TypeVar("ServerContextT", bound="Context")
ApiContextT = TypeVar("ApiContextT", bound="Context")

JSON = Union[
    None,
    bool,
    int,
    float,
    str,
    List["JSON"],
    Dict[str, "JSON"],
]

ServerConfigObject = FrozenDict[str, Any]
ServerConfig = FrozenDict[str, Any]

builtin_type = type


class Api(Generic[ServerContextT]):
    """
    A server API.

    The most common purpose of this class is to
    add a new API to the server by the means of routes.

    Every may produce API context objects for a given server
    configuration.

    If the server configuration changes, the API is asked to
    create a new context object.

    However, an API may be just programmatic and serve as a
    web server middleware. It can then still provide
    the context for other dependent APIs.

    May be derived by clients to override the methods

    * `create_ctx` - to create an API-specific context object;
    * `on_start` - to do things on server start;
    * `on_stop` - to do things on server stop.

    Note that these methods can be also be effectively
    implemented by respectively passing the *create_ctx*, *on_start*,
    *on_stop* arguments to the constructor.

    Each extension API module must export an instance of this
    class. A typical use case of this class:

    ```
    class DatasetsContext(ApiContext)
        def update(self, prev_ctx: Optional[Context]):
            config = self.config
            ...

        def get_datasets(self):
            ...

    api = Api("datasets",
              config_schema=DATASET_CONFIG_SCHEMA,
              create_ctx=DatasetsApiContext)

    @api.route("/datasets")
    class DatasetsHandler(ApiHandler[DatasetsContext]):
        def get(self):
            return self.ctx.get_datasets()
    ```

    :param name: The API name. Must be unique within a server.
    :param version: The API version. Defaults to "0.0.0".
    :param routes: Optional list of initial routes.
        A route is a tuple of the form (route-pattern, handler-class) or
        (route-pattern, handler-class, handler-kwargs). The handler-class
        must be derived from ApiHandler.
    :param required_apis: Sequence of names of other required APIs.
    :param optional_apis: Sequence of names of other optional APIs.
    :param config_schema: Optional JSON schema for the API's configuration.
        If not given, or None is passed, the API is assumed to
        have no configuration.
    :param create_ctx: Optional API context factory.
        If given, must be a callable that accepts the server context
        and returns a ``Context`` instance for the API.
        Called when a new context is required after configuration changes.
    :param on_start: Optional start handler.
        If given, must be a callable that accepts the server context.
        Called when the server starts.
    :param on_stop: Optional stop handler.
        If given, must be a callable that accepts the server context.
        Called when the server stopped.
    """

    def __init__(
            self,
            name: str, /,
            version: str = '0.0.0',
            description: Optional[str] = None,
            routes: Optional[Sequence["ApiRoute"]] = None,
            required_apis: Optional[Sequence[str]] = None,
            optional_apis: Optional[Sequence[str]] = None,
            config_schema: Optional[JsonObjectSchema] = None,
            create_ctx: Optional[
                Callable[["Context"], Optional[ServerContextT]]
            ] = None,
            on_start: Optional[
                Callable[["Context"], Any]
            ] = None,
            on_stop: Optional[
                Callable[["Context"], Any]
            ] = None,
    ):
        assert_instance(name, str, 'name')
        assert_instance(version, str, 'version')
        if description is not None:
            assert_instance(description, str, 'description')
        if config_schema is not None:
            assert_instance(config_schema, JsonObjectSchema, 'config_schema')
        if on_start is not None:
            assert_true(callable(on_start),
                        message='on_start must be callable')
        if on_stop is not None:
            assert_true(callable(on_stop),
                        message='on_stop must be callable')
        self._name = name
        self._version = version
        self._description = description
        self._required_apis = tuple(required_apis or ())
        self._optional_apis = tuple(optional_apis or ())
        self._routes: List[ApiRoute] = list(routes or [])
        self._config_schema = config_schema
        self._create_ctx = create_ctx or ApiContext
        self._on_start = on_start or self._handle_event
        self._on_stop = on_stop or self._handle_event

    @property
    def name(self) -> str:
        """The name of this API."""
        return self._name

    @property
    def version(self) -> str:
        """The version of this API."""
        return self._version

    @property
    def description(self) -> Optional[str]:
        """The description of this API."""
        return self._description or (getattr(self, '__doc__', None)
                                     if self.__class__ is not Api else None)

    @property
    def required_apis(self) -> Tuple[str]:
        """The names of other required APIs."""
        return self._required_apis

    @property
    def optional_apis(self) -> Tuple[str]:
        """The names of other optional APIs."""
        return self._optional_apis

    def route(self, path: str, **handler_kwargs):
        """
        Decorator that adds a route to this API.

        The decorator target must be a class derived from ApiHandler.

        :param path: The route path.
        :param handler_kwargs: Optional keyword arguments passed to
            ApiHandler constructor.
        :return: A decorator function that receives a
            class derived from ApiHandler
        """

        def decorator_func(handler_cls: Type[ApiHandler]):
            self._routes.append(ApiRoute(self.name,
                                         path,
                                         handler_cls,
                                         handler_kwargs))
            return handler_cls

        return decorator_func

    def operation(self,
                  operation_id: Optional[str] = None,
                  summary: Optional[str] = None,
                  description: Optional[str] = None,
                  parameters: Optional[List[Dict[str, Any]]] = None,
                  tags: Optional[str] = None,
                  **kwargs):
        """
        Decorator that adds OpenAPI 3.0 information to an
        API handler's operation,
        i.e. one of the get, post, put, delete, or options methods.

        :return: A decorator function that receives a
            and returns an ApiHandler's operation.
        """
        openapi = {
            "operationId": operation_id or kwargs.pop("operationId", None),
            "summary": summary,
            "description": description,
            "parameters": parameters,
            "tags": tags,
        }
        openapi = {k: v for k, v in openapi.items() if v is not None}

        def decorator_func(target: Union[Type[ApiHandler], Callable]):
            if inspect.isfunction(target) \
                    and hasattr(target, '__name__') \
                    and target.__name__ in _HTTP_METHODS:
                setattr(target, "__openapi__", openapi)
            else:
                raise TypeError(f'API {self.name}:'
                                f' @operation() decorator'
                                f' must be used with one of the'
                                f' HTTP methods of an {ApiHandler.__name__}')
            return target

        return decorator_func

    @property
    def routes(self) -> Tuple["ApiRoute"]:
        """The routes provided by this API."""
        return tuple(self._routes)

    @property
    def config_schema(self) -> Optional[JsonObjectSchema]:
        """Get the JSON schema for the configuration of this API."""
        return self._config_schema

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    def create_ctx(self, server_ctx: "Context") -> ServerContextT:
        """Create a new context object for this API.
        The default implementation uses the *create_ctx*
        argument passed to the constructor, if any,
        to instantiate an API context using *ctx* as only argument.
        Otherwise, a new instance of ``ApiContext`` is returned.
        Should not be called directly.

        :param server_ctx: The server's current context.
        :return: An instance of ``Context``
        """
        return self._create_ctx(server_ctx)

    def on_start(self, server_ctx: "Context"):
        """Called when the server is started.
        Can be overridden to initialize the API.
        Should not be called directly.

        The default implementation calls the *on_start*
        argument passed to the constructor, if any.

        :param server_ctx: The server's current context
        """
        return self._on_start(server_ctx)

    def on_stop(self, server_ctx: "Context"):
        """Called when the server is stopped.
        Can be overridden to initialize the API.
        Should not be called directly.

        The default implementation calls the *on_stop*
        argument passed to the constructor, if any.

        :param server_ctx: The server's current context
        """
        return self._on_stop(server_ctx)

    def _handle_event(self, server_ctx: "Context"):
        """Do nothing."""

    def __repr__(self):
        return f'Api({self.name!r}, version={self.version!r})'


class Context(AsyncExecution, ABC):
    """The interface for server context objects."""

    @property
    @abstractmethod
    def apis(self) -> Tuple[Api]:
        """The APIs used by the server."""

    @property
    @abstractmethod
    def open_api_doc(self) -> Dict[str, Any]:
        """The OpenAPI JSON document for the server."""

    @property
    @abstractmethod
    def config(self) -> ServerConfig:
        """The server's current configuration."""

    @abstractmethod
    def get_api_ctx(self,
                    api_name: str,
                    cls: Optional[Type[ApiContextT]] = None) \
            -> Optional[ApiContextT]:
        """
        Get the API context for *api_name*.
        Can be used to access context objects of other APIs.

        The keyword argument *cls* can be used to assert a specific
        type if of context.

        :param api_name: The name of a registered API.
        :param cls: Optional context class.
            If given, must be a class derived from `ApiContext`.
        :return: The API context object for *api_name*,
            or None if no such exists.
        """

    @abstractmethod
    def on_update(self, prev_context: Optional["Context"]):
        """Called when the server configuration changed.
        Must be implemented by derived classes in order to update
        this context with respect to the current configuration
        ``self.config`` and the given *prev_context*, if any.
        The method shall not be called directly.

        :param prev_context: The previous context instance.
            Will be ``None`` if ``on_update()`` is called for the
            very first time.
        """

    @abstractmethod
    def on_dispose(self):
        """Called if this context will never be used again.
        May be overridden by derived classes in order to
        dispose allocated resources.
        The default implementation does nothing.
        The method shall not be called directly.
        """


class ApiContext(Context):
    """
    An implementation of the server context to be used by APIs.

    A typical use case is to cache computationally expensive
    resources served by a particular API.

    An instance of this class is created for every API unless
    an API provides its own, specific context.

    Specific context classes should derive from ``ApiContext`` and

    * may override the `on_update()` method in order
      to initialize or update this context object state with
      respect to the current server configuration, or with
      respect to other API context object states.
    * may override the `on_dispose()` method to empty any caches
      and close access to resources.
    * must call the super class constructor with the
      *server_ctx* context, from their own constructor, if any.

    :param server_ctx: The server context.
    """

    def __init__(self, server_ctx: Context):
        self._server_ctx = server_ctx

    @property
    def server_ctx(self) -> Context:
        """The server context."""
        return self._server_ctx

    @property
    def apis(self) -> Tuple[Api]:
        """Return the server context's ``apis`` property."""
        return self.server_ctx.apis

    @property
    def open_api_doc(self) -> Dict[str, Any]:
        """Return the server context's ``apis`` property."""
        return self.server_ctx.open_api_doc

    @property
    def config(self) -> ServerConfig:
        """Return the server context's ``config`` property."""
        return self.server_ctx.config

    def get_api_ctx(self,
                    api_name: str,
                    cls: Optional[Type[ApiContextT]] = None) \
            -> Optional[ApiContextT]:
        """Calls the server context's ``get_api_ctx()`` method."""
        return self.server_ctx.get_api_ctx(api_name, cls=cls)

    def call_later(self,
                   delay: Union[int, float],
                   callback: Callable,
                   *args,
                   **kwargs) -> object:
        """Calls the server context's ``call_later()`` method."""
        return self.server_ctx.call_later(delay, callback,
                                          *args, **kwargs)

    def run_in_executor(self,
                        executor: Optional[concurrent.futures.Executor],
                        function: Callable[..., ReturnT],
                        *args: Any,
                        **kwargs: Any) -> Awaitable[ReturnT]:
        """Calls the server context's ``run_in_executor()`` method."""
        return self.server_ctx.run_in_executor(executor, function,
                                               *args, **kwargs)

    def on_update(self, prev_context: Optional["Context"]):
        """Does nothing."""

    def on_dispose(self):
        """Does nothing."""


class ApiRequest:

    @abstractmethod
    def url_for_path(self,
                     path: str,
                     query: Optional[str] = None) -> str:
        """Get the full URL for the given *path* component and
        optional *query* string.

        :param path: The path component.
        :param query: Optional query string.
        :return: Full URL for *path* and *query*.
        """

    @property
    def base_url(self) -> str:
        return self.url_for_path("")

    @property
    @abstractmethod
    def url(self) -> str:
        """The full URL of the request."""

    @property
    @abstractmethod
    def headers(self) -> Mapping[str, str]:
        """The request headers."""

    @property
    @abstractmethod
    def body(self) -> bytes:
        """The request body."""

    @property
    @abstractmethod
    def json(self) -> JSON:
        """The request body as JSON value."""

    @abstractmethod
    def make_query_lower_case(self):
        """Make the query keys case-insensitive."""

    @property
    @abstractmethod
    def query(self) -> Mapping[str, Sequence[str]]:
        """The request query arguments."""

    # noinspection PyShadowingBuiltins
    def get_query_arg(self,
                      name: str,
                      type: Optional[Type[ArgT]] = None,
                      default: Optional[ArgT] = None) -> Optional[ArgT]:
        """Get the value of query argument given by *name*. To force
        conversion to a specific target data type use the optional *type*
        argument. If *type* is not given, but *default* is, then *type*
        will be inferred from *default*.

        :param name: The name of the argument
        :param type: The requested data type.
            Must be a callable type, e.g. bool, int.
        :param default: Optional default value.
        :return: The value of the query argument.
        """
        if type is None and default is not None:
            type = builtin_type(default)
            type = type if callable(type) else None
        values = self.get_query_args(name, type=type)
        return values[0] if values else default

    # noinspection PyShadowingBuiltins
    @abstractmethod
    def get_query_args(self,
                       name: str,
                       type: Optional[Type[ArgT]] = None) -> Sequence[ArgT]:
        """Get the values of query argument given by *name*.
        If *type* is given, a sequence of that type will be returned.
        :param name: The name of the argument
        :param type: The requested data type.
            Must be a callable type, e.g. bool, int.
        :return: The values of the query argument.
        """


class ApiResponse(ABC):
    @abstractmethod
    def set_status(self, status_code: int, reason: Optional[str] = None):
        """Set the HTTP status code and optionally the reason."""

    @abstractmethod
    def set_header(self, name: str, value: str):
        """Set the HTTP header *name* to given *value*."""

    @abstractmethod
    def write(self, data: Union[str, bytes, JSON]):
        """Write data."""

    @abstractmethod
    def finish(self, data: Union[str, bytes, JSON] = None):
        """Finish the response (and submit it)."""


class ApiHandler(Generic[ServerContextT], ABC):
    """
    Base class for all API handlers.

    :param ctx: The API context.
    :param request: The API handler's request.
    :param response: The API handler's response.
    :param kwargs: Client keyword arguments (not used in base class).
    """

    def __init__(self,
                 ctx: Context,
                 request: ApiRequest,
                 response: ApiResponse,
                 **kwargs: Any):
        assert_true(not kwargs,
                    message=f"Unknown keyword(s) passed to"
                            f" {self.__class__.__name__}:"
                            f" {', '.join(kwargs.keys())}.")
        self._ctx = ctx
        self._request = request
        self._response = response

    @property
    def ctx(self) -> ServerContextT:
        """The API's context object."""
        # noinspection PyTypeChecker
        return self._ctx

    @property
    def request(self) -> ApiRequest:
        """The request that provides the handler's input."""
        return self._request

    @property
    def response(self) -> ApiResponse:
        """The response that provides the handler's output."""
        return self._response

    # HTTP methods

    def head(self, *args, **kwargs):
        raise ApiError.MethodNotAllowed("method HEAD not allowed")

    def get(self, *args, **kwargs):
        raise ApiError.MethodNotAllowed("method GET not allowed")

    def post(self, *args, **kwargs):
        raise ApiError.MethodNotAllowed("method POST not allowed")

    def put(self, *args, **kwargs):
        raise ApiError.MethodNotAllowed("method PUT not allowed")

    def delete(self, *args, **kwargs):
        raise ApiError.MethodNotAllowed("method DELETE not allowed")

    def options(self, *args, **kwargs):
        # Warning, naive implementation:
        # By default, we allow for pre-flight OPTIONS requests.
        # We could improve by returning 204 only for methods that
        # are effectively implemented by clients.
        self.response.set_status(204)
        self.response.finish()


class ApiRoute:
    """
    An API route.

    :param api_name: The name of the API to which this route belongs to.
    :param path: The route path which may include path variable templates.
    :param handler_cls: The route handler class.
        Must be derived from ```ApiHandler```.
    :param handler_kwargs: Optional keyword arguments passed to
        the *handler_cls* when it is instantiated.
    """

    def __init__(self,
                 api_name: str,
                 path: str,
                 handler_cls: Type[ApiHandler],
                 handler_kwargs: Optional[Dict[str, Any]] = None):
        assert_instance(api_name, str, name="api_name")
        assert_instance(path, str, name="path")
        assert_instance(handler_cls, type, name="handler_cls")
        assert_true(issubclass(handler_cls, ApiHandler),
                    message=f'handler_cls must be a subclass'
                            f' of {ApiHandler.__name__},'
                            f' was {handler_cls}')
        assert_instance(handler_kwargs, (type(None), dict),
                        name="handler_kwargs")
        self.api_name = api_name
        self.path = path
        self.handler_cls = handler_cls
        self.handler_kwargs = dict(handler_kwargs or {})

    def __eq__(self, other) -> bool:
        if isinstance(other, ApiRoute):
            return self.api_name == other.api_name \
                   and self.path == other.path \
                   and self.handler_cls == other.handler_cls \
                   and self.handler_kwargs == other.handler_kwargs
        return False

    def __hash__(self) -> int:
        return hash(self.api_name) \
               + 2 * hash(self.path) \
               + 4 * hash(self.handler_cls) \
               + 16 * hash(tuple(sorted(tuple(self.handler_kwargs.items()),
                                        key=lambda p: p[0])))

    def __str__(self) -> str:
        return repr(self)

    def __repr__(self) -> str:
        args = (f"{self.api_name!r},"
                f" {self.path!r},"
                f" {self.handler_cls.__name__}")
        if self.handler_kwargs:
            args += f", handler_kwargs={self.handler_kwargs!r}"
        return f"ApiRoute({args})"


class ApiError(Exception):
    """
    An API error.
    This exception should be raised to terminate the current request
    with a defined HTTP status code.

    :param status_code: The HTTP status code
    :param message: Optional message
    """

    def __init__(self,
                 status_code: int,
                 message: Optional[str] = None):
        super().__init__(status_code, message)

    BadRequest: Type["_DerivedApiError"]
    Unauthorized: Type["_DerivedApiError"]
    Forbidden: Type["_DerivedApiError"]
    NotFound: Type["_DerivedApiError"]
    MethodNotAllowed: Type["_DerivedApiError"]
    Conflict: Type["_DerivedApiError"]
    Gone: Type["_DerivedApiError"]
    InternalServerError: Type["_DerivedApiError"]
    NotImplemented: Type["_DerivedApiError"]
    InvalidServerConfig: Type["_DerivedApiError"]

    @property
    def status_code(self) -> int:
        return self.args[0]

    @property
    def message(self) -> Optional[str]:
        return self.args[1]

    def __str__(self):
        text = f'HTTP status {self.status_code}'
        if self.message:
            text += f': {self.message}'
        return text


class _DerivedApiError(ApiError):
    def __init__(self, message: Optional[str] = None):
        super().__init__(500, message=message)


class _BadRequest(ApiError):
    def __init__(self, message: Optional[str] = None):
        super().__init__(400, message=message)


class _Unauthorized(ApiError):
    def __init__(self, message: Optional[str] = None):
        super().__init__(401, message=message)


class _Forbidden(ApiError):
    def __init__(self, message: Optional[str] = None):
        super().__init__(403, message=message)


class _NotFound(ApiError):
    def __init__(self, message: Optional[str] = None):
        super().__init__(404, message=message)


class _MethodNotAllowed(ApiError):
    def __init__(self, message: Optional[str] = None):
        super().__init__(405, message=message)


class _Conflict(ApiError):
    def __init__(self, message: Optional[str] = None):
        super().__init__(409, message=message)


class _Gone(ApiError):
    def __init__(self, message: Optional[str] = None):
        super().__init__(410, message=message)


class _InternalServerError(ApiError):
    def __init__(self, message: Optional[str] = None):
        super().__init__(500, message=message)


class _NotImplemented(ApiError):
    def __init__(self, message: Optional[str] = None):
        super().__init__(501, message=message)


class _InvalidServerConfig(ApiError):
    def __init__(self, message: Optional[str] = None):
        super().__init__(580, message=message)


ApiError.BadRequest = _BadRequest
ApiError.Unauthorized = _Unauthorized
ApiError.Forbidden = _Forbidden
ApiError.NotFound = _NotFound
ApiError.MethodNotAllowed = _MethodNotAllowed
ApiError.Conflict = _Conflict
ApiError.Gone = _Gone
ApiError.InternalServerError = _InternalServerError
ApiError.NotImplemented = _NotImplemented
ApiError.InvalidServerConfig = _InvalidServerConfig
