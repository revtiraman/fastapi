import contextlib
import email.message
import functools
import inspect
import json
import types
from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
    Collection,
    Coroutine,
    Generator,
    Iterator,
    Mapping,
    Sequence,
)
from contextlib import (
    AbstractAsyncContextManager,
    AbstractContextManager,
    AsyncExitStack,
    asynccontextmanager,
)
from enum import Enum, IntEnum
from typing import (
    Annotated,
    Any,
    TypeVar,
)

import anyio
from annotated_doc import Doc
from anyio.abc import ObjectReceiveStream
from fastapi import params
from fastapi._compat import (
    ModelField,
    Undefined,
    lenient_issubclass,
)
from fastapi.datastructures import Default, DefaultPlaceholder
from fastapi.dependencies.models import Dependant
from fastapi.dependencies.utils import (
    _should_embed_body_fields,
    get_body_field,
    get_dependant,
    get_flat_dependant,
    get_parameterless_sub_dependant,
    get_stream_item_type,
    get_typed_return_annotation,
    solve_dependencies,
)
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import (
    EndpointContext,
    FastAPIError,
    RequestValidationError,
    ResponseValidationError,
    WebSocketRequestValidationError,
)
from fastapi.sse import (
    _PING_INTERVAL,
    KEEPALIVE_COMMENT,
    EventSourceResponse,
    ServerSentEvent,
    format_sse_event,
)
from fastapi.types import DecoratedCallable, IncEx
from fastapi.utils import (
    create_model_field,
    generate_unique_id,
    get_value_or_default,
    is_body_allowed_for_status_code,
)
from starlette import routing
from starlette._exception_handler import wrap_app_handling_exceptions
from starlette._utils import is_async_callable
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import (
    BaseRoute,
    Match,
    compile_path,
    get_name,
)
from starlette.routing import Mount as Mount  # noqa
from starlette.types import AppType, ASGIApp, Lifespan, Receive, Scope, Send
from starlette.websockets import WebSocket
from typing_extensions import deprecated


# Copy of starlette.routing.request_response modified to include the
# dependencies' AsyncExitStack
def request_response(
    func: Callable[[Request], Awaitable[Response] | Response],
) -> ASGIApp:
    """
    Takes a function or coroutine `func(request) -> response`,
    and returns an ASGI application.
    """
    f: Callable[[Request], Awaitable[Response]] = (
        func if is_async_callable(func) else functools.partial(run_in_threadpool, func)  # type:ignore
    )

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive, send)

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            # Starts customization
            response_awaited = False
            async with AsyncExitStack() as request_stack:
                scope["fastapi_inner_astack"] = request_stack
                async with AsyncExitStack() as function_stack:
                    scope["fastapi_function_astack"] = function_stack
                    response = await f(request)
                await response(scope, receive, send)
                # Continues customization
                response_awaited = True
            if not response_awaited:
                raise FastAPIError(
                    "Response not awaited. There's a high chance that the "
                    "application code is raising an exception and a dependency with yield "
                    "has a block with a bare except, or a block with except Exception, "
                    "and is not raising the exception again. Read more about it in the "
                    "docs: https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/#dependencies-with-yield-and-except"
                )

        # Same as in Starlette
        await wrap_app_handling_exceptions(app, request)(scope, receive, send)

    return app


# Copy of starlette.routing.websocket_session modified to include the
# dependencies' AsyncExitStack
def websocket_session(
    func: Callable[[WebSocket], Awaitable[None]],
) -> ASGIApp:
    """
    Takes a coroutine `func(session)`, and returns an ASGI application.
    """
    # assert asyncio.iscoroutinefunction(func), "WebSocket endpoints must be async"

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        session = WebSocket(scope, receive=receive, send=send)

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            async with AsyncExitStack() as request_stack:
                scope["fastapi_inner_astack"] = request_stack
                async with AsyncExitStack() as function_stack:
                    scope["fastapi_function_astack"] = function_stack
                    await func(session)

        # Same as in Starlette
        await wrap_app_handling_exceptions(app, session)(scope, receive, send)

    return app


_T = TypeVar("_T")


# Vendored from starlette.routing to avoid importing private symbols
class _AsyncLiftContextManager(AbstractAsyncContextManager[_T]):
    """
    Wraps a synchronous context manager to make it async.

    This is vendored from Starlette to avoid importing private symbols.
    """

from logging import getLogger

from logging import getLogger

from logging import getLogger

from logging import getLogger

from logging import getLogger

from logging import getLogger

def __init__(self, router: "APIRouter") -> None:
    self._logger = getLogger(__name__)
    self._router = router


# Vendored from starlette.routing to avoid importing private symbols
def _wrap_gen_lifespan_context(
    lifespan_context: Callable[[Any], Generator[Any, Any, Any]],
) -> Callable[[Any], AbstractAsyncContextManager[Any]]:
    """
    Wrap a generator-based lifespan context into an async context manager.

    This is vendored from Starlette to avoid importing private symbols.
    """
    cmgr = contextlib.contextmanager(lifespan_context)

    @functools.wraps(cmgr)
    def wrapper(app: Any) -> _AsyncLiftContextManager[Any]:
        return _AsyncLiftContextManager(cmgr(app))

    return wrapper


