from collections.abc import Awaitable, Callable, Coroutine, Sequence
from enum import Enum
from typing import (
    Annotated,
    Any,
    TypeVar,
)

from annotated_doc import Doc
from fastapi import routing
from fastapi.datastructures import Default, DefaultPlaceholder
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
    websocket_request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError, WebSocketRequestValidationError
from fastapi.logger import logger
from fastapi.middleware.asyncexitstack import AsyncExitStackMiddleware
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from fastapi.openapi.utils import get_openapi
from fastapi.params import Depends
from fastapi.types import DecoratedCallable, IncEx
from fastapi.utils import generate_unique_id
from starlette.applications import Starlette
from starlette.datastructures import State
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.errors import ServerErrorMiddleware
from starlette.middleware.exceptions import ExceptionMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import BaseRoute
from starlette.types import ASGIApp, ExceptionHandler, Lifespan, Receive, Scope, Send
from typing_extensions import deprecated

AppType = TypeVar("AppType", bound="FastAPI")


class FastAPI(Starlette):
    """
    `FastAPI` app class, the main entrypoint to use FastAPI.

    Read more in the
    [FastAPI docs for First Steps](https://fastapi.tiangolo.com/tutorial/first-steps/).

    ## Example

    ```python
    from fastapi import FastAPI

    app = FastAPI()
    ```
    """

python
import logging

