"""A2A 1.0 weather agent using live Open-Meteo data."""

import hmac
import json
import os
import re
from urllib.parse import urlencode
from urllib.request import urlopen

import uvicorn
from a2a.helpers import (
    get_message_text,
    new_task_from_user_message,
    new_text_message,
    new_text_part,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    create_agent_card_routes,
    create_jsonrpc_routes,
    create_rest_routes,
)
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
)
from a2a.types.a2a_pb2 import TaskState
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route


PORT = int(os.environ.get("PORT", "10000"))
PUBLIC_URL = os.environ.get(
    "A2A_PUBLIC_URL",
    "https://a2a-weather-agent-bca5.onrender.com",
).rstrip("/")


WEATHER_CODES = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "rime fog",
    51: "light drizzle",
    53: "drizzle",
    55: "dense drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    80: "rain showers",
    81: "rain showers",
    82: "violent rain showers",
    95: "thunderstorm",
    96: "thunderstorm with hail",
    99: "thunderstorm with heavy hail",
}


def get_json(url: str) -> dict:
    """Retrieve JSON from an HTTPS endpoint."""

    with urlopen(url, timeout=10) as response:
        return json.load(response)


def location_from_question(question: str) -> str:
    """Extract the requested location from a weather question."""

    match = re.search(
        r"(?:in|for)\s+([A-Za-z][A-Za-z .'-]{1,50})",
        question,
        re.IGNORECASE,
    )
    return match.group(1).strip(" ?.!") if match else ""


def weather_reply(question: str) -> str:
    """Return current Open-Meteo weather for a requested location."""

    place = location_from_question(question)

    if not place:
        return (
            "Tell me the city or location, for example: "
            "What is the weather in London?"
        )

    try:
        geocoding_url = (
            "https://geocoding-api.open-meteo.com/v1/search?"
            + urlencode(
                {
                    "name": place,
                    "count": 1,
                    "language": "en",
                    "format": "json",
                }
            )
        )

        results = get_json(geocoding_url).get("results", [])

        if not results:
            return (
                f"I could not find a location matching '{place}'. "
                "Please include a city and country."
            )

        location = results[0]

        forecast_url = (
            "https://api.open-meteo.com/v1/forecast?"
            + urlencode(
                {
                    "latitude": location["latitude"],
                    "longitude": location["longitude"],
                    "current": (
                        "temperature_2m,apparent_temperature,"
                        "weather_code,wind_speed_10m"
                    ),
                    "timezone": "auto",
                }
            )
        )

        current = get_json(forecast_url)["current"]
        condition = WEATHER_CODES.get(
            current.get("weather_code"),
            "unknown conditions",
        )

        location_name = ", ".join(
            part
            for part in (
                location.get("name"),
                location.get("country"),
            )
            if part
        )

        return (
            f"Current weather in {location_name}: {condition}, "
            f"{current['temperature_2m']}°C "
            f"(feels like {current['apparent_temperature']}°C), "
            f"wind {current['wind_speed_10m']} km/h. "
            "Source: Open-Meteo."
        )

    except Exception:
        return (
            "I could not retrieve live weather data right now. "
            "Please try again in a moment."
        )


class WeatherAgentExecutor(AgentExecutor):
    """Process one weather request using an A2A task lifecycle."""

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        if context.current_task:
            task = context.current_task
        else:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=task.id,
            context_id=task.context_id,
        )

        await updater.update_status(
            state=TaskState.TASK_STATE_WORKING,
            message=new_text_message("Checking current weather."),
        )

        question = (
            get_message_text(context.message)
            if context.message
            else ""
        )
        answer = weather_reply(question)

        await updater.add_artifact(
            parts=[
                new_text_part(
                    text=answer,
                    media_type="text/plain",
                )
            ],
            name="Current weather",
        )

        await updater.update_status(
            state=TaskState.TASK_STATE_COMPLETED,
            message=new_text_message("Weather lookup completed."),
        )

    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        raise NotImplementedError("Cancellation is not supported.")