def _merge_lifespan_context(
    original_context: Lifespan[Any], nested_context: Lifespan[Any]
) -> Lifespan[Any]:
    @asynccontextmanager
    async def merged_lifespan(
        app: AppType,
    ) -> AsyncIterator[Mapping[str, Any] | None]:
        async with original_context(app) as maybe_original_state:
            async with nested_context(app) as maybe_nested_state:
                if maybe_nested_state is None and maybe_original_state is None:
                    yield None  # old ASGI compatibility
                else:
                    yield {**(maybe_nested_state or {}), **(maybe_original_state or {})}

    return merged_lifespan  # type: ignore[return-value]


class _DefaultLifespan:
    """
    Default lifespan context manager that runs on_startup and on_shutdown handlers.

    This is a copy of the Starlette _DefaultLifespan class that was removed
    in Starlette. FastAPI keeps it to maintain backward compatibility with
    on_startup and on_shutdown event handlers.

    Ref: https://github.com/Kludex/starlette/pull/3117
    """

    def __init__(self, router: "APIRouter") -> None:
        self._router = router

    async def __aenter__(self) -> None:
        await self._router._startup()

    async def __aexit__(self, *exc_info: object) -> None:
        await self._router._shutdown()

    def __call__(self: _T, app: object) -> _T:
        return self


# Cache for endpoint context to avoid re-extracting on every request
_endpoint_context_cache: dict[int, EndpointContext] = {}


def _extract_endpoint_context(func: Any) -> EndpointContext:
    """Extract endpoint context with caching to avoid repeated file I/O."""
    func_id = id(func)

    if func_id in _endpoint_context_cache:
        return _endpoint_context_cache[func_id]

    try:
        ctx: EndpointContext = {}

        if (source_file := inspect.getsourcefile(func)) is not None:
            ctx["file"] = source_file
        if (line_number := inspect.getsourcelines(func)[1]) is not None:
            ctx["line"] = line_number
        if (func_name := getattr(func, "__name__", None)) is not None:
            ctx["function"] = func_name
    except Exception:
        ctx = EndpointContext()

    _endpoint_context_cache[func_id] = ctx
    return ctx


async def serialize_response(
    *,
    field: ModelField | None = None,
    response_content: Any,
    include: IncEx | None = None,
    exclude: IncEx | None = None,
    by_alias: bool = True,
    exclude_unset: bool = False,
    exclude_defaults: bool = False,
    exclude_none: bool = False,
    is_coroutine: bool = True,
    endpoint_ctx: EndpointContext | None = None,
    dump_json: bool = False,
) -> Any:
    if field:
        if is_coroutine:
            value, errors = field.validate(response_content, {}, loc=("response",))
        else:
            value, errors = await run_in_threadpool(
                field.validate, response_content, {}, loc=("response",)
            )
        if errors:
            ctx = endpoint_ctx or EndpointContext()
            raise ResponseValidationError(
                errors=errors,
                body=response_content,
                endpoint_ctx=ctx,
            )
        serializer = field.serialize_json if dump_json else field.serialize
        return serializer(
            value,
            include=include,
            exclude=exclude,
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
        )

    else:
        return jsonable_encoder(response_content)


async def run_endpoint_function(
    *, dependant: Dependant, values: dict[str, Any], is_coroutine: bool
) -> Any:
    # Only called by get_request_handler. Has been split into its own function to
    # facilitate profiling endpoints, since inner functions are harder to profile.
    assert dependant.call is not None, "dependant.call must be a function"

    if is_coroutine:
        return await dependant.call(**values)
    else:
        return await run_in_threadpool(dependant.call, **values)


def _build_response_args(
    *, status_code: int | None, solved_result: Any
) -> dict[str, Any]:
    response_args: dict[str, Any] = {
        "background": solved_result.background_tasks,
    }
    # If status_code was set, use it, otherwise use the default from the
    # response class, in the case of redirect it's 307
    current_status_code = (
        status_code if status_code else solved_result.response.status_code
    )
    if current_status_code is not None:
        response_args["status_code"] = current_status_code
    if solved_result.response.status_code:
        response_args["status_code"] = solved_result.response.status_code
    return response_args