def __init__(
    self: AppType,
    *,
    debug: Annotated[
        bool,
        Doc(
            """
            Boolean indicating if debug tracebacks should be returned on server
            errors.

            Read more in the
            [Starlette docs for Applications](https://www.starlette.dev/applications/#instantiating-the-application).
            """
        ),
    ] = False,
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
            like `app.get()`, `app.post()`, etc.
            """
        ),
    ] = None,
    title: Annotated[
        str,
        Doc(
            """
            The title of the API.

            It will be added to the generated OpenAPI (e.g. visible at `/docs`).

            Read more in the
            [FastAPI docs for Metadata](https://fastapi.tiangolo.com/tutorial/metadata/).
            """
        ),
    ] = None,
    logger_name: str = "api_routes",
):
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    self.logger = logging.getLogger(logger_name)

    # Add routes to the logger
    for route in routes or []:
        self.logger.info(f"Route added: {route.path}")

    def build_middleware_stack(self) -> ASGIApp:
        # Duplicate/override from Starlette to add AsyncExitStackMiddleware
        # inside of ExceptionMiddleware, inside of custom user middlewares
        debug = self.debug
        error_handler = None
        exception_handlers: dict[Any, ExceptionHandler] = {}

        for key, value in self.exception_handlers.items():
            if key in (500, Exception):
                error_handler = value
            else:
                exception_handlers[key] = value

        middleware = (
            [Middleware(ServerErrorMiddleware, handler=error_handler, debug=debug)]
            + self.user_middleware
            + [
                Middleware(
                    ExceptionMiddleware, handlers=exception_handlers, debug=debug
                ),
                # Add FastAPI-specific AsyncExitStackMiddleware for closing files.
                # Before this was also used for closing dependencies with yield but
                # those now have their own AsyncExitStack, to properly support
                # streaming responses while keeping compatibility with the previous
                # versions (as of writing 0.117.1) that allowed doing
                # except HTTPException inside a dependency with yield.
                # This needs to happen after user middlewares because those create a
                # new contextvars context copy by using a new AnyIO task group.
                # This AsyncExitStack preserves the context for contextvars, not
                # strictly necessary for closing files but it was one of the original
                # intentions.
                # If the AsyncExitStack lived outside of the custom middlewares and
                # contextvars were set, for example in a dependency with 'yield'
                # in that internal contextvars context, the values would not be
                # available in the outer context of the AsyncExitStack.
                # By placing the middleware and the AsyncExitStack here, inside all
                # user middlewares, the same context is used.
                # This is currently not needed, only for closing files, but used to be
                # important when dependencies with yield were closed here.
                Middleware(AsyncExitStackMiddleware),
            ]
        )

        app = self.router
        for cls, args, kwargs in reversed(middleware):
            app = cls(app, *args, **kwargs)
        return app

    def openapi(self) -> dict[str, Any]:
        """
        Generate the OpenAPI schema of the application. This is called by FastAPI
        internally.

        The first time it is called it stores the result in the attribute
        `app.openapi_schema`, and next times it is called, it just returns that same
        result. To avoid the cost of generating the schema every time.

        If you need to modify the generated OpenAPI schema, you could modify it.

        Read more in the
        [FastAPI docs for OpenAPI](https://fastapi.tiangolo.com/how-to/extending-openapi/).
        """
        if not self.openapi_schema:
            self.openapi_schema = get_openapi(
                title=self.title,
                version=self.version,
                openapi_version=self.openapi_version,
                summary=self.summary,
                description=self.description,
                terms_of_service=self.terms_of_service,
                contact=self.contact,
                license_info=self.license_info,
                routes=self.routes,
                webhooks=self.webhooks.routes,
                tags=self.openapi_tags,
                servers=self.servers,
                separate_input_output_schemas=self.separate_input_output_schemas,
                external_docs=self.openapi_external_docs,
            )
        return self.openapi_schema

    def setup(self) -> None:
        if self.openapi_url:

            async def openapi(req: Request) -> JSONResponse:
                root_path = req.scope.get("root_path", "").rstrip("/")
                schema = self.openapi()
                if root_path and self.root_path_in_servers:
                    server_urls = {s.get("url") for s in schema.get("servers", [])}
                    if root_path not in server_urls:
                        schema = dict(schema)
                        schema["servers"] = [{"url": root_path}] + schema.get(
                            "servers", []
                        )
                return JSONResponse(schema)

            self.add_route(self.openapi_url, openapi, include_in_schema=False)
        if self.openapi_url and self.docs_url:

            async def swagger_ui_html(req: Request) -> HTMLResponse:
                root_path = req.scope.get("root_path", "").rstrip("/")
                openapi_url = root_path + self.openapi_url
                oauth2_redirect_url = self.swagger_ui_oauth2_redirect_url
                if oauth2_redirect_url:
                    oauth2_redirect_url = root_path + oauth2_redirect_url
                return get_swagger_ui_html(
                    openapi_url=openapi_url,
                    title=f"{self.title} - Swagger UI",
                    oauth2_redirect_url=oauth2_redirect_url,
                    init_oauth=self.swagger_ui_init_oauth,
                    swagger_ui_parameters=self.swagger_ui_parameters,
                )

            self.add_route(self.docs_url, swagger_ui_html, include_in_schema=False)

            if self.swagger_ui_oauth2_redirect_url:

                async def swagger_ui_redirect(req: Request) -> HTMLResponse:
                    return get_swagger_ui_oauth2_redirect_html()

                self.add_route(
                    self.swagger_ui_oauth2_redirect_url,
                    swagger_ui_redirect,
                    include_in_schema=False,
                )
        if self.openapi_url and self.redoc_url:

            async def redoc_html(req: Request) -> HTMLResponse:
                root_path = req.scope.get("root_path", "").rstrip("/")
                openapi_url = root_path + self.openapi_url
                return get_redoc_html(
                    openapi_url=openapi_url, title=f"{self.title} - ReDoc"
                )

            self.add_route(self.redoc_url, redoc_html, include_in_schema=False)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self.root_path:
            scope["root_path"] = self.root_path
        await super().__call__(scope, receive, send)

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
    dependencies: Sequence[Depends] | None = None,
    summary: str | None = None,
    description: str | None = None,
    response_description: str = "Successful Response",
    responses: dict[int | str, dict[str, Any]] | None = None,
    deprecated: bool | None = None,
    methods: list[str] | None = None,
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
    openapi_extra: dict[str, Any] | None = None,
    generate_unique_id_function: Callable[[routing.APIRoute], str] = Default(
        generate_unique_id
    ),
) -> None:
    """
    Add a new API route to the router.

    Args:
        path (str): The path of the API route.
        endpoint (Callable[..., Any]): The endpoint function for the API route.
        response_model (Any, optional): The response model for the API route. Defaults to None.
        status_code (int | None, optional): The status code for the API route. Defaults to None.
        tags (list[str | Enum] | None, optional): The tags for the API route. Defaults to None.
        dependencies (Sequence[Depends] | None, optional): The dependencies for the API route. Defaults to None.
        summary (str | None, optional): The summary for the API route. Defaults to None.
        description (str | None, optional): The description for the API route. Defaults to None.
        response_description (str, optional): The response description for the API route. Defaults to "Successful Response".
        responses (dict[int | str, dict[str, Any]] | None, optional): The responses for the API route. Defaults to None.
        deprecated (bool | None, optional): Whether the API route is deprecated. Defaults to None.
        methods (list[str] | None, optional): The methods for the API route. Defaults to None.
        operation_id (str | None, optional): The operation ID for the API route. Defaults to None.
        response_model_include (IncEx | None, optional): The response model include for the API route. Defaults to None.
        response_model_exclude (IncEx | None, optional): The response model exclude for the API route. Defaults to None.
        response_model_by_alias (bool, optional): Whether to use aliases for the response model. Defaults to True.
        response_model_exclude_unset (bool, optional): Whether to exclude unset values from the response model. Defaults to False.
        response_model_exclude_defaults (bool, optional): Whether to exclude default values from the response model. Defaults to False.
        response_model_exclude_none (bool, optional): Whether to exclude None values from the response model. Defaults to False.
        include_in_schema (bool, optional): Whether to include the API route in the schema. Defaults to True.
        response_class (type[Response] | DefaultPlaceholder, optional): The response class for the API route. Defaults to JSONResponse.
        name (str | None, optional): The name of the API route. Defaults to None.
        openapi_extra (dict[str, Any] | None, optional): Extra OpenAPI information for the API route. Defaults to None.
        generate_unique_id_function (Callable[[routing.APIRoute], str], optional): A function to generate a unique ID for the API route. Defaults to generate_unique_id.
    """
    try:
        self.router.add_api_route(
            path,
            endpoint=endpoint,
            response_model=response_model,
            status_code=status_code,
            tags=tags,
            dependencies=dependencies,
            summary=summary,
            description=description,
            response_description=response_description,
            responses=responses,
            deprecated=deprecated,
            methods=methods,
            operation_id=operation_id,
            response_model_include=response_model_include,
            response_model_exclude=response_model_exclude,
            response_model_by_alias=response_model_by_alias,
            response_model_exclude_unset=response_model_exclude_unset,
            response_model_exclude_defaults=response_model_exclude_defaults,
            response_model_exclude_none=response_model_exclude_none,
            include_in_schema=include_in_schema,
            response_class=response_class,
            name=name,
            openapi_extra=openapi_extra,
            generate_unique_id_function=generate_unique_id_function,
        )
        logging.info(f"API route added: {path}")
    except Exception as e:
        logging.error(f"Failed to add API route: {path}. Error: {str(e)}")

    def api_route(
        self,
        path: str,
        *,
        response_model: Any = Default(None),
        status_code: int | None = None,
        tags: list[str | Enum] | None = None,
        dependencies: Sequence[Depends] | None = None,
        summary: str | None = None,
        description: str | None = None,
        response_description: str = "Successful Response",
        responses: dict[int | str, dict[str, Any]] | None = None,
        deprecated: bool | None = None,
        methods: list[str] | None = None,
        operation_id: str | None = None,
        response_model_include: IncEx | None = None,
        response_model_exclude: IncEx | None = None,
        response_model_by_alias: bool = True,
        response_model_exclude_unset: bool = False,
        response_model_exclude_defaults: bool = False,
        response_model_exclude_none: bool = False,
        include_in_schema: bool = True,
        response_class: type[Response] = Default(JSONResponse),
        name: str | None = None,
        openapi_extra: dict[str, Any] | None = None,
        generate_unique_id_function: Callable[[routing.APIRoute], str] = Default(
            generate_unique_id
        ),
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        def decorator(func: DecoratedCallable) -> DecoratedCallable:
            self.router.add_api_route(
                path,
                func,
                response_model=response_model,
                status_code=status_code,
                tags=tags,
                dependencies=dependencies,
                summary=summary,
                description=description,
                response_description=response_description,
                responses=responses,
                deprecated=deprecated,
                methods=methods,
                operation_id=operation_id,
                response_model_include=response_model_include,
                response_model_exclude=response_model_exclude,
                response_model_by_alias=response_model_by_alias,
                response_model_exclude_unset=response_model_exclude_unset,
                response_model_exclude_defaults=response_model_exclude_defaults,
                response_model_exclude_none=response_model_exclude_none,
                include_in_schema=include_in_schema,
                response_class=response_class,
                name=name,
                openapi_extra=openapi_extra,
                generate_unique_id_function=generate_unique_id_function,
            )
            return func

        return decorator

    def add_api_websocket_route(
        self,
        path: str,
        endpoint: Callable[..., Any],
        name: str | None = None,
        *,
        dependencies: Sequence[Depends] | None = None,
    ) -> None:
        self.router.add_api_websocket_route(
            path,
            endpoint,
            name=name,
            dependencies=dependencies,
        )

    def websocket(
        self,
        path: Annotated[
            str,
            Doc(
                """
                WebSocket path.
                """
            ),
        ],
        name: Annotated[
            str | None,
            Doc(
                """
                A name for the WebSocket. Only used internally.
                """
            ),
        ] = None,
        *,
        dependencies: Annotated[
            Sequence[Depends] | None,
            Doc(
                """
                A list of dependencies (using `Depends()`) to be used for this
                WebSocket.

                Read more about it in the
                [FastAPI docs for WebSockets](https://fastapi.tiangolo.com/advanced/websockets/).
                """
            ),
        ] = None,
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        """
        Decorate a WebSocket function.

        Read more about it in the
        [FastAPI docs for WebSockets](https://fastapi.tiangolo.com/advanced/websockets/).

        **Example**

        ```python
        from fastapi import FastAPI, WebSocket

        app = FastAPI()

        @app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await websocket.accept()
            while True:
                data = await websocket.receive_text()
                await websocket.send_text(f"Message text was: {data}")
        ```
        """

        def decorator(func: DecoratedCallable) -> DecoratedCallable:
            self.add_api_websocket_route(
                path,
                func,
                name=name,
                dependencies=dependencies,
            )
            return func

        return decorator

    def include_router(
        self,
        router: Annotated[routing.APIRouter, Doc("The `APIRouter` to include.")],
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
            Sequence[Depends] | None,
            Doc(
                """
                A list of dependencies (using `Depends()`) to be applied to all the
                *path operations* in this router.

                Read more about it in the
                [FastAPI docs for Bigger Applications - Multiple Files](https://fastapi.tiangolo.com/tutorial/bigger-applications/#include-an-apirouter-with-a-custom-prefix-tags-responses-and-dependencies).

                **Example**

                ```python
                from fastapi import Depends, FastAPI

                from .dependencies import get_token_header
                from .internal import admin

                app = FastAPI()

                app.include_router(
                    admin.router,
                    dependencies=[Depends(get_token_header)],
                )
                ```
                """
            ),
        ] = None,
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
        deprecated: Annotated[
            bool | None,
            Doc(
                """
                Mark all the *path operations* in this router as deprecated.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                **Example**

                ```python
                from fastapi import FastAPI

                from .internal import old_api

                app = FastAPI()

                app.include_router(
                    old_api.router,
                    deprecated=True,
                )
                ```
                """
            ),
        ] = None,
        include_in_schema: Annotated[
            bool,
            Doc(
                """
                Include (or not) all the *path operations* in this router in the
                generated OpenAPI schema.

                This affects the generated OpenAPI (e.g. visible at `/docs`).

                **Example**

                ```python
                from fastapi import FastAPI

                from .internal import old_api

                app = FastAPI()

                app.include_router(
                    old_api.router,
                    include_in_schema=False,
                )
                ```
                """
            ),
        ] = True,
        default_response_class: Annotated[
            type[Response],
            Doc(
                """
                Default response class to be used for the *path operations* in this
                router.

                Read more in the
                [FastAPI docs for Custom Response - HTML, Stream, File, others](https://fastapi.tiangolo.com/advanced/custom-response/#default-response-class).

                **Example**

                ```python
                from fastapi import FastAPI
                from fastapi.responses import ORJSONResponse

                from .internal import old_api

                app = FastAPI()

                app.include_router(
                    old_api.router,
                    default_response_class=ORJSONResponse,
                )
                ```
                """
            ),
        ] = Default(JSONResponse),
        callbacks: Annotated[
            list[BaseRoute] | None,
            Doc(
                """
                List of *path operations* that will be used as OpenAPI callbacks.

                This is only for OpenAPI documentation, the callbacks won't be used
                directly.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for OpenAPI Callbacks](https://fastapi.tiangolo.com/advanced/openapi-callbacks/).
                """
            ),
        ] = None,
        generate_unique_id_function: Annotated[
            Callable[[routing.APIRoute], str],
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
    ) -> None:
        """
        Include an `APIRouter` in the same app.

        Read more about it in the
        [FastAPI docs for Bigger Applications](https://fastapi.tiangolo.com/tutorial/bigger-applications/).

        ## Example

        ```python
        from fastapi import FastAPI

        from .users import users_router

        app = FastAPI()

        app.include_router(users_router)
        ```
        """
        self.router.include_router(
            router,
            prefix=prefix,
            tags=tags,
            dependencies=dependencies,
            responses=responses,
            deprecated=deprecated,
            include_in_schema=include_in_schema,
            default_response_class=default_response_class,
            callbacks=callbacks,
            generate_unique_id_function=generate_unique_id_function,
        )

    def get(
        self,
        path: Annotated[
            str,
            Doc(
                """
                The URL path to be used for this *path operation*.

                For example, in `http://example.com/items`, the path is `/items`.
                """
            ),
        ],
        *,
        response_model: Annotated[
            Any,
            Doc(
                """
                The type to use for the response.

                It could be any valid Pydantic *field* type. So, it doesn't have to
                be a Pydantic model, it could be other things, like a `list`, `dict`,
                etc.

                It will be used for:

                * Documentation: the generated OpenAPI (and the UI at `/docs`) will
                    show it as the response (JSON Schema).
                * Serialization: you could return an arbitrary object and the
                    `response_model` would be used to serialize that object into the
                    corresponding JSON.
                * Filtering: the JSON sent to the client will only contain the data
                    (fields) defined in the `response_model`. If you returned an object
                    that contains an attribute `password` but the `response_model` does
                    not include that field, the JSON sent to the client would not have
                    that `password`.
                * Validation: whatever you return will be serialized with the
                    `response_model`, converting any data as necessary to generate the
                    corresponding JSON. But if the data in the object returned is not
                    valid, that would mean a violation of the contract with the client,
                    so it's an error from the API developer. So, FastAPI will raise an
                    error and return a 500 error code (Internal Server Error).

                Read more about it in the
                [FastAPI docs for Response Model](https://fastapi.tiangolo.com/tutorial/response-model/).
                """
            ),
        ] = Default(None),
        status_code: Annotated[
            int | None,
            Doc(
                """
                The default status code to be used for the response.

                You could override the status code by returning a response directly.

                Read more about it in the
                [FastAPI docs for Response Status Code](https://fastapi.tiangolo.com/tutorial/response-status-code/).
                """
            ),
        ] = None,
        tags: Annotated[
            list[str | Enum] | None,
            Doc(
                """
                A list of tags to be applied to the *path operation*.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Path Operation Configuration](https://fastapi.tiangolo.com/tutorial/path-operation-configuration/#tags).
                """
            ),
        ] = None,
        dependencies: Annotated[
            Sequence[Depends] | None,
            Doc(
                """
                A list of dependencies (using `Depends()`) to be applied to the
                *path operation*.

                Read more about it in the
                [FastAPI docs for Dependencies in path operation decorators](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-in-path-operation-decorators/).
                """
            ),
        ] = None,
        summary: Annotated[
            str | None,
            Doc(
                """
                A summary for the *path operation*.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Path Operation Configuration](https://fastapi.tiangolo.com/tutorial/path-operation-configuration/).
                """
            ),
        ] = None,
        description: Annotated[
            str | None,
            Doc(
                """
                A description for the *path operation*.

                If not provided, it will be extracted automatically from the docstring
                of the *path operation function*.

                It can contain Markdown.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Path Operation Configuration](https://fastapi.tiangolo.com/tutorial/path-operation-configuration/).
                """
            ),
        ] = None,
        response_description: Annotated[
            str,
            Doc(
                """
                The description for the default response.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).
                """
            ),
        ] = "Successful Response",
        responses: Annotated[
            dict[int | str, dict[str, Any]] | None,
            Doc(
                """
                Additional responses that could be returned by this *path operation*.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).
                """
            ),
        ] = None,
        deprecated: Annotated[
            bool | None,
            Doc(
                """
                Mark this *path operation* as deprecated.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).
                """
            ),
        ] = None,
        operation_id: Annotated[
            str | None,
            Doc(
                """
                Custom operation ID to be used by this *path operation*.

                By default, it is generated automatically.

                If you provide a custom operation ID, you need to make sure it is
                unique for the whole API.

                You can customize the
                operation ID generation with the parameter
                `generate_unique_id_function` in the `FastAPI` class.

                Read more about it in the
                [FastAPI docs about how to Generate Clients](https://fastapi.tiangolo.com/advanced/generate-clients/#custom-generate-unique-id-function).
                """
            ),
        ] = None,
        response_model_include: Annotated[
            IncEx | None,
            Doc(
                """
                Configuration passed to Pydantic to include only certain fields in the
                response data.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_include-and-response_model_exclude).
                """
            ),
        ] = None,
        response_model_exclude: Annotated[
            IncEx | None,
            Doc(
                """
                Configuration passed to Pydantic to exclude certain fields in the
                response data.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_include-and-response_model_exclude).
                """
            ),
        ] = None,
        response_model_by_alias: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response model
                should be serialized by alias when an alias is used.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_include-and-response_model_exclude).
                """
            ),
        ] = True,
        response_model_exclude_unset: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response data
                should have all the fields, including the ones that were not set and
                have their default values. This is different from
                `response_model_exclude_defaults` in that if the fields are set,
                they will be included in the response, even if the value is the same
                as the default.

                When `True`, default values are omitted from the response.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#use-the-response_model_exclude_unset-parameter).
                """
            ),
        ] = False,
        response_model_exclude_defaults: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response data
                should have all the fields, including the ones that have the same value
                as the default. This is different from `response_model_exclude_unset`
                in that if the fields are set but contain the same default values,
                they will be excluded from the response.

                When `True`, default values are omitted from the response.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#use-the-response_model_exclude_unset-parameter).
                """
            ),
        ] = False,
        response_model_exclude_none: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response data should
                exclude fields set to `None`.

                This is much simpler (less smart) than `response_model_exclude_unset`
                and `response_model_exclude_defaults`. You probably want to use one of
                those two instead of this one, as those allow returning `None` values
                when it makes sense.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_exclude_none).
                """
            ),
        ] = False,
        include_in_schema: Annotated[
            bool,
            Doc(
                """
                Include this *path operation* in the generated OpenAPI schema.

                This affects the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Query Parameters and String Validations](https://fastapi.tiangolo.com/tutorial/query-params-str-validations/#exclude-parameters-from-openapi).
                """
            ),
        ] = True,
        response_class: Annotated[
            type[Response],
            Doc(
                """
                Response class to be used for this *path operation*.

                This will not be used if you return a response directly.

                Read more about it in the
                [FastAPI docs for Custom Response - HTML, Stream, File, others](https://fastapi.tiangolo.com/advanced/custom-response/#redirectresponse).
                """
            ),
        ] = Default(JSONResponse),
        name: Annotated[
            str | None,
            Doc(
                """
                Name for this *path operation*. Only used internally.
                """
            ),
        ] = None,
        callbacks: Annotated[
            list[BaseRoute] | None,
            Doc(
                """
                List of *path operations* that will be used as OpenAPI callbacks.

                This is only for OpenAPI documentation, the callbacks won't be used
                directly.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for OpenAPI Callbacks](https://fastapi.tiangolo.com/advanced/openapi-callbacks/).
                """
            ),
        ] = None,
        openapi_extra: Annotated[
            dict[str, Any] | None,
            Doc(
                """
                Extra metadata to be included in the OpenAPI schema for this *path
                operation*.

                Read more about it in the
                [FastAPI docs for Path Operation Advanced Configuration](https://fastapi.tiangolo.com/advanced/path-operation-advanced-configuration/#custom-openapi-path-operation-schema).
                """
            ),
        ] = None,
        generate_unique_id_function: Annotated[
            Callable[[routing.APIRoute], str],
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
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        """
        Add a *path operation* using an HTTP GET operation.

        ## Example

        ```python
        from fastapi import FastAPI

        app = FastAPI()

        @app.get("/items/")
        def read_items():
            return [{"name": "Empanada"}, {"name": "Arepa"}]
        ```
        """
        return self.router.get(
            path,
            response_model=response_model,
            status_code=status_code,
            tags=tags,
            dependencies=dependencies,
            summary=summary,
            description=description,
            response_description=response_description,
            responses=responses,
            deprecated=deprecated,
            operation_id=operation_id,
            response_model_include=response_model_include,
            response_model_exclude=response_model_exclude,
            response_model_by_alias=response_model_by_alias,
            response_model_exclude_unset=response_model_exclude_unset,
            response_model_exclude_defaults=response_model_exclude_defaults,
            response_model_exclude_none=response_model_exclude_none,
            include_in_schema=include_in_schema,
            response_class=response_class,
            name=name,
            callbacks=callbacks,
            openapi_extra=openapi_extra,
            generate_unique_id_function=generate_unique_id_function,
        )

    def put(
        self,
        path: Annotated[
            str,
            Doc(
                """
                The URL path to be used for this *path operation*.

                For example, in `http://example.com/items`, the path is `/items`.
                """
            ),
        ],
        *,
        response_model: Annotated[
            Any,
            Doc(
                """
                The type to use for the response.

                It could be any valid Pydantic *field* type. So, it doesn't have to
                be a Pydantic model, it could be other things, like a `list`, `dict`,
                etc.

                It will be used for:

                * Documentation: the generated OpenAPI (and the UI at `/docs`) will
                    show it as the response (JSON Schema).
                * Serialization: you could return an arbitrary object and the
                    `response_model` would be used to serialize that object into the
                    corresponding JSON.
                * Filtering: the JSON sent to the client will only contain the data
                    (fields) defined in the `response_model`. If you returned an object
                    that contains an attribute `password` but the `response_model` does
                    not include that field, the JSON sent to the client would not have
                    that `password`.
                * Validation: whatever you return will be serialized with the
                    `response_model`, converting any data as necessary to generate the
                    corresponding JSON. But if the data in the object returned is not
                    valid, that would mean a violation of the contract with the client,
                    so it's an error from the API developer. So, FastAPI will raise an
                    error and return a 500 error code (Internal Server Error).

                Read more about it in the
                [FastAPI docs for Response Model](https://fastapi.tiangolo.com/tutorial/response-model/).
                """
            ),
        ] = Default(None),
        status_code: Annotated[
            int | None,
            Doc(
                """
                The default status code to be used for the response.

                You could override the status code by returning a response directly.

                Read more about it in the
                [FastAPI docs for Response Status Code](https://fastapi.tiangolo.com/tutorial/response-status-code/).
                """
            ),
        ] = None,
        tags: Annotated[
            list[str | Enum] | None,
            Doc(
                """
                A list of tags to be applied to the *path operation*.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Path Operation Configuration](https://fastapi.tiangolo.com/tutorial/path-operation-configuration/#tags).
                """
            ),
        ] = None,
        dependencies: Annotated[
            Sequence[Depends] | None,
            Doc(
                """
                A list of dependencies (using `Depends()`) to be applied to the
                *path operation*.

                Read more about it in the
                [FastAPI docs for Dependencies in path operation decorators](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-in-path-operation-decorators/).
                """
            ),
        ] = None,
        summary: Annotated[
            str | None,
            Doc(
                """
                A summary for the *path operation*.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Path Operation Configuration](https://fastapi.tiangolo.com/tutorial/path-operation-configuration/).
                """
            ),
        ] = None,
        description: Annotated[
            str | None,
            Doc(
                """
                A description for the *path operation*.

                If not provided, it will be extracted automatically from the docstring
                of the *path operation function*.

                It can contain Markdown.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Path Operation Configuration](https://fastapi.tiangolo.com/tutorial/path-operation-configuration/).
                """
            ),
        ] = None,
        response_description: Annotated[
            str,
            Doc(
                """
                The description for the default response.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).
                """
            ),
        ] = "Successful Response",
        responses: Annotated[
            dict[int | str, dict[str, Any]] | None,
            Doc(
                """
                Additional responses that could be returned by this *path operation*.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).
                """
            ),
        ] = None,
        deprecated: Annotated[
            bool | None,
            Doc(
                """
                Mark this *path operation* as deprecated.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).
                """
            ),
        ] = None,
        operation_id: Annotated[
            str | None,
            Doc(
                """
                Custom operation ID to be used by this *path operation*.

                By default, it is generated automatically.

                If you provide a custom operation ID, you need to make sure it is
                unique for the whole API.

                You can customize the
                operation ID generation with the parameter
                `generate_unique_id_function` in the `FastAPI` class.

                Read more about it in the
                [FastAPI docs about how to Generate Clients](https://fastapi.tiangolo.com/advanced/generate-clients/#custom-generate-unique-id-function).
                """
            ),
        ] = None,
        response_model_include: Annotated[
            IncEx | None,
            Doc(
                """
                Configuration passed to Pydantic to include only certain fields in the
                response data.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_include-and-response_model_exclude).
                """
            ),
        ] = None,
        response_model_exclude: Annotated[
            IncEx | None,
            Doc(
                """
                Configuration passed to Pydantic to exclude certain fields in the
                response data.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_include-and-response_model_exclude).
                """
            ),
        ] = None,
        response_model_by_alias: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response model
                should be serialized by alias when an alias is used.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_include-and-response_model_exclude).
                """
            ),
        ] = True,
        response_model_exclude_unset: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response data
                should have all the fields, including the ones that were not set and
                have their default values. This is different from
                `response_model_exclude_defaults` in that if the fields are set,
                they will be included in the response, even if the value is the same
                as the default.

                When `True`, default values are omitted from the response.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#use-the-response_model_exclude_unset-parameter).
                """
            ),
        ] = False,
        response_model_exclude_defaults: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response data
                should have all the fields, including the ones that have the same value
                as the default. This is different from `response_model_exclude_unset`
                in that if the fields are set but contain the same default values,
                they will be excluded from the response.

                When `True`, default values are omitted from the response.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#use-the-response_model_exclude_unset-parameter).
                """
            ),
        ] = False,
        response_model_exclude_none: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response data should
                exclude fields set to `None`.

                This is much simpler (less smart) than `response_model_exclude_unset`
                and `response_model_exclude_defaults`. You probably want to use one of
                those two instead of this one, as those allow returning `None` values
                when it makes sense.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_exclude_none).
                """
            ),
        ] = False,
        include_in_schema: Annotated[
            bool,
            Doc(
                """
                Include this *path operation* in the generated OpenAPI schema.

                This affects the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Query Parameters and String Validations](https://fastapi.tiangolo.com/tutorial/query-params-str-validations/#exclude-parameters-from-openapi).
                """
            ),
        ] = True,
        response_class: Annotated[
            type[Response],
            Doc(
                """
                Response class to be used for this *path operation*.

                This will not be used if you return a response directly.

                Read more about it in the
                [FastAPI docs for Custom Response - HTML, Stream, File, others](https://fastapi.tiangolo.com/advanced/custom-response/#redirectresponse).
                """
            ),
        ] = Default(JSONResponse),
        name: Annotated[
            str | None,
            Doc(
                """
                Name for this *path operation*. Only used internally.
                """
            ),
        ] = None,
        callbacks: Annotated[
            list[BaseRoute] | None,
            Doc(
                """
                List of *path operations* that will be used as OpenAPI callbacks.

                This is only for OpenAPI documentation, the callbacks won't be used
                directly.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for OpenAPI Callbacks](https://fastapi.tiangolo.com/advanced/openapi-callbacks/).
                """
            ),
        ] = None,
        openapi_extra: Annotated[
            dict[str, Any] | None,
            Doc(
                """
                Extra metadata to be included in the OpenAPI schema for this *path
                operation*.

                Read more about it in the
                [FastAPI docs for Path Operation Advanced Configuration](https://fastapi.tiangolo.com/advanced/path-operation-advanced-configuration/#custom-openapi-path-operation-schema).
                """
            ),
        ] = None,
        generate_unique_id_function: Annotated[
            Callable[[routing.APIRoute], str],
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
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        """
        Add a *path operation* using an HTTP PUT operation.

        ## Example

        ```python
        from fastapi import FastAPI
        from pydantic import BaseModel

        class Item(BaseModel):
            name: str
            description: str | None = None

        app = FastAPI()

        @app.put("/items/{item_id}")
        def replace_item(item_id: str, item: Item):
            return {"message": "Item replaced", "id": item_id}
        ```
        """
        return self.router.put(
            path,
            response_model=response_model,
            status_code=status_code,
            tags=tags,
            dependencies=dependencies,
            summary=summary,
            description=description,
            response_description=response_description,
            responses=responses,
            deprecated=deprecated,
            operation_id=operation_id,
            response_model_include=response_model_include,
            response_model_exclude=response_model_exclude,
            response_model_by_alias=response_model_by_alias,
            response_model_exclude_unset=response_model_exclude_unset,
            response_model_exclude_defaults=response_model_exclude_defaults,
            response_model_exclude_none=response_model_exclude_none,
            include_in_schema=include_in_schema,
            response_class=response_class,
            name=name,
            callbacks=callbacks,
            openapi_extra=openapi_extra,
            generate_unique_id_function=generate_unique_id_function,
        )

    def post(
        self,
        path: Annotated[
            str,
            Doc(
                """
                The URL path to be used for this *path operation*.

                For example, in `http://example.com/items`, the path is `/items`.
                """
            ),
        ],
        *,
        response_model: Annotated[
            Any,
            Doc(
                """
                The type to use for the response.

                It could be any valid Pydantic *field* type. So, it doesn't have to
                be a Pydantic model, it could be other things, like a `list`, `dict`,
                etc.

                It will be used for:

                * Documentation: the generated OpenAPI (and the UI at `/docs`) will
                    show it as the response (JSON Schema).
                * Serialization: you could return an arbitrary object and the
                    `response_model` would be used to serialize that object into the
                    corresponding JSON.
                * Filtering: the JSON sent to the client will only contain the data
                    (fields) defined in the `response_model`. If you returned an object
                    that contains an attribute `password` but the `response_model` does
                    not include that field, the JSON sent to the client would not have
                    that `password`.
                * Validation: whatever you return will be serialized with the
                    `response_model`, converting any data as necessary to generate the
                    corresponding JSON. But if the data in the object returned is not
                    valid, that would mean a violation of the contract with the client,
                    so it's an error from the API developer. So, FastAPI will raise an
                    error and return a 500 error code (Internal Server Error).

                Read more about it in the
                [FastAPI docs for Response Model](https://fastapi.tiangolo.com/tutorial/response-model/).
                """
            ),
        ] = Default(None),
        status_code: Annotated[
            int | None,
            Doc(
                """
                The default status code to be used for the response.

                You could override the status code by returning a response directly.

                Read more about it in the
                [FastAPI docs for Response Status Code](https://fastapi.tiangolo.com/tutorial/response-status-code/).
                """
            ),
        ] = None,
        tags: Annotated[
            list[str | Enum] | None,
            Doc(
                """
                A list of tags to be applied to the *path operation*.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Path Operation Configuration](https://fastapi.tiangolo.com/tutorial/path-operation-configuration/#tags).
                """
            ),
        ] = None,
        dependencies: Annotated[
            Sequence[Depends] | None,
            Doc(
                """
                A list of dependencies (using `Depends()`) to be applied to the
                *path operation*.

                Read more about it in the
                [FastAPI docs for Dependencies in path operation decorators](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-in-path-operation-decorators/).
                """
            ),
        ] = None,
        summary: Annotated[
            str | None,
            Doc(
                """
                A summary for the *path operation*.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Path Operation Configuration](https://fastapi.tiangolo.com/tutorial/path-operation-configuration/).
                """
            ),
        ] = None,
        description: Annotated[
            str | None,
            Doc(
                """
                A description for the *path operation*.

                If not provided, it will be extracted automatically from the docstring
                of the *path operation function*.

                It can contain Markdown.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Path Operation Configuration](https://fastapi.tiangolo.com/tutorial/path-operation-configuration/).
                """
            ),
        ] = None,
        response_description: Annotated[
            str,
            Doc(
                """
                The description for the default response.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).
                """
            ),
        ] = "Successful Response",
        responses: Annotated[
            dict[int | str, dict[str, Any]] | None,
            Doc(
                """
                Additional responses that could be returned by this *path operation*.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).
                """
            ),
        ] = None,
        deprecated: Annotated[
            bool | None,
            Doc(
                """
                Mark this *path operation* as deprecated.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).
                """
            ),
        ] = None,
        operation_id: Annotated[
            str | None,
            Doc(
                """
                Custom operation ID to be used by this *path operation*.

                By default, it is generated automatically.

                If you provide a custom operation ID, you need to make sure it is
                unique for the whole API.

                You can customize the
                operation ID generation with the parameter
                `generate_unique_id_function` in the `FastAPI` class.

                Read more about it in the
                [FastAPI docs about how to Generate Clients](https://fastapi.tiangolo.com/advanced/generate-clients/#custom-generate-unique-id-function).
                """
            ),
        ] = None,
        response_model_include: Annotated[
            IncEx | None,
            Doc(
                """
                Configuration passed to Pydantic to include only certain fields in the
                response data.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_include-and-response_model_exclude).
                """
            ),
        ] = None,
        response_model_exclude: Annotated[
            IncEx | None,
            Doc(
                """
                Configuration passed to Pydantic to exclude certain fields in the
                response data.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_include-and-response_model_exclude).
                """
            ),
        ] = None,
        response_model_by_alias: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response model
                should be serialized by alias when an alias is used.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_include-and-response_model_exclude).
                """
            ),
        ] = True,
        response_model_exclude_unset: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response data
                should have all the fields, including the ones that were not set and
                have their default values. This is different from
                `response_model_exclude_defaults` in that if the fields are set,
                they will be included in the response, even if the value is the same
                as the default.

                When `True`, default values are omitted from the response.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#use-the-response_model_exclude_unset-parameter).
                """
            ),
        ] = False,
        response_model_exclude_defaults: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response data
                should have all the fields, including the ones that have the same value
                as the default. This is different from `response_model_exclude_unset`
                in that if the fields are set but contain the same default values,
                they will be excluded from the response.

                When `True`, default values are omitted from the response.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#use-the-response_model_exclude_unset-parameter).
                """
            ),
        ] = False,
        response_model_exclude_none: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response data should
                exclude fields set to `None`.

                This is much simpler (less smart) than `response_model_exclude_unset`
                and `response_model_exclude_defaults`. You probably want to use one of
                those two instead of this one, as those allow returning `None` values
                when it makes sense.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_exclude_none).
                """
            ),
        ] = False,
        include_in_schema: Annotated[
            bool,
            Doc(
                """
                Include this *path operation* in the generated OpenAPI schema.

                This affects the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Query Parameters and String Validations](https://fastapi.tiangolo.com/tutorial/query-params-str-validations/#exclude-parameters-from-openapi).
                """
            ),
        ] = True,
        response_class: Annotated[
            type[Response],
            Doc(
                """
                Response class to be used for this *path operation*.

                This will not be used if you return a response directly.

                Read more about it in the
                [FastAPI docs for Custom Response - HTML, Stream, File, others](https://fastapi.tiangolo.com/advanced/custom-response/#redirectresponse).
                """
            ),
        ] = Default(JSONResponse),
        name: Annotated[
            str | None,
            Doc(
                """
                Name for this *path operation*. Only used internally.
                """
            ),
        ] = None,
        callbacks: Annotated[
            list[BaseRoute] | None,
            Doc(
                """
                List of *path operations* that will be used as OpenAPI callbacks.

                This is only for OpenAPI documentation, the callbacks won't be used
                directly.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for OpenAPI Callbacks](https://fastapi.tiangolo.com/advanced/openapi-callbacks/).
                """
            ),
        ] = None,
        openapi_extra: Annotated[
            dict[str, Any] | None,
            Doc(
                """
                Extra metadata to be included in the OpenAPI schema for this *path
                operation*.

                Read more about it in the
                [FastAPI docs for Path Operation Advanced Configuration](https://fastapi.tiangolo.com/advanced/path-operation-advanced-configuration/#custom-openapi-path-operation-schema).
                """
            ),
        ] = None,
        generate_unique_id_function: Annotated[
            Callable[[routing.APIRoute], str],
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
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        """
        Add a *path operation* using an HTTP POST operation.

        ## Example

        ```python
        from fastapi import FastAPI
        from pydantic import BaseModel

        class Item(BaseModel):
            name: str
            description: str | None = None

        app = FastAPI()

        @app.post("/items/")
        def create_item(item: Item):
            return {"message": "Item created"}
        ```
        """
        return self.router.post(
            path,
            response_model=response_model,
            status_code=status_code,
            tags=tags,
            dependencies=dependencies,
            summary=summary,
            description=description,
            response_description=response_description,
            responses=responses,
            deprecated=deprecated,
            operation_id=operation_id,
            response_model_include=response_model_include,
            response_model_exclude=response_model_exclude,
            response_model_by_alias=response_model_by_alias,
            response_model_exclude_unset=response_model_exclude_unset,
            response_model_exclude_defaults=response_model_exclude_defaults,
            response_model_exclude_none=response_model_exclude_none,
            include_in_schema=include_in_schema,
            response_class=response_class,
            name=name,
            callbacks=callbacks,
            openapi_extra=openapi_extra,
            generate_unique_id_function=generate_unique_id_function,
        )

    def delete(
        self,
        path: Annotated[
            str,
            Doc(
                """
                The URL path to be used for this *path operation*.

                For example, in `http://example.com/items`, the path is `/items`.
                """
            ),
        ],
        *,
        response_model: Annotated[
            Any,
            Doc(
                """
                The type to use for the response.

                It could be any valid Pydantic *field* type. So, it doesn't have to
                be a Pydantic model, it could be other things, like a `list`, `dict`,
                etc.

                It will be used for:

                * Documentation: the generated OpenAPI (and the UI at `/docs`) will
                    show it as the response (JSON Schema).
                * Serialization: you could return an arbitrary object and the
                    `response_model` would be used to serialize that object into the
                    corresponding JSON.
                * Filtering: the JSON sent to the client will only contain the data
                    (fields) defined in the `response_model`. If you returned an object
                    that contains an attribute `password` but the `response_model` does
                    not include that field, the JSON sent to the client would not have
                    that `password`.
                * Validation: whatever you return will be serialized with the
                    `response_model`, converting any data as necessary to generate the
                    corresponding JSON. But if the data in the object returned is not
                    valid, that would mean a violation of the contract with the client,
                    so it's an error from the API developer. So, FastAPI will raise an
                    error and return a 500 error code (Internal Server Error).

                Read more about it in the
                [FastAPI docs for Response Model](https://fastapi.tiangolo.com/tutorial/response-model/).
                """
            ),
        ] = Default(None),
        status_code: Annotated[
            int | None,
            Doc(
                """
                The default status code to be used for the response.

                You could override the status code by returning a response directly.

                Read more about it in the
                [FastAPI docs for Response Status Code](https://fastapi.tiangolo.com/tutorial/response-status-code/).
                """
            ),
        ] = None,
        tags: Annotated[
            list[str | Enum] | None,
            Doc(
                """
                A list of tags to be applied to the *path operation*.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Path Operation Configuration](https://fastapi.tiangolo.com/tutorial/path-operation-configuration/#tags).
                """
            ),
        ] = None,
        dependencies: Annotated[
            Sequence[Depends] | None,
            Doc(
                """
                A list of dependencies (using `Depends()`) to be applied to the
                *path operation*.

                Read more about it in the
                [FastAPI docs for Dependencies in path operation decorators](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-in-path-operation-decorators/).
                """
            ),
        ] = None,
        summary: Annotated[
            str | None,
            Doc(
                """
                A summary for the *path operation*.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Path Operation Configuration](https://fastapi.tiangolo.com/tutorial/path-operation-configuration/).
                """
            ),
        ] = None,
        description: Annotated[
            str | None,
            Doc(
                """
                A description for the *path operation*.

                If not provided, it will be extracted automatically from the docstring
                of the *path operation function*.

                It can contain Markdown.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Path Operation Configuration](https://fastapi.tiangolo.com/tutorial/path-operation-configuration/).
                """
            ),
        ] = None,
        response_description: Annotated[
            str,
            Doc(
                """
                The description for the default response.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).
                """
            ),
        ] = "Successful Response",
        responses: Annotated[
            dict[int | str, dict[str, Any]] | None,
            Doc(
                """
                Additional responses that could be returned by this *path operation*.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).
                """
            ),
        ] = None,
        deprecated: Annotated[
            bool | None,
            Doc(
                """
                Mark this *path operation* as deprecated.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).
                """
            ),
        ] = None,
        operation_id: Annotated[
            str | None,
            Doc(
                """
                Custom operation ID to be used by this *path operation*.

                By default, it is generated automatically.

                If you provide a custom operation ID, you need to make sure it is
                unique for the whole API.

                You can customize the
                operation ID generation with the parameter
                `generate_unique_id_function` in the `FastAPI` class.

                Read more about it in the
                [FastAPI docs about how to Generate Clients](https://fastapi.tiangolo.com/advanced/generate-clients/#custom-generate-unique-id-function).
                """
            ),
        ] = None,
        response_model_include: Annotated[
            IncEx | None,
            Doc(
                """
                Configuration passed to Pydantic to include only certain fields in the
                response data.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_include-and-response_model_exclude).
                """
            ),
        ] = None,
        response_model_exclude: Annotated[
            IncEx | None,
            Doc(
                """
                Configuration passed to Pydantic to exclude certain fields in the
                response data.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_include-and-response_model_exclude).
                """
            ),
        ] = None,
        response_model_by_alias: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response model
                should be serialized by alias when an alias is used.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_include-and-response_model_exclude).
                """
            ),
        ] = True,
        response_model_exclude_unset: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response data
                should have all the fields, including the ones that were not set and
                have their default values. This is different from
                `response_model_exclude_defaults` in that if the fields are set,
                they will be included in the response, even if the value is the same
                as the default.

                When `True`, default values are omitted from the response.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#use-the-response_model_exclude_unset-parameter).
                """
            ),
        ] = False,
        response_model_exclude_defaults: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response data
                should have all the fields, including the ones that have the same value
                as the default. This is different from `response_model_exclude_unset`
                in that if the fields are set but contain the same default values,
                they will be excluded from the response.

                When `True`, default values are omitted from the response.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#use-the-response_model_exclude_unset-parameter).
                """
            ),
        ] = False,
        response_model_exclude_none: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response data should
                exclude fields set to `None`.

                This is much simpler (less smart) than `response_model_exclude_unset`
                and `response_model_exclude_defaults`. You probably want to use one of
                those two instead of this one, as those allow returning `None` values
                when it makes sense.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_exclude_none).
                """
            ),
        ] = False,
        include_in_schema: Annotated[
            bool,
            Doc(
                """
                Include this *path operation* in the generated OpenAPI schema.

                This affects the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Query Parameters and String Validations](https://fastapi.tiangolo.com/tutorial/query-params-str-validations/#exclude-parameters-from-openapi).
                """
            ),
        ] = True,
        response_class: Annotated[
            type[Response],
            Doc(
                """
                Response class to be used for this *path operation*.

                This will not be used if you return a response directly.

                Read more about it in the
                [FastAPI docs for Custom Response - HTML, Stream, File, others](https://fastapi.tiangolo.com/advanced/custom-response/#redirectresponse).
                """
            ),
        ] = Default(JSONResponse),
        name: Annotated[
            str | None,
            Doc(
                """
                Name for this *path operation*. Only used internally.
                """
            ),
        ] = None,
        callbacks: Annotated[
            list[BaseRoute] | None,
            Doc(
                """
                List of *path operations* that will be used as OpenAPI callbacks.

                This is only for OpenAPI documentation, the callbacks won't be used
                directly.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for OpenAPI Callbacks](https://fastapi.tiangolo.com/advanced/openapi-callbacks/).
                """
            ),
        ] = None,
        openapi_extra: Annotated[
            dict[str, Any] | None,
            Doc(
                """
                Extra metadata to be included in the OpenAPI schema for this *path
                operation*.

                Read more about it in the
                [FastAPI docs for Path Operation Advanced Configuration](https://fastapi.tiangolo.com/advanced/path-operation-advanced-configuration/#custom-openapi-path-operation-schema).
                """
            ),
        ] = None,
        generate_unique_id_function: Annotated[
            Callable[[routing.APIRoute], str],
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
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        """
        Add a *path operation* using an HTTP DELETE operation.

        ## Example

        ```python
        from fastapi import FastAPI

        app = FastAPI()

        @app.delete("/items/{item_id}")
        def delete_item(item_id: str):
            return {"message": "Item deleted"}
        ```
        """
        return self.router.delete(
            path,
            response_model=response_model,
            status_code=status_code,
            tags=tags,
            dependencies=dependencies,
            summary=summary,
            description=description,
            response_description=response_description,
            responses=responses,
            deprecated=deprecated,
            operation_id=operation_id,
            response_model_include=response_model_include,
            response_model_exclude=response_model_exclude,
            response_model_by_alias=response_model_by_alias,
            response_model_exclude_unset=response_model_exclude_unset,
            response_model_exclude_defaults=response_model_exclude_defaults,
            response_model_exclude_none=response_model_exclude_none,
            include_in_schema=include_in_schema,
            response_class=response_class,
            name=name,
            callbacks=callbacks,
            openapi_extra=openapi_extra,
            generate_unique_id_function=generate_unique_id_function,
        )

    def options(
        self,
        path: Annotated[
            str,
            Doc(
                """
                The URL path to be used for this *path operation*.

                For example, in `http://example.com/items`, the path is `/items`.
                """
            ),
        ],
        *,
        response_model: Annotated[
            Any,
            Doc(
                """
                The type to use for the response.

                It could be any valid Pydantic *field* type. So, it doesn't have to
                be a Pydantic model, it could be other things, like a `list`, `dict`,
                etc.

                It will be used for:

                * Documentation: the generated OpenAPI (and the UI at `/docs`) will
                    show it as the response (JSON Schema).
                * Serialization: you could return an arbitrary object and the
                    `response_model` would be used to serialize that object into the
                    corresponding JSON.
                * Filtering: the JSON sent to the client will only contain the data
                    (fields) defined in the `response_model`. If you returned an object
                    that contains an attribute `password` but the `response_model` does
                    not include that field, the JSON sent to the client would not have
                    that `password`.
                * Validation: whatever you return will be serialized with the
                    `response_model`, converting any data as necessary to generate the
                    corresponding JSON. But if the data in the object returned is not
                    valid, that would mean a violation of the contract with the client,
                    so it's an error from the API developer. So, FastAPI will raise an
                    error and return a 500 error code (Internal Server Error).

                Read more about it in the
                [FastAPI docs for Response Model](https://fastapi.tiangolo.com/tutorial/response-model/).
                """
            ),
        ] = Default(None),
        status_code: Annotated[
            int | None,
            Doc(
                """
                The default status code to be used for the response.

                You could override the status code by returning a response directly.

                Read more about it in the
                [FastAPI docs for Response Status Code](https://fastapi.tiangolo.com/tutorial/response-status-code/).
                """
            ),
        ] = None,
        tags: Annotated[
            list[str | Enum] | None,
            Doc(
                """
                A list of tags to be applied to the *path operation*.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Path Operation Configuration](https://fastapi.tiangolo.com/tutorial/path-operation-configuration/#tags).
                """
            ),
        ] = None,
        dependencies: Annotated[
            Sequence[Depends] | None,
            Doc(
                """
                A list of dependencies (using `Depends()`) to be applied to the
                *path operation*.

                Read more about it in the
                [FastAPI docs for Dependencies in path operation decorators](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-in-path-operation-decorators/).
                """
            ),
        ] = None,
        summary: Annotated[
            str | None,
            Doc(
                """
                A summary for the *path operation*.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Path Operation Configuration](https://fastapi.tiangolo.com/tutorial/path-operation-configuration/).
                """
            ),
        ] = None,
        description: Annotated[
            str | None,
            Doc(
                """
                A description for the *path operation*.

                If not provided, it will be extracted automatically from the docstring
                of the *path operation function*.

                It can contain Markdown.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Path Operation Configuration](https://fastapi.tiangolo.com/tutorial/path-operation-configuration/).
                """
            ),
        ] = None,
        response_description: Annotated[
            str,
            Doc(
                """
                The description for the default response.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).
                """
            ),
        ] = "Successful Response",
        responses: Annotated[
            dict[int | str, dict[str, Any]] | None,
            Doc(
                """
                Additional responses that could be returned by this *path operation*.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).
                """
            ),
        ] = None,
        deprecated: Annotated[
            bool | None,
            Doc(
                """
                Mark this *path operation* as deprecated.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).
                """
            ),
        ] = None,
        operation_id: Annotated[
            str | None,
            Doc(
                """
                Custom operation ID to be used by this *path operation*.

                By default, it is generated automatically.

                If you provide a custom operation ID, you need to make sure it is
                unique for the whole API.

                You can customize the
                operation ID generation with the parameter
                `generate_unique_id_function` in the `FastAPI` class.

                Read more about it in the
                [FastAPI docs about how to Generate Clients](https://fastapi.tiangolo.com/advanced/generate-clients/#custom-generate-unique-id-function).
                """
            ),
        ] = None,
        response_model_include: Annotated[
            IncEx | None,
            Doc(
                """
                Configuration passed to Pydantic to include only certain fields in the
                response data.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_include-and-response_model_exclude).
                """
            ),
        ] = None,
        response_model_exclude: Annotated[
            IncEx | None,
            Doc(
                """
                Configuration passed to Pydantic to exclude certain fields in the
                response data.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_include-and-response_model_exclude).
                """
            ),
        ] = None,
        response_model_by_alias: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response model
                should be serialized by alias when an alias is used.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_include-and-response_model_exclude).
                """
            ),
        ] = True,
        response_model_exclude_unset: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response data
                should have all the fields, including the ones that were not set and
                have their default values. This is different from
                `response_model_exclude_defaults` in that if the fields are set,
                they will be included in the response, even if the value is the same
                as the default.

                When `True`, default values are omitted from the response.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#use-the-response_model_exclude_unset-parameter).
                """
            ),
        ] = False,
        response_model_exclude_defaults: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response data
                should have all the fields, including the ones that have the same value
                as the default. This is different from `response_model_exclude_unset`
                in that if the fields are set but contain the same default values,
                they will be excluded from the response.

                When `True`, default values are omitted from the response.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#use-the-response_model_exclude_unset-parameter).
                """
            ),
        ] = False,
        response_model_exclude_none: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response data should
                exclude fields set to `None`.

                This is much simpler (less smart) than `response_model_exclude_unset`
                and `response_model_exclude_defaults`. You probably want to use one of
                those two instead of this one, as those allow returning `None` values
                when it makes sense.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_exclude_none).
                """
            ),
        ] = False,
        include_in_schema: Annotated[
            bool,
            Doc(
                """
                Include this *path operation* in the generated OpenAPI schema.

                This affects the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Query Parameters and String Validations](https://fastapi.tiangolo.com/tutorial/query-params-str-validations/#exclude-parameters-from-openapi).
                """
            ),
        ] = True,
        response_class: Annotated[
            type[Response],
            Doc(
                """
                Response class to be used for this *path operation*.

                This will not be used if you return a response directly.

                Read more about it in the
                [FastAPI docs for Custom Response - HTML, Stream, File, others](https://fastapi.tiangolo.com/advanced/custom-response/#redirectresponse).
                """
            ),
        ] = Default(JSONResponse),
        name: Annotated[
            str | None,
            Doc(
                """
                Name for this *path operation*. Only used internally.
                """
            ),
        ] = None,
        callbacks: Annotated[
            list[BaseRoute] | None,
            Doc(
                """
                List of *path operations* that will be used as OpenAPI callbacks.

                This is only for OpenAPI documentation, the callbacks won't be used
                directly.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for OpenAPI Callbacks](https://fastapi.tiangolo.com/advanced/openapi-callbacks/).
                """
            ),
        ] = None,
        openapi_extra: Annotated[
            dict[str, Any] | None,
            Doc(
                """
                Extra metadata to be included in the OpenAPI schema for this *path
                operation*.

                Read more about it in the
                [FastAPI docs for Path Operation Advanced Configuration](https://fastapi.tiangolo.com/advanced/path-operation-advanced-configuration/#custom-openapi-path-operation-schema).
                """
            ),
        ] = None,
        generate_unique_id_function: Annotated[
            Callable[[routing.APIRoute], str],
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
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        """
        Add a *path operation* using an HTTP OPTIONS operation.

        ## Example

        ```python
        from fastapi import FastAPI

        app = FastAPI()

        @app.options("/items/")
        def get_item_options():
            return {"additions": ["Aji", "Guacamole"]}
        ```
        """
        return self.router.options(
            path,
            response_model=response_model,
            status_code=status_code,
            tags=tags,
            dependencies=dependencies,
            summary=summary,
            description=description,
            response_description=response_description,
            responses=responses,
            deprecated=deprecated,
            operation_id=operation_id,
            response_model_include=response_model_include,
            response_model_exclude=response_model_exclude,
            response_model_by_alias=response_model_by_alias,
            response_model_exclude_unset=response_model_exclude_unset,
            response_model_exclude_defaults=response_model_exclude_defaults,
            response_model_exclude_none=response_model_exclude_none,
            include_in_schema=include_in_schema,
            response_class=response_class,
            name=name,
            callbacks=callbacks,
            openapi_extra=openapi_extra,
            generate_unique_id_function=generate_unique_id_function,
        )

    def head(
        self,
        path: Annotated[
            str,
            Doc(
                """
                The URL path to be used for this *path operation*.

                For example, in `http://example.com/items`, the path is `/items`.
                """
            ),
        ],
        *,
        response_model: Annotated[
            Any,
            Doc(
                """
                The type to use for the response.

                It could be any valid Pydantic *field* type. So, it doesn't have to
                be a Pydantic model, it could be other things, like a `list`, `dict`,
                etc.

                It will be used for:

                * Documentation: the generated OpenAPI (and the UI at `/docs`) will
                    show it as the response (JSON Schema).
                * Serialization: you could return an arbitrary object and the
                    `response_model` would be used to serialize that object into the
                    corresponding JSON.
                * Filtering: the JSON sent to the client will only contain the data
                    (fields) defined in the `response_model`. If you returned an object
                    that contains an attribute `password` but the `response_model` does
                    not include that field, the JSON sent to the client would not have
                    that `password`.
                * Validation: whatever you return will be serialized with the
                    `response_model`, converting any data as necessary to generate the
                    corresponding JSON. But if the data in the object returned is not
                    valid, that would mean a violation of the contract with the client,
                    so it's an error from the API developer. So, FastAPI will raise an
                    error and return a 500 error code (Internal Server Error).

                Read more about it in the
                [FastAPI docs for Response Model](https://fastapi.tiangolo.com/tutorial/response-model/).
                """
            ),
        ] = Default(None),
        status_code: Annotated[
            int | None,
            Doc(
                """
                The default status code to be used for the response.

                You could override the status code by returning a response directly.

                Read more about it in the
                [FastAPI docs for Response Status Code](https://fastapi.tiangolo.com/tutorial/response-status-code/).
                """
            ),
        ] = None,
        tags: Annotated[
            list[str | Enum] | None,
            Doc(
                """
                A list of tags to be applied to the *path operation*.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Path Operation Configuration](https://fastapi.tiangolo.com/tutorial/path-operation-configuration/#tags).
                """
            ),
        ] = None,
        dependencies: Annotated[
            Sequence[Depends] | None,
            Doc(
                """
                A list of dependencies (using `Depends()`) to be applied to the
                *path operation*.

                Read more about it in the
                [FastAPI docs for Dependencies in path operation decorators](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-in-path-operation-decorators/).
                """
            ),
        ] = None,
        summary: Annotated[
            str | None,
            Doc(
                """
                A summary for the *path operation*.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Path Operation Configuration](https://fastapi.tiangolo.com/tutorial/path-operation-configuration/).
                """
            ),
        ] = None,
        description: Annotated[
            str | None,
            Doc(
                """
                A description for the *path operation*.

                If not provided, it will be extracted automatically from the docstring
                of the *path operation function*.

                It can contain Markdown.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Path Operation Configuration](https://fastapi.tiangolo.com/tutorial/path-operation-configuration/).
                """
            ),
        ] = None,
        response_description: Annotated[
            str,
            Doc(
                """
                The description for the default response.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).
                """
            ),
        ] = "Successful Response",
        responses: Annotated[
            dict[int | str, dict[str, Any]] | None,
            Doc(
                """
                Additional responses that could be returned by this *path operation*.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).
                """
            ),
        ] = None,
        deprecated: Annotated[
            bool | None,
            Doc(
                """
                Mark this *path operation* as deprecated.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).
                """
            ),
        ] = None,
        operation_id: Annotated[
            str | None,
            Doc(
                """
                Custom operation ID to be used by this *path operation*.

                By default, it is generated automatically.

                If you provide a custom operation ID, you need to make sure it is
                unique for the whole API.

                You can customize the
                operation ID generation with the parameter
                `generate_unique_id_function` in the `FastAPI` class.

                Read more about it in the
                [FastAPI docs about how to Generate Clients](https://fastapi.tiangolo.com/advanced/generate-clients/#custom-generate-unique-id-function).
                """
            ),
        ] = None,
        response_model_include: Annotated[
            IncEx | None,
            Doc(
                """
                Configuration passed to Pydantic to include only certain fields in the
                response data.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_include-and-response_model_exclude).
                """
            ),
        ] = None,
        response_model_exclude: Annotated[
            IncEx | None,
            Doc(
                """
                Configuration passed to Pydantic to exclude certain fields in the
                response data.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_include-and-response_model_exclude).
                """
            ),
        ] = None,
        response_model_by_alias: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response model
                should be serialized by alias when an alias is used.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_include-and-response_model_exclude).
                """
            ),
        ] = True,
        response_model_exclude_unset: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response data
                should have all the fields, including the ones that were not set and
                have their default values. This is different from
                `response_model_exclude_defaults` in that if the fields are set,
                they will be included in the response, even if the value is the same
                as the default.

                When `True`, default values are omitted from the response.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#use-the-response_model_exclude_unset-parameter).
                """
            ),
        ] = False,
        response_model_exclude_defaults: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response data
                should have all the fields, including the ones that have the same value
                as the default. This is different from `response_model_exclude_unset`
                in that if the fields are set but contain the same default values,
                they will be excluded from the response.

                When `True`, default values are omitted from the response.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#use-the-response_model_exclude_unset-parameter).
                """
            ),
        ] = False,
        response_model_exclude_none: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response data should
                exclude fields set to `None`.

                This is much simpler (less smart) than `response_model_exclude_unset`
                and `response_model_exclude_defaults`. You probably want to use one of
                those two instead of this one, as those allow returning `None` values
                when it makes sense.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_exclude_none).
                """
            ),
        ] = False,
        include_in_schema: Annotated[
            bool,
            Doc(
                """
                Include this *path operation* in the generated OpenAPI schema.

                This affects the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Query Parameters and String Validations](https://fastapi.tiangolo.com/tutorial/query-params-str-validations/#exclude-parameters-from-openapi).
                """
            ),
        ] = True,
        response_class: Annotated[
            type[Response],
            Doc(
                """
                Response class to be used for this *path operation*.

                This will not be used if you return a response directly.

                Read more about it in the
                [FastAPI docs for Custom Response - HTML, Stream, File, others](https://fastapi.tiangolo.com/advanced/custom-response/#redirectresponse).
                """
            ),
        ] = Default(JSONResponse),
        name: Annotated[
            str | None,
            Doc(
                """
                Name for this *path operation*. Only used internally.
                """
            ),
        ] = None,
        callbacks: Annotated[
            list[BaseRoute] | None,
            Doc(
                """
                List of *path operations* that will be used as OpenAPI callbacks.

                This is only for OpenAPI documentation, the callbacks won't be used
                directly.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for OpenAPI Callbacks](https://fastapi.tiangolo.com/advanced/openapi-callbacks/).
                """
            ),
        ] = None,
        openapi_extra: Annotated[
            dict[str, Any] | None,
            Doc(
                """
                Extra metadata to be included in the OpenAPI schema for this *path
                operation*.

                Read more about it in the
                [FastAPI docs for Path Operation Advanced Configuration](https://fastapi.tiangolo.com/advanced/path-operation-advanced-configuration/#custom-openapi-path-operation-schema).
                """
            ),
        ] = None,
        generate_unique_id_function: Annotated[
            Callable[[routing.APIRoute], str],
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
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        """
        Add a *path operation* using an HTTP HEAD operation.

        ## Example

        ```python
        from fastapi import FastAPI, Response

        app = FastAPI()

        @app.head("/items/", status_code=204)
        def get_items_headers(response: Response):
            response.headers["X-Cat-Dog"] = "Alone in the world"
        ```
        """
        return self.router.head(
            path,
            response_model=response_model,
            status_code=status_code,
            tags=tags,
            dependencies=dependencies,
            summary=summary,
            description=description,
            response_description=response_description,
            responses=responses,
            deprecated=deprecated,
            operation_id=operation_id,
            response_model_include=response_model_include,
            response_model_exclude=response_model_exclude,
            response_model_by_alias=response_model_by_alias,
            response_model_exclude_unset=response_model_exclude_unset,
            response_model_exclude_defaults=response_model_exclude_defaults,
            response_model_exclude_none=response_model_exclude_none,
            include_in_schema=include_in_schema,
            response_class=response_class,
            name=name,
            callbacks=callbacks,
            openapi_extra=openapi_extra,
            generate_unique_id_function=generate_unique_id_function,
        )

    def patch(
        self,
        path: Annotated[
            str,
            Doc(
                """
                The URL path to be used for this *path operation*.

                For example, in `http://example.com/items`, the path is `/items`.
                """
            ),
        ],
        *,
        response_model: Annotated[
            Any,
            Doc(
                """
                The type to use for the response.

                It could be any valid Pydantic *field* type. So, it doesn't have to
                be a Pydantic model, it could be other things, like a `list`, `dict`,
                etc.

                It will be used for:

                * Documentation: the generated OpenAPI (and the UI at `/docs`) will
                    show it as the response (JSON Schema).
                * Serialization: you could return an arbitrary object and the
                    `response_model` would be used to serialize that object into the
                    corresponding JSON.
                * Filtering: the JSON sent to the client will only contain the data
                    (fields) defined in the `response_model`. If you returned an object
                    that contains an attribute `password` but the `response_model` does
                    not include that field, the JSON sent to the client would not have
                    that `password`.
                * Validation: whatever you return will be serialized with the
                    `response_model`, converting any data as necessary to generate the
                    corresponding JSON. But if the data in the object returned is not
                    valid, that would mean a violation of the contract with the client,
                    so it's an error from the API developer. So, FastAPI will raise an
                    error and return a 500 error code (Internal Server Error).

                Read more about it in the
                [FastAPI docs for Response Model](https://fastapi.tiangolo.com/tutorial/response-model/).
                """
            ),
        ] = Default(None),
        status_code: Annotated[
            int | None,
            Doc(
                """
                The default status code to be used for the response.

                You could override the status code by returning a response directly.

                Read more about it in the
                [FastAPI docs for Response Status Code](https://fastapi.tiangolo.com/tutorial/response-status-code/).
                """
            ),
        ] = None,
        tags: Annotated[
            list[str | Enum] | None,
            Doc(
                """
                A list of tags to be applied to the *path operation*.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Path Operation Configuration](https://fastapi.tiangolo.com/tutorial/path-operation-configuration/#tags).
                """
            ),
        ] = None,
        dependencies: Annotated[
            Sequence[Depends] | None,
            Doc(
                """
                A list of dependencies (using `Depends()`) to be applied to the
                *path operation*.

                Read more about it in the
                [FastAPI docs for Dependencies in path operation decorators](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-in-path-operation-decorators/).
                """
            ),
        ] = None,
        summary: Annotated[
            str | None,
            Doc(
                """
                A summary for the *path operation*.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Path Operation Configuration](https://fastapi.tiangolo.com/tutorial/path-operation-configuration/).
                """
            ),
        ] = None,
        description: Annotated[
            str | None,
            Doc(
                """
                A description for the *path operation*.

                If not provided, it will be extracted automatically from the docstring
                of the *path operation function*.

                It can contain Markdown.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Path Operation Configuration](https://fastapi.tiangolo.com/tutorial/path-operation-configuration/).
                """
            ),
        ] = None,
        response_description: Annotated[
            str,
            Doc(
                """
                The description for the default response.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).
                """
            ),
        ] = "Successful Response",
        responses: Annotated[
            dict[int | str, dict[str, Any]] | None,
            Doc(
                """
                Additional responses that could be returned by this *path operation*.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).
                """
            ),
        ] = None,
        deprecated: Annotated[
            bool | None,
            Doc(
                """
                Mark this *path operation* as deprecated.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).
                """
            ),
        ] = None,
        operation_id: Annotated[
            str | None,
            Doc(
                """
                Custom operation ID to be used by this *path operation*.

                By default, it is generated automatically.

                If you provide a custom operation ID, you need to make sure it is
                unique for the whole API.

                You can customize the
                operation ID generation with the parameter
                `generate_unique_id_function` in the `FastAPI` class.

                Read more about it in the
                [FastAPI docs about how to Generate Clients](https://fastapi.tiangolo.com/advanced/generate-clients/#custom-generate-unique-id-function).
                """
            ),
        ] = None,
        response_model_include: Annotated[
            IncEx | None,
            Doc(
                """
                Configuration passed to Pydantic to include only certain fields in the
                response data.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_include-and-response_model_exclude).
                """
            ),
        ] = None,
        response_model_exclude: Annotated[
            IncEx | None,
            Doc(
                """
                Configuration passed to Pydantic to exclude certain fields in the
                response data.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_include-and-response_model_exclude).
                """
            ),
        ] = None,
        response_model_by_alias: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response model
                should be serialized by alias when an alias is used.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_include-and-response_model_exclude).
                """
            ),
        ] = True,
        response_model_exclude_unset: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response data
                should have all the fields, including the ones that were not set and
                have their default values. This is different from
                `response_model_exclude_defaults` in that if the fields are set,
                they will be included in the response, even if the value is the same
                as the default.

                When `True`, default values are omitted from the response.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#use-the-response_model_exclude_unset-parameter).
                """
            ),
        ] = False,
        response_model_exclude_defaults: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response data
                should have all the fields, including the ones that have the same value
                as the default. This is different from `response_model_exclude_unset`
                in that if the fields are set but contain the same default values,
                they will be excluded from the response.

                When `True`, default values are omitted from the response.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#use-the-response_model_exclude_unset-parameter).
                """
            ),
        ] = False,
        response_model_exclude_none: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response data should
                exclude fields set to `None`.

                This is much simpler (less smart) than `response_model_exclude_unset`
                and `response_model_exclude_defaults`. You probably want to use one of
                those two instead of this one, as those allow returning `None` values
                when it makes sense.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_exclude_none).
                """
            ),
        ] = False,
        include_in_schema: Annotated[
            bool,
            Doc(
                """
                Include this *path operation* in the generated OpenAPI schema.

                This affects the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Query Parameters and String Validations](https://fastapi.tiangolo.com/tutorial/query-params-str-validations/#exclude-parameters-from-openapi).
                """
            ),
        ] = True,
        response_class: Annotated[
            type[Response],
            Doc(
                """
                Response class to be used for this *path operation*.

                This will not be used if you return a response directly.

                Read more about it in the
                [FastAPI docs for Custom Response - HTML, Stream, File, others](https://fastapi.tiangolo.com/advanced/custom-response/#redirectresponse).
                """
            ),
        ] = Default(JSONResponse),
        name: Annotated[
            str | None,
            Doc(
                """
                Name for this *path operation*. Only used internally.
                """
            ),
        ] = None,
        callbacks: Annotated[
            list[BaseRoute] | None,
            Doc(
                """
                List of *path operations* that will be used as OpenAPI callbacks.

                This is only for OpenAPI documentation, the callbacks won't be used
                directly.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for OpenAPI Callbacks](https://fastapi.tiangolo.com/advanced/openapi-callbacks/).
                """
            ),
        ] = None,
        openapi_extra: Annotated[
            dict[str, Any] | None,
            Doc(
                """
                Extra metadata to be included in the OpenAPI schema for this *path
                operation*.

                Read more about it in the
                [FastAPI docs for Path Operation Advanced Configuration](https://fastapi.tiangolo.com/advanced/path-operation-advanced-configuration/#custom-openapi-path-operation-schema).
                """
            ),
        ] = None,
        generate_unique_id_function: Annotated[
            Callable[[routing.APIRoute], str],
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
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        """
        Add a *path operation* using an HTTP PATCH operation.

        ## Example

        ```python
        from fastapi import FastAPI
        from pydantic import BaseModel

        class Item(BaseModel):
            name: str
            description: str | None = None

        app = FastAPI()

        @app.patch("/items/")
        def update_item(item: Item):
            return {"message": "Item updated in place"}
        ```
        """
        return self.router.patch(
            path,
            response_model=response_model,
            status_code=status_code,
            tags=tags,
            dependencies=dependencies,
            summary=summary,
            description=description,
            response_description=response_description,
            responses=responses,
            deprecated=deprecated,
            operation_id=operation_id,
            response_model_include=response_model_include,
            response_model_exclude=response_model_exclude,
            response_model_by_alias=response_model_by_alias,
            response_model_exclude_unset=response_model_exclude_unset,
            response_model_exclude_defaults=response_model_exclude_defaults,
            response_model_exclude_none=response_model_exclude_none,
            include_in_schema=include_in_schema,
            response_class=response_class,
            name=name,
            callbacks=callbacks,
            openapi_extra=openapi_extra,
            generate_unique_id_function=generate_unique_id_function,
        )

    def trace(
        self,
        path: Annotated[
            str,
            Doc(
                """
                The URL path to be used for this *path operation*.

                For example, in `http://example.com/items`, the path is `/items`.
                """
            ),
        ],
        *,
        response_model: Annotated[
            Any,
            Doc(
                """
                The type to use for the response.

                It could be any valid Pydantic *field* type. So, it doesn't have to
                be a Pydantic model, it could be other things, like a `list`, `dict`,
                etc.

                It will be used for:

                * Documentation: the generated OpenAPI (and the UI at `/docs`) will
                    show it as the response (JSON Schema).
                * Serialization: you could return an arbitrary object and the
                    `response_model` would be used to serialize that object into the
                    corresponding JSON.
                * Filtering: the JSON sent to the client will only contain the data
                    (fields) defined in the `response_model`. If you returned an object
                    that contains an attribute `password` but the `response_model` does
                    not include that field, the JSON sent to the client would not have
                    that `password`.
                * Validation: whatever you return will be serialized with the
                    `response_model`, converting any data as necessary to generate the
                    corresponding JSON. But if the data in the object returned is not
                    valid, that would mean a violation of the contract with the client,
                    so it's an error from the API developer. So, FastAPI will raise an
                    error and return a 500 error code (Internal Server Error).

                Read more about it in the
                [FastAPI docs for Response Model](https://fastapi.tiangolo.com/tutorial/response-model/).
                """
            ),
        ] = Default(None),
        status_code: Annotated[
            int | None,
            Doc(
                """
                The default status code to be used for the response.

                You could override the status code by returning a response directly.

                Read more about it in the
                [FastAPI docs for Response Status Code](https://fastapi.tiangolo.com/tutorial/response-status-code/).
                """
            ),
        ] = None,
        tags: Annotated[
            list[str | Enum] | None,
            Doc(
                """
                A list of tags to be applied to the *path operation*.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Path Operation Configuration](https://fastapi.tiangolo.com/tutorial/path-operation-configuration/#tags).
                """
            ),
        ] = None,
        dependencies: Annotated[
            Sequence[Depends] | None,
            Doc(
                """
                A list of dependencies (using `Depends()`) to be applied to the
                *path operation*.

                Read more about it in the
                [FastAPI docs for Dependencies in path operation decorators](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-in-path-operation-decorators/).
                """
            ),
        ] = None,
        summary: Annotated[
            str | None,
            Doc(
                """
                A summary for the *path operation*.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Path Operation Configuration](https://fastapi.tiangolo.com/tutorial/path-operation-configuration/).
                """
            ),
        ] = None,
        description: Annotated[
            str | None,
            Doc(
                """
                A description for the *path operation*.

                If not provided, it will be extracted automatically from the docstring
                of the *path operation function*.

                It can contain Markdown.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Path Operation Configuration](https://fastapi.tiangolo.com/tutorial/path-operation-configuration/).
                """
            ),
        ] = None,
        response_description: Annotated[
            str,
            Doc(
                """
                The description for the default response.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).
                """
            ),
        ] = "Successful Response",
        responses: Annotated[
            dict[int | str, dict[str, Any]] | None,
            Doc(
                """
                Additional responses that could be returned by this *path operation*.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).
                """
            ),
        ] = None,
        deprecated: Annotated[
            bool | None,
            Doc(
                """
                Mark this *path operation* as deprecated.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).
                """
            ),
        ] = None,
        operation_id: Annotated[
            str | None,
            Doc(
                """
                Custom operation ID to be used by this *path operation*.

                By default, it is generated automatically.

                If you provide a custom operation ID, you need to make sure it is
                unique for the whole API.

                You can customize the
                operation ID generation with the parameter
                `generate_unique_id_function` in the `FastAPI` class.

                Read more about it in the
                [FastAPI docs about how to Generate Clients](https://fastapi.tiangolo.com/advanced/generate-clients/#custom-generate-unique-id-function).
                """
            ),
        ] = None,
        response_model_include: Annotated[
            IncEx | None,
            Doc(
                """
                Configuration passed to Pydantic to include only certain fields in the
                response data.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_include-and-response_model_exclude).
                """
            ),
        ] = None,
        response_model_exclude: Annotated[
            IncEx | None,
            Doc(
                """
                Configuration passed to Pydantic to exclude certain fields in the
                response data.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_include-and-response_model_exclude).
                """
            ),
        ] = None,
        response_model_by_alias: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response model
                should be serialized by alias when an alias is used.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_include-and-response_model_exclude).
                """
            ),
        ] = True,
        response_model_exclude_unset: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response data
                should have all the fields, including the ones that were not set and
                have their default values. This is different from
                `response_model_exclude_defaults` in that if the fields are set,
                they will be included in the response, even if the value is the same
                as the default.

                When `True`, default values are omitted from the response.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#use-the-response_model_exclude_unset-parameter).
                """
            ),
        ] = False,
        response_model_exclude_defaults: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response data
                should have all the fields, including the ones that have the same value
                as the default. This is different from `response_model_exclude_unset`
                in that if the fields are set but contain the same default values,
                they will be excluded from the response.

                When `True`, default values are omitted from the response.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#use-the-response_model_exclude_unset-parameter).
                """
            ),
        ] = False,
        response_model_exclude_none: Annotated[
            bool,
            Doc(
                """
                Configuration passed to Pydantic to define if the response data should
                exclude fields set to `None`.

                This is much simpler (less smart) than `response_model_exclude_unset`
                and `response_model_exclude_defaults`. You probably want to use one of
                those two instead of this one, as those allow returning `None` values
                when it makes sense.

                Read more about it in the
                [FastAPI docs for Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/#response_model_exclude_none).
                """
            ),
        ] = False,
        include_in_schema: Annotated[
            bool,
            Doc(
                """
                Include this *path operation* in the generated OpenAPI schema.

                This affects the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for Query Parameters and String Validations](https://fastapi.tiangolo.com/tutorial/query-params-str-validations/#exclude-parameters-from-openapi).
                """
            ),
        ] = True,
        response_class: Annotated[
            type[Response],
            Doc(
                """
                Response class to be used for this *path operation*.

                This will not be used if you return a response directly.

                Read more about it in the
                [FastAPI docs for Custom Response - HTML, Stream, File, others](https://fastapi.tiangolo.com/advanced/custom-response/#redirectresponse).
                """
            ),
        ] = Default(JSONResponse),
        name: Annotated[
            str | None,
            Doc(
                """
                Name for this *path operation*. Only used internally.
                """
            ),
        ] = None,
        callbacks: Annotated[
            list[BaseRoute] | None,
            Doc(
                """
                List of *path operations* that will be used as OpenAPI callbacks.

                This is only for OpenAPI documentation, the callbacks won't be used
                directly.

                It will be added to the generated OpenAPI (e.g. visible at `/docs`).

                Read more about it in the
                [FastAPI docs for OpenAPI Callbacks](https://fastapi.tiangolo.com/advanced/openapi-callbacks/).
                """
            ),
        ] = None,
        openapi_extra: Annotated[
            dict[str, Any] | None,
            Doc(
                """
                Extra metadata to be included in the OpenAPI schema for this *path
                operation*.

                Read more about it in the
                [FastAPI docs for Path Operation Advanced Configuration](https://fastapi.tiangolo.com/advanced/path-operation-advanced-configuration/#custom-openapi-path-operation-schema).
                """
            ),
        ] = None,
        generate_unique_id_function: Annotated[
            Callable[[routing.APIRoute], str],
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
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        """
        Add a *path operation* using an HTTP TRACE operation.

        ## Example

        ```python
        from fastapi import FastAPI

        app = FastAPI()

        @app.trace("/items/{item_id}")
        def trace_item(item_id: str):
            return None
        ```
        """
        return self.router.trace(
            path,
            response_model=response_model,
            status_code=status_code,
            tags=tags,
            dependencies=dependencies,
            summary=summary,
            description=description,
            response_description=response_description,
            responses=responses,
            deprecated=deprecated,
            operation_id=operation_id,
            response_model_include=response_model_include,
            response_model_exclude=response_model_exclude,
            response_model_by_alias=response_model_by_alias,
            response_model_exclude_unset=response_model_exclude_unset,
            response_model_exclude_defaults=response_model_exclude_defaults,
            response_model_exclude_none=response_model_exclude_none,
            include_in_schema=include_in_schema,
            response_class=response_class,
            name=name,
            callbacks=callbacks,
            openapi_extra=openapi_extra,
            generate_unique_id_function=generate_unique_id_function,
        )

    def websocket_route(
        self, path: str, name: str | None = None
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        def decorator(func: DecoratedCallable) -> DecoratedCallable:
            self.router.add_websocket_route(path, func, name=name)
            return func

        return decorator

    @deprecated(
        """
        on_event is deprecated, use lifespan event handlers instead.

        Read more about it in the
        [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).
        """
    )
    def on_event(
        self,
        event_type: Annotated[
            str,
            Doc(
                """
                The type of event. `startup` or `shutdown`.
                """
            ),
        ],
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        """
        Add an event handler for the application.

        `on_event` is deprecated, use `lifespan` event handlers instead.

        Read more about it in the
        [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/#alternative-events-deprecated).
        """
        return self.router.on_event(event_type)

    def middleware(
        self,
        middleware_type: Annotated[
            str,
            Doc(
                """
                The type of middleware. Currently only supports `http`.
                """
            ),
        ],
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        """
        Add a middleware to the application.

        Read more about it in the
        [FastAPI docs for Middleware](https://fastapi.tiangolo.com/tutorial/middleware/).

        ## Example

        ```python
        import time
        from typing import Awaitable, Callable

        from fastapi import FastAPI, Request, Response

        app = FastAPI()


        @app.middleware("http")
        async def add_process_time_header(
            request: Request, call_next: Callable[[Request], Awaitable[Response]]
        ) -> Response:
            start_time = time.time()
            response = await call_next(request)
            process_time = time.time() - start_time
            response.headers["X-Process-Time"] = str(process_time)
            return response
        ```
        """

        def decorator(func: DecoratedCallable) -> DecoratedCallable:
            self.add_middleware(BaseHTTPMiddleware, dispatch=func)
            return func

        return decorator

    def exception_handler(
        self,
        exc_class_or_status_code: Annotated[
            int | type[Exception],
            Doc(
                """
                The Exception class this would handle, or a status code.
                """
            ),
        ],
    ) -> Callable[[DecoratedCallable], DecoratedCallable]:
        """
        Add an exception handler to the app.

        Read more about it in the
        [FastAPI docs for Handling Errors](https://fastapi.tiangolo.com/tutorial/handling-errors/).

        ## Example

        ```python
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse


        class UnicornException(Exception):
            def __init__(self, name: str):
                self.name = name


        app = FastAPI()


        @app.exception_handler(UnicornException)
        async def unicorn_exception_handler(request: Request, exc: UnicornException):
            return JSONResponse(
                status_code=418,
                content={"message": f"Oops! {exc.name} did something. There goes a rainbow..."},
            )
        ```
        """

        def decorator(func: DecoratedCallable) -> DecoratedCallable:
            self.add_exception_handler(exc_class_or_status_code, func)
            return func

        return decorator