class FusionA2AVersionCompatibilityMiddleware:
    """Normalize Fusion requests for this stateless weather agent."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        public_paths = {
            "/.well-known/agent-card.json",
            "/health",
        }

        if (
            scope["type"] == "http"
            and scope.get("path") not in public_paths
        ):
            updated_headers = []
            version_header_found = False

            for header_name, header_value in scope.get("headers", []):
                if header_name.lower() == b"a2a-version":
                    updated_headers.append((header_name, b"1.0"))
                    version_header_found = True
                else:
                    updated_headers.append((header_name, header_value))

            if not version_header_found:
                updated_headers.append((b"a2a-version", b"1.0"))

            scope = dict(scope)
            scope["headers"] = updated_headers

            if (
                scope.get("method") == "POST"
                and scope.get("path") == "/message:send"
            ):
                receive = await self._fresh_task_request(receive)

        await self.app(scope, receive, send)

    @staticmethod
    async def _fresh_task_request(receive):
        """Remove stale task identity from an independent weather lookup."""

        first_event = await receive()
        body = first_event.get("body", b"")

        if body:
            try:
                payload = json.loads(body)
                message = payload.get("message")

                if isinstance(message, dict):
                    message.pop("taskId", None)
                    message.pop("contextId", None)
                    first_event = dict(first_event)
                    first_event["body"] = json.dumps(payload).encode("utf-8")
            except (TypeError, ValueError):
                pass

        delivered = False

        async def normalized_receive():
            nonlocal delivered

            if not delivered:
                delivered = True
                return first_event

            return await receive()

        return normalized_receive


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Require Bearer-token authentication for A2A operations."""

    PUBLIC_PATHS = {
        "/.well-known/agent-card.json",
        "/health",
    }

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.PUBLIC_PATHS:
            return await call_next(request)

        expected_token = os.environ.get("A2A_BEARER_TOKEN")

        if not expected_token:
            return JSONResponse(
                {"detail": "A2A Bearer authentication is not configured."},
                status_code=503,
            )

        authorization = request.headers.get("authorization", "")

        if not authorization.lower().startswith("bearer "):
            return self.unauthorized()

        supplied_token = authorization.split(" ", 1)[1].strip()

        if not supplied_token:
            return self.unauthorized()

        if not hmac.compare_digest(supplied_token, expected_token):
            return self.unauthorized()

        return await call_next(request)

    @staticmethod
    def unauthorized() -> Response:
        return JSONResponse(
            {"detail": "A valid Bearer token is required."},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


agent_card = AgentCard(
    name="Starter Weather Agent",
    description=(
        "An A2A weather agent using live Open-Meteo current-weather data."
    ),
    version="1.0.0",
    provider={
        "organization": "A2A Weather Demo",
        "url": PUBLIC_URL,
    },
    capabilities=AgentCapabilities(
        streaming=False,
        push_notifications=False,
        extended_agent_card=False,
    ),
    default_input_modes=[
        "text/plain",
        "application/json",
    ],
    default_output_modes=[
        "text/plain",
        "application/json",
    ],
    supported_interfaces=[
        AgentInterface(
            url=PUBLIC_URL,
            protocol_binding="HTTP+JSON",
            protocol_version="1.0",
        ),
        AgentInterface(
            url=PUBLIC_URL,
            protocol_binding="JSONRPC",
            protocol_version="1.0",
        ),
    ],
    security_schemes={
        "bearer_auth": {
            "http_auth_security_scheme": {
                "description": (
                    "Bearer token authentication for A2A operations."
                ),
                "scheme": "Bearer",
                "bearer_format": "opaque",
            }
        }
    },
    security_requirements=[
        {
            "schemes": {
                "bearer_auth": {
                    "list": [],
                }
            }
        }
    ],
    skills=[
        AgentSkill(
            id="weather_lookup",
            name="demo_weather_lookup",
            description=(
                "Returns live current weather for a requested location."
            ),
            tags=[
                "weather",
                "open-meteo",
                "current conditions",
            ],
            examples=[
                "What is the weather in London?",
            ],
            input_modes=[
                "text/plain",
                "application/json",
            ],
            output_modes=[
                "text/plain",
                "application/json",
            ],
        )
    ],
)


request_handler = DefaultRequestHandler(
    agent_executor=WeatherAgentExecutor(),
    task_store=InMemoryTaskStore(),
    agent_card=agent_card,
)


routes = [
    Route("/health", health, methods=["GET"]),
    *create_agent_card_routes(agent_card),
    *create_jsonrpc_routes(request_handler, rpc_url="/"),
    *create_rest_routes(request_handler),
]


app = Starlette(
    routes=routes,
    middleware=[
        Middleware(FusionA2AVersionCompatibilityMiddleware),
        Middleware(BearerAuthMiddleware),
    ],
)

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
    )