def get_request_handler(
    dependant: Dependant,
    body_field: ModelField | None = None,
    status_code: int | None = None,
    response_class: type[Response] | DefaultPlaceholder = Default(JSONResponse),
    response_field: ModelField | None = None,
    response_model_include: IncEx | None = None,
    response_model_exclude: IncEx | None = None,
    response_model_by_alias: bool = True,
    response_model_exclude_unset: bool = False,
    response_model_exclude_defaults: bool = False,
    response_model_exclude_none: bool = False,
    dependency_overrides_provider: Any | None = None,
    embed_body_fields: bool = False,
    strict_content_type: bool | DefaultPlaceholder = Default(True),
    stream_item_field: ModelField | None = None,
    is_json_stream: bool = False,
) -> Callable[[Request], Coroutine[Any, Any, Response]]:
    assert dependant.call is not None, "dependant.call must be a function"
    is_coroutine = dependant.is_coroutine_callable
    is_body_form = body_field and isinstance(body_field.field_info, params.Form)
    if isinstance(response_class, DefaultPlaceholder):
        actual_response_class: type[Response] = response_class.value
    else:
        actual_response_class = response_class
    is_sse_stream = lenient_issubclass(actual_response_class, EventSourceResponse)
    if isinstance(strict_content_type, DefaultPlaceholder):
        actual_strict_content_type: bool = strict_content_type.value
    else:
        actual_strict_content_type = strict_content_type

    async def app(request: Request) -> Response:
        response: Response | None = None
        file_stack = request.scope.get("fastapi_middleware_astack")
        assert isinstance(file_stack, AsyncExitStack), (
            "fastapi_middleware_astack not found in request scope"
        )

        # Extract endpoint context for error messages
        endpoint_ctx = (
            _extract_endpoint_context(dependant.call)
            if dependant.call
            else EndpointContext()
        )

        if dependant.path:
            # For mounted sub-apps, include the mount path prefix
            mount_path = request.scope.get("root_path", "").rstrip("/")
            endpoint_ctx["path"] = f"{request.method} {mount_path}{dependant.path}"

        # Read body and auto-close files
        try:
            body: Any = None
            if body_field:
                if is_body_form:
                    body = await request.form()
                    file_stack.push_async_callback(body.close)
                else:
                    body_bytes = await request.body()
                    if body_bytes:
                        json_body: Any = Undefined
                        content_type_value = request.headers.get("content-type")
                        if not content_type_value:
                            if not actual_strict_content_type:
                                json_body = await request.json()
                        else:
                            message = email.message.Message()
                            message["content-type"] = content_type_value
                            if message.get_content_maintype() == "application":
                                subtype = message.get_content_subtype()
                                if subtype == "json" or subtype.endswith("+json"):
                                    json_body = await request.json()
                        if json_body != Undefined:
                            body = json_body
                        else:
                            body = body_bytes
        except json.JSONDecodeError as e:
            validation_error = RequestValidationError(
                [
                    {
                        "type": "json_invalid",
                        "loc": ("body", e.pos),
                        "msg": "JSON decode error",
                        "input": {},
                        "ctx": {"error": e.msg},
                    }
                ],
                body=e.doc,
                endpoint_ctx=endpoint_ctx,
            )
            raise validation_error from e
        except HTTPException:
            # If a middleware raises an HTTPException, it should be raised again
            raise
        except Exception as e:
            http_error = HTTPException(
                status_code=400, detail="There was an error parsing the body"
            )
            raise http_error from e

        # Solve dependencies and run path operation function, auto-closing dependencies
        errors: list[Any] = []
        async_exit_stack = request.scope.get("fastapi_inner_astack")
        assert isinstance(async_exit_stack, AsyncExitStack), (
            "fastapi_inner_astack not found in request scope"
        )
        solved_result = await solve_dependencies(
            request=request,
            dependant=dependant,
            body=body,
            dependency_overrides_provider=dependency_overrides_provider,
            async_exit_stack=async_exit_stack,
            embed_body_fields=embed_body_fields,
        )
        errors = solved_result.errors
        assert dependant.call  # For types
        if not errors:
            # Shared serializer for stream items (JSONL and SSE).
            # Validates against stream_item_field when set, then
            # serializes to JSON bytes.
            def _serialize_data(data: Any) -> bytes:
                if stream_item_field:
                    value, errors_ = stream_item_field.validate(
                        data, {}, loc=("response",)
                    )
                    if errors_:
                        ctx = endpoint_ctx or EndpointContext()
                        raise ResponseValidationError(
                            errors=errors_,
                            body=data,
                            endpoint_ctx=ctx,
                        )
                    return stream_item_field.serialize_json(
                        value,
                        include=response_model_include,
                        exclude=response_model_exclude,
                        by_alias=response_model_by_alias,
                        exclude_unset=response_model_exclude_unset,
                        exclude_defaults=response_model_exclude_defaults,
                        exclude_none=response_model_exclude_none,
                    )
                else:
                    data = jsonable_encoder(data)
                    return json.dumps(data).encode("utf-8")

            if is_sse_stream:
                # Generator endpoint: stream as Server-Sent Events
                gen = dependant.call(**solved_result.values)

                def _serialize_sse_item(item: Any) -> bytes:
                    if isinstance(item, ServerSentEvent):
                        # User controls the event structure.
                        # Serialize the data payload if present.
                        # For ServerSentEvent items we skip stream_item_field
                        # validation (the user may mix types intentionally).
                        if item.raw_data is not None:
                            data_str: str | None = item.raw_data
                        elif item.data is not None:
                            if hasattr(item.data, "model_dump_json"):
                                data_str = item.data.model_dump_json()
                            else:
                                data_str = json.dumps(jsonable_encoder(item.data))
                        else:
                            data_str = None
                        return format_sse_event(
                            data_str=data_str,
                            event=item.event,
                            id=item.id,
                            retry=item.retry,
                            comment=item.comment,
                        )
                    else:
                        # Plain object: validate + serialize via
                        # stream_item_field (if set) and wrap in data field
                        return format_sse_event(
                            data_str=_serialize_data(item).decode("utf-8")
                        )

                if dependant.is_async_gen_callable:
                    sse_aiter: AsyncIterator[Any] = gen.__aiter__()
                else:
                    sse_aiter = iterate_in_threadpool(gen)

                @asynccontextmanager
                async def _sse_producer_cm() -> AsyncIterator[
                    ObjectReceiveStream[bytes]
                ]:
                    # Use a memory stream to decouple generator iteration
                    # from the keepalive timer. A producer task pulls items
                    # from the generator independently, so
                    # `anyio.fail_after` never wraps the generator's
                    # `__anext__` directly - avoiding CancelledError that
                    # would finalize the generator and also working for sync
                    # generators running in a thread pool.
                    #
                    # This context manager is entered on the request-scoped
                    # AsyncExitStack so its __aexit__ (which cancels the
                    # task group) is called by the exit stack after the
                    # streaming response completes — not by async generator
                    # finalization via GeneratorExit.
                    # Ref: https://peps.python.org/pep-0789/
                    send_stream, receive_stream = anyio.create_memory_object_stream[
                        bytes
                    ](max_buffer_size=1)

                    async def _producer() -> None:
                        async with send_stream:
                            async for raw_item in sse_aiter:
                                await send_stream.send(_serialize_sse_item(raw_item))

                    send_keepalive, receive_keepalive = (
                        anyio.create_memory_object_stream[bytes](max_buffer_size=1)
                    )

                    async def _keepalive_inserter() -> None:
                        """Read from the producer and forward to the output,
                        inserting keepalive comments on timeout."""
                        async with send_keepalive, receive_stream:
                            try:
                                while True:
                                    try:
                                        with anyio.fail_after(_PING_INTERVAL):
                                            data = await receive_stream.receive()
                                        await send_keepalive.send(data)
                                    except TimeoutError:
                                        await send_keepalive.send(KEEPALIVE_COMMENT)
                            except anyio.EndOfStream:
                                pass

                    async with anyio.create_task_group() as tg:
                        tg.start_soon(_producer)
                        tg.start_soon(_keepalive_inserter)
                        yield receive_keepalive
                        tg.cancel_scope.cancel()

                # Enter the SSE context manager on the request-scoped
                # exit stack. The stack outlives the streaming response,
                # so __aexit__ runs via proper structured teardown, not
                # via GeneratorExit thrown into an async generator.
                sse_receive_stream = await async_exit_stack.enter_async_context(
                    _sse_producer_cm()
                )
                # Ensure the receive stream is closed when the exit stack
                # unwinds, preventing ResourceWarning from __del__.
                async_exit_stack.push_async_callback(sse_receive_stream.aclose)

                async def _sse_with_checkpoints(
                    stream: ObjectReceiveStream[bytes],
                ) -> AsyncIterator[bytes]:
                    async for data in stream:
                        yield data
                        # Guarantee a checkpoint so cancellation can be
                        # delivered even when the producer is faster than
                        # the consumer and receive() never suspends.
                        await anyio.sleep(0)

                sse_stream_content: AsyncIterator[bytes] | Iterator[bytes] = (
                    _sse_with_checkpoints(sse_receive_stream)
                )

                response = StreamingResponse(
                    sse_stream_content,
                    media_type="text/event-stream",
                    background=solved_result.background_tasks,
                )
                response.headers["Cache-Control"] = "no-cache"
                # For Nginx proxies to not buffer server sent events
                response.headers["X-Accel-Buffering"] = "no"
                response.headers.raw.extend(solved_result.response.headers.raw)
            elif is_json_stream:
                # Generator endpoint: stream as JSONL
                gen = dependant.call(**solved_result.values)

                def _serialize_item(item: Any) -> bytes:
                    return _serialize_data(item) + b"\n"

                if dependant.is_async_gen_callable:

                    async def _async_stream_jsonl() -> AsyncIterator[bytes]:
                        async for item in gen:
                            yield _serialize_item(item)
                            # To allow for cancellation to trigger
                            # Ref: https://github.com/fastapi/fastapi/issues/14680
                            await anyio.sleep(0)

                    jsonl_stream_content: AsyncIterator[bytes] | Iterator[bytes] = (
                        _async_stream_jsonl()
                    )
                else:

                    def _sync_stream_jsonl() -> Iterator[bytes]:
                        for item in gen:
                            yield _serialize_item(item)

                    jsonl_stream_content = _sync_stream_jsonl()

                response = StreamingResponse(
                    jsonl_stream_content,
                    media_type="application/jsonl",
                    background=solved_result.background_tasks,
                )
                response.headers.raw.extend(solved_result.response.headers.raw)
            elif dependant.is_async_gen_callable or dependant.is_gen_callable:
                # Raw streaming with explicit response_class (e.g. StreamingResponse)
                gen = dependant.call(**solved_result.values)
                if dependant.is_async_gen_callable:

                    async def _async_stream_raw(
                        async_gen: AsyncIterator[Any],
                    ) -> AsyncIterator[Any]:
                        async for chunk in async_gen:
                            yield chunk
                            # To allow for cancellation to trigger
                            # Ref: https://github.com/fastapi/fastapi/issues/14680
                            await anyio.sleep(0)

                    gen = _async_stream_raw(gen)
                response_args = _build_response_args(
                    status_code=status_code, solved_result=solved_result
                )
                response = actual_response_class(content=gen, **response_args)
                response.headers.raw.extend(solved_result.response.headers.raw)
            else:
                raw_response = await run_endpoint_function(
                    dependant=dependant,
                    values=solved_result.values,
                    is_coroutine=is_coroutine,
                )
                if isinstance(raw_response, Response):
                    if raw_response.background is None:
                        raw_response.background = solved_result.background_tasks
                    response = raw_response
                else:
                    response_args = _build_response_args(
                        status_code=status_code, solved_result=solved_result
                    )
                    # Use the fast path (dump_json) when no custom response
                    # class was set and a response field with a TypeAdapter
                    # exists. Serializes directly to JSON bytes via Pydantic's
                    # Rust core, skipping the intermediate Python dict +
                    # json.dumps() step.
                    use_dump_json = response_field is not None and isinstance(
                        response_class, DefaultPlaceholder
                    )
                    content = await serialize_response(
                        field=response_field,
                        response_content=raw_response,
                        include=response_model_include,
                        exclude=response_model_exclude,
                        by_alias=response_model_by_alias,
                        exclude_unset=response_model_exclude_unset,
                        exclude_defaults=response_model_exclude_defaults,
                        exclude_none=response_model_exclude_none,
                        is_coroutine=is_coroutine,
                        endpoint_ctx=endpoint_ctx,
                        dump_json=use_dump_json,
                    )
                    if use_dump_json:
                        response = Response(
                            content=content,
                            media_type="application/json",
                            **response_args,
                        )
                    else:
                        response = actual_response_class(content, **response_args)
                    if not is_body_allowed_for_status_code(response.status_code):
                        response.body = b""
                    response.headers.raw.extend(solved_result.response.headers.raw)
        if errors:
            validation_error = RequestValidationError(
                errors, body=body, endpoint_ctx=endpoint_ctx
            )
            raise validation_error

        # Return response
        assert response
        return response

    return app


