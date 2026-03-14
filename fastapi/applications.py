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
):
    logging.basicConfig(level=logging.INFO)
    logging.info("Initializing API")
    # ... rest of the function remains the same ...
    # ... rest of the function remains the same ...
    # ... rest of the function remains the same ...
    # ... rest of the function remains the same ...
    # ... rest of the function remains the same ...

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
    logging.info(f"Adding API route: {path}")
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