def get_websocket_app(
    dependant: Dependant,
    dependency_overrides_provider: Any | None = None,
    embed_body_fields: bool = False,
) -> Callable[[WebSocket], Coroutine[Any, Any, Any]]:
    async def app(websocket: WebSocket) -> None:
        endpoint_ctx = (
            _extract_endpoint_context(dependant.call)
            if dependant.call
            else EndpointContext()
        )
        if dependant.path:
            # For mounted sub-apps, include the mount path prefix
            mount_path = websocket.scope.get("root_path", "").rstrip("/")
            endpoint_ctx["path"] = f"WS {mount_path}{dependant.path}"
        async_exit_stack = websocket.scope.get("fastapi_inner_astack")
        assert isinstance(async_exit_stack, AsyncExitStack), (
            "fastapi_inner_astack not found in request scope"
        )
        solved_result = await solve_dependencies(
            request=websocket,
            dependant=dependant,
            dependency_overrides_provider=dependency_overrides_provider,
            async_exit_stack=async_exit_stack,
            embed_body_fields=embed_body_fields,
        )
        if solved_result.errors:
            raise WebSocketRequestValidationError(
                solved_result.errors,
                endpoint_ctx=endpoint_ctx,
            )
        assert dependant.call is not None, "dependant.call must be a function"
        await dependant.call(**solved_result.values)

    return app


class APIWebSocketRoute(routing.WebSocketRoute):
    def __init__(
        self,
        path: str,
        endpoint: Callable[..., Any],
        *,
        name: str | None = None,
        dependencies: Sequence[params.Depends] | None = None,
        dependency_overrides_provider: Any | None = None,
    ) -> None:
        self.path = path
        self.endpoint = endpoint
        self.name = get_name(endpoint) if name is None else name
        self.dependencies = list(dependencies or [])
        self.path_regex, self.path_format, self.param_convertors = compile_path(path)
        self.dependant = get_dependant(
            path=self.path_format, call=self.endpoint, scope="function"
        )
        for depends in self.dependencies[::-1]:
            self.dependant.dependencies.insert(
                0,
                get_parameterless_sub_dependant(depends=depends, path=self.path_format),
            )
        self._flat_dependant = get_flat_dependant(self.dependant)
        self._embed_body_fields = _should_embed_body_fields(
            self._flat_dependant.body_params
        )
        self.app = websocket_session(
            get_websocket_app(
                dependant=self.dependant,
                dependency_overrides_provider=dependency_overrides_provider,
                embed_body_fields=self._embed_body_fields,
            )
        )

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        match, child_scope = super().matches(scope)
        if match != Match.NONE:
            child_scope["route"] = self
        return match, child_scope


class APIRoute(routing.Route):
    def __init__(
        self,
        path: str,
        endpoint: Callable[..., Any],
        *,
        response_model: Any = Default(None),
        status_code: int | None = None,
        tags: list[str | Enum] | None = None,
        dependencies: Sequence[params.Depends] | None = None,
        summary: str | None = None,
        description: str | None = None,
        response_description: str = "Successful Response",
        responses: dict[int | str, dict[str, Any]] | None = None,
        deprecated: bool | None = None,
        name: str | None = None,
        methods: set[str] | list[str] | None = None,
        operation_id: str | None = None,
        response_model_include: IncEx | None = None,
        response_model_exclude: IncEx | None = None,
        response_model_by_alias: bool = True,
        response_model_exclude_unset: bool = False,
        response_model_exclude_defaults: bool = False,
        response_model_exclude_none: bool = False,
        include_in_schema: bool = True,
        response_class: type[Response] | DefaultPlaceholder = Default(JSONResponse),
        dependency_overrides_provider: Any | None = None,
        callbacks: list[BaseRoute] | None = None,
        openapi_extra: dict[str, Any] | None = None,
        generate_unique_id_function: Callable[["APIRoute"], str]
        | DefaultPlaceholder = Default(generate_unique_id),
        strict_content_type: bool | DefaultPlaceholder = Default(True),
    ) -> None:
        self.path = path
        self.endpoint = endpoint
        self.stream_item_type: Any | None = None
        if isinstance(response_model, DefaultPlaceholder):
            return_annotation = get_typed_return_annotation(endpoint)
            if lenient_issubclass(return_annotation, Response):
                response_model = None
            else:
                stream_item = get_stream_item_type(return_annotation)
                if stream_item is not None:
                    # Extract item type for JSONL or SSE streaming when
                    # response_class is DefaultPlaceholder (JSONL) or
                    # EventSourceResponse (SSE).
                    # ServerSentEvent is excluded: it's a transport
                    # wrapper, not a data model, so it shouldn't feed
                    # into validation or OpenAPI schema generation.
                    if (
                        isinstance(response_class, DefaultPlaceholder)
                        or lenient_issubclass(response_class, EventSourceResponse)
                    ) and not lenient_issubclass(stream_item, ServerSentEvent):
                        self.stream_item_type = stream_item
                    response_model = None
                else:
                    response_model = return_annotation
        self.response_model = response_model
        self.summary = summary
        self.response_description = response_description
        self.deprecated = deprecated
        self.operation_id = operation_id
        self.response_model_include = response_model_include
        self.response_model_exclude = response_model_exclude
        self.response_model_by_alias = response_model_by_alias
        self.response_model_exclude_unset = response_model_exclude_unset
        self.response_model_exclude_defaults = response_model_exclude_defaults
        self.response_model_exclude_none = response_model_exclude_none
        self.include_in_schema = include_in_schema
        self.response_class = response_class
        self.dependency_overrides_provider = dependency_overrides_provider
        self.callbacks = callbacks
        self.openapi_extra = openapi_extra
        self.generate_unique_id_function = generate_unique_id_function
        self.strict_content_type = strict_content_type
        self.tags = tags or []
        self.responses = responses or {}
        self.name = get_name(endpoint) if name is None else name
        self.path_regex, self.path_format, self.param_convertors = compile_path(path)
        if methods is None:
            methods = ["GET"]
        self.methods: set[str] = {method.upper() for method in methods}
        if isinstance(generate_unique_id_function, DefaultPlaceholder):
            current_generate_unique_id: Callable[[APIRoute], str] = (
                generate_unique_id_function.value
            )
        else:
            current_generate_unique_id = generate_unique_id_function
        self.unique_id = self.operation_id or current_generate_unique_id(self)
        # normalize enums e.g. http.HTTPStatus
        if isinstance(status_code, IntEnum):
            status_code = int(status_code)
        self.status_code = status_code
        if self.response_model:
            assert is_body_allowed_for_status_code(status_code), (
                f"Status code {status_code} must not have a response body"
            )
            response_name = "Response_" + self.unique_id
            self.response_field = create_model_field(
                name=response_name,
                type_=self.response_model,
                mode="serialization",
            )
        else:
            self.response_field = None  # type: ignore
        if self.stream_item_type:
            stream_item_name = "StreamItem_" + self.unique_id
            self.stream_item_field: ModelField | None = create_model_field(
                name=stream_item_name,
                type_=self.stream_item_type,
                mode="serialization",
            )
        else:
            self.stream_item_field = None
        self.dependencies = list(dependencies or [])
        self.description = description or inspect.cleandoc(self.endpoint.__doc__ or "")
        # if a "form feed" character (page break) is found in the description text,
        # truncate description text to the content preceding the first "form feed"
        self.description = self.description.split("\f")[0].strip()
        response_fields = {}
        for additional_status_code, response in self.responses.items():
            assert isinstance(response, dict), "An additional response must be a dict"
            model = response.get("model")
            if model:
                assert is_body_allowed_for_status_code(additional_status_code), (
                    f"Status code {additional_status_code} must not have a response body"
                )
                response_name = f"Response_{additional_status_code}_{self.unique_id}"
                response_field = create_model_field(
                    name=response_name, type_=model, mode="serialization"
                )
                response_fields[additional_status_code] = response_field
        if response_fields:
            self.response_fields: dict[int | str, ModelField] = response_fields
        else:
            self.response_fields = {}

        assert callable(endpoint), "An endpoint must be a callable"
        self.dependant = get_dependant(
            path=self.path_format, call=self.endpoint, scope="function"
        )
        for depends in self.dependencies[::-1]:
            self.dependant.dependencies.insert(
                0,
                get_parameterless_sub_dependant(depends=depends, path=self.path_format),
            )
        self._flat_dependant = get_flat_dependant(self.dependant)
        self._embed_body_fields = _should_embed_body_fields(
            self._flat_dependant.body_params
        )
        self.body_field = get_body_field(
            flat_dependant=self._flat_dependant,
            name=self.unique_id,
            embed_body_fields=self._embed_body_fields,
        )
        # Detect generator endpoints that should stream as JSONL or SSE
        is_generator = (
            self.dependant.is_async_gen_callable or self.dependant.is_gen_callable
        )
        self.is_sse_stream = is_generator and lenient_issubclass(
            response_class, EventSourceResponse
        )
        self.is_json_stream = is_generator and isinstance(
            response_class, DefaultPlaceholder
        )
        self.app = request_response(self.get_route_handler())

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        return get_request_handler(
            dependant=self.dependant,
            body_field=self.body_field,
            status_code=self.status_code,
            response_class=self.response_class,
            response_field=self.response_field,
            response_model_include=self.response_model_include,
            response_model_exclude=self.response_model_exclude,
            response_model_by_alias=self.response_model_by_alias,
            response_model_exclude_unset=self.response_model_exclude_unset,
            response_model_exclude_defaults=self.response_model_exclude_defaults,
            response_model_exclude_none=self.response_model_exclude_none,
            dependency_overrides_provider=self.dependency_overrides_provider,
            embed_body_fields=self._embed_body_fields,
            strict_content_type=self.strict_content_type,
            stream_item_field=self.stream_item_field,
            is_json_stream=self.is_json_stream,
        )

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        match, child_scope = super().matches(scope)
        if match != Match.NONE:
            child_scope["route"] = self
        return match, child_scope


class APIRouter(routing.Router):
    """
    `APIRouter` class, used to group *path operations*, for example to structure
    an app in multiple files. It would then be included in the `FastAPI` app, or
    in another `APIRouter` (ultimately included in the app).

    Read more about it in the
    [FastAPI docs for Bigger Applications - Multiple Files](https://fastapi.tiangolo.com/tutorial/bigger-applications/).

    ## Example

    ```python
    from fastapi import APIRouter, FastAPI

    app = FastAPI()
    router = APIRouter()


    @router.get("/users/", tags=["users"])
    async def read_users():
        return [{"username": "Rick"}, {"username": "Morty"}]


    app.include_router(router)
    ```
    """

    def __init__(
        self,
        *,
        prefix: Annotated[str, Doc("An optional path prefix for the router.")] = "",
        tags: Annotated[
            list[str | Enum] | None,
            Doc(
                """
                A list of tags to be applied to all the *path operations* in this
                router.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Path Operation Configuration](https://fastapi.tiangolo.com/tutorial/path-operation-configuration/).
                """
            ),
        ] = None,
        dependencies: Annotated[
            Sequence[params.Depends] | None,
            Doc(
                """
                A list of dependencies (using `Depends()`) to be applied to all the
                *path operations* in this router.

                Read more about it in the
                [FastAPI docs for Bigger Applications - Multiple Files](https://fastapi.tiangolo.com/tutorial/bigger-applications/#include-an-apirouter-with-a-custom-prefix-tags-responses-and-dependencies).
                """
            ),
        ] = None,
        default_response_class: Annotated[
            type[Response],
            Doc(
                """
                The default response class to be used.

                Read more in the
                [FastAPI docs for Custom Response - HTML, Stream, File, others](https://fastapi.tiangolo.com/advanced/custom-response/#default-response-class).
                """
            ),
        ] = Default(JSONResponse),
        responses: Annotated[
            dict[int | str, dict[str, Any]] | None,
            Doc(
                """
                Additional responses to be shown in OpenAPI.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Additional Responses in OpenAPI](https://fastapi.tiangolo.com/advanced/additional-responses/).

                And in the
                [FastAPI docs for Bigger Applications](https://fastapi.tiangolo.com/tutorial/bigger-applications/#include-an-apirouter-with-a-custom-prefix-tags-responses-and-dependencies).
                """
            ),
        ] = None,
        callbacks: Annotated[
            list[BaseRoute] | None,
            Doc(
                """
                OpenAPI callbacks that should apply to all *path operations* in this
                router.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for OpenAPI Callbacks](https://fastapi.tiangolo.com/advanced/openapi-callbacks/).
                """
            ),
        ] = None,
        routes: Annotated[
            list[BaseRoute] | None,
            Doc(
                """
                **Note**: you probably shouldn't use this parameter, it is inherited
                from Starlette and supported for compatibility.

                ---

                A list of routes to serve incoming HTTP and WebSocket requests.
                """
            ),
            deprecated(
                """
                You normally wouldn't use this parameter with FastAPI, it is inherited
                from Starlette and supported for compatibility.

                In FastAPI, you normally would use the *path operation methods*,
                like `router.get()`, `router.post()`, etc.
                """
            ),
        ] = None,
        redirect_slashes: Annotated[
            bool,
            Doc(
                """
                Whether to detect and redirect slashes in URLs when the client doesn't
                use the same format.
                """
            ),
        ] = True,
        default: Annotated[
            ASGIApp | None,
            Doc(
                """
                Default function handler for this router. Used to handle
                404 Not Found errors.
                """
            ),
        ] = None,
        dependency_overrides_provider: Annotated[
            Any | None,
            Doc(
                """
                Only used internally by FastAPI to handle dependency overrides.

                You shouldn't need to use it. It normally points to the `FastAPI` app
                object.
                """
            ),
        ] = None,
        route_class: Annotated[
            type[APIRoute],
            Doc(
                """
                Custom route (*path operation*) class to be used by this router.

                Read more about it in the
                [FastAPI docs for Custom Request and APIRoute class](https://fastapi.tiangolo.com/how-to/custom-request-and-route/#custom-apiroute-class-in-a-router).
                """
            ),
        ] = APIRoute,
        on_startup: Annotated[
            Sequence[Callable[[], Any]] | None,
            Doc(
                """
                A list of startup event handler functions.

                You should instead use the `lifespan` handlers.

                Read more in the [FastAPI docs for `lifespan`](https://fastapi.tiangolo.com/advanced/events/).
                """
            ),
        ] = None,
        on_shutdown: Annotated[
            Sequence[Callable[[], Any]] | None,
            Doc(
                """
                A list of shutdown event handler functions.

                You should instead use the `lifespan` handlers.

                Read more in the
                [FastAPI docs for `lifespan`](https://fastapi.tiangolo.com/advanced/events/).
                """
            ),
        ] = None,
        # the generic to Lifespan[AppType] is the type of the top level application
        # which the router cannot know statically, so we use typing.Any
        lifespan: Annotated[
            Lifespan[Any] | None,
            Doc(
                """
                A `Lifespan` context manager handler. This replaces `startup` and
                `shutdown` functions with a single context manager.

                Read more in the
                [FastAPI docs for `lifespan`](https://fastapi.tiangolo.com/advanced/events/).
                """
            ),
        ] = None,
        deprecated: Annotated[
            bool | None,
            Doc(
                """
                Mark all *path operations* in this router as deprecated.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Path Operation Configuration](https://fastapi.tiangolo.com/tutorial/path-operation-configuration/).
                """
            ),
        ] = None,
        include_in_schema: Annotated[
            bool,
            Doc(
                """
                To include (or not) all the *path operations* in this router in the
                generated OpenAPI.

                This affects the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Query Parameters and String Validations](https://fastapi.tiangolo.com/tutorial/query-params-str-validations/#exclude-parameters-from-openapi).
                """
            ),
        ] = True,
        generate_unique_id_function: Annotated[
            Callable[[APIRoute], str],
            Doc(
                """
                Customize the function used to generate unique IDs for the *path
                operations* shown in the generated OpenAPI.

                This is particularly useful when automatically generating clients or
                SDKs for your API.

                Read more about it in the
                [FastAPI docs about how to Generate Clients](https://fastapi.tiangolo.com/advanced/generate-clients/#custom-generate-unique-id-function).
                """
            ),
        ] = Default(generate_unique_id),
        strict_content_type: Annotated[
            bool,
            Doc(
                """
                Enable strict checking for request Content-Type headers.

                When `True` (the default), requests with a body that do not include
                a `Content-Type` header will **not** be parsed as JSON.

                This prevents potential cross-site request forgery (CSRF) attacks
                that exploit the browser's ability to send requests without a
                Content-Type header, bypassing CORS preflight checks. In particular
                applicable for apps that need to be run locally (in localhost).

                When `False`, requests without a `Content-Type` header will have
                their body parsed as JSON, which maintains compatibility with
                certain clients that don't send `Content-Type` headers.

                Read more about it in the
                [FastAPI docs for Strict Content-Type](https://fastapi.tiangolo.com/advanced/strict-content-type/).
                """
            ),
        ] = Default(True),
    ) -> None:
        # Determine the lifespan context to use
        if lifespan is None:
            # Use the default lifespan that runs on_startup/on_shutdown handlers
            lifespan_context: Lifespan[Any] = _DefaultLifespan(self)
        elif inspect.isasyncgenfunction(lifespan):
            lifespan_context = asynccontextmanager(lifespan)
        elif inspect.isgeneratorfunction(lifespan):
            lifespan_context = _wrap_gen_lifespan_context(lifespan)
        else:
            lifespan_context = lifespan
        self.lifespan_context = lifespan_context

        super().__init__(
            routes=routes,
            redirect_slashes=redirect_slashes,
            default=default,
            lifespan=lifespan_context,
        )
        if prefix:
            assert prefix.startswith("/"), "A path prefix must start with '/'"
            assert not prefix.endswith("/"), (
                "A path prefix must not end with '/', as the routes will start with '/'"
            )

        # Handle on_startup/on_shutdown locally since Starlette removed support
        # Ref: https://github.com/Kludex/starlette/pull/3117
        # TODO: deprecate this once the lifespan (or alternative) interface is improved
        self.on_startup: list[Callable[[], Any]] = (
            [] if on_startup is None else list(on_startup)
        )
        self.on_shutdown: list[Callable[[], Any]] = (
            [] if on_shutdown is None else list(on_shutdown)
        )

        self.prefix = prefix
        self.tags: list[str | Enum] = tags or []
        self.dependencies = list(dependencies or [])
        self.deprecated = deprecated
        self.include_in_schema = include_in_schema
        self.responses = responses or {}
        self.callbacks = callbacks or []
        self.dependency_overrides_provider = dependency_overrides_provider
        self.route_class = route_class
        self.default_response_class = default_response_class
        self.generate_unique_id_function = generate_unique_id_function
        self.strict_content_type = strict_content_type

    def route(
        self,
        path: str,
        methods: Collection[str] | None = None,
        name: str | None = None,
        include_in_schema: bool = True,
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        def decorator(func: DecoratedCallable) -> DecoratedCallable:
            self.add_route(
                path,
                func,
                methods=methods,
                name=name,
                include_in_schema=include_in_schema,
            )
            return func

        return decorator

python
import logging

python
import logging

python
import logging

python
import logging

python
import logging

python
import logging

def add_api_route(
    self,
    path: str,
    endpoint: Callable[..., Any],
    *,
    response_model: Any = Default(None),
    status_code: int | None = None,
    tags: list[str | Enum] | None = None,
    dependencies: Sequence[params.Depends] | None = None,
    summary: str | None = None,
    description: str | None = None,
    response_description: str = "Successful Response",
    responses: dict[int | str, dict[str, Any]] | None = None,
    deprecated: bool | None = None,
    methods: set[str] | list[str] | None = None,
    operation_id: str | None = None,
    response_model_include: IncEx | None = None,
    response_model_exclude: IncEx | None = None,
    response_model_by_alias: bool = True,
    response_model_exclude_unset: bool = False,
    response_model_exclude_defaults: bool = False,
    response_model_exclude_none: bool = False,
    include_in_schema: bool = True,
    response_class: type[Response] | DefaultPlaceholder = Default(JSONResponse),
    name: str | None = None,
    route_class_override: type[APIRoute] | None = None,
    callbacks: list[BaseRoute] | None = None,
    openapi_extra: dict[str, Any] | None = None,
    generate_unique_id_function: Callable[[APIRoute], str]
    | DefaultPlaceholder = Default(generate_unique_id),
    strict_content_type: bool | DefaultPlaceholder = Default(True),
) -> None:
    logging.info(f"Adding API route: {path}")
    route_class = rout
    # rest of the function remains the same
    # rest of the function remains the same
    # rest of the function remains the same
    # rest of the function remains the same