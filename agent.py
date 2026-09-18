"""A tiny, public A2A-compatible weather demo agent.

It deliberately returns demo data and needs no external API key. Replace
weather_reply() with a real provider only after deployment is working.
"""

import os
import re
import uuid
import json
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import urlopen

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


app = FastAPI(title="Starter Weather Agent")


WEATHER_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "rime fog", 51: "light drizzle", 53: "drizzle",
    55: "dense drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 80: "rain showers",
    81: "rain showers", 82: "violent rain showers", 95: "thunderstorm",
    96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}


def get_json(url: str) -> dict:
    """Fetch JSON from a public weather endpoint with a short timeout."""
    with urlopen(url, timeout=10) as response:  # nosec B310: fixed HTTPS hosts below
        return json.load(response)


def location_from_question(question: str) -> str:
    match = re.search(r"(?:in|for)\s+([A-Za-z][A-Za-z .'-]{1,50})", question, re.I)
    return match.group(1).strip(" ?.!") if match else ""


def weather_reply(question: str) -> str:
    """Look up a place and return live current conditions from Open-Meteo."""
    place = location_from_question(question)
    if not place:
        return "Tell me the city or location, for example: What is the weather in London?"

    try:
        geocoding_url = "https://geocoding-api.open-meteo.com/v1/search?" + urlencode(
            {"name": place, "count": 1, "language": "en", "format": "json"}
        )
        results = get_json(geocoding_url).get("results", [])
        if not results:
            return f"I could not find a location matching '{place}'. Please include a city and country."

        location = results[0]
        forecast_url = "https://api.open-meteo.com/v1/forecast?" + urlencode(
            {
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
                "timezone": "auto",
            }
        )
        current = get_json(forecast_url)["current"]
        condition = WEATHER_CODES.get(current.get("weather_code"), "unknown conditions")
        location_name = ", ".join(
            part for part in (location.get("name"), location.get("country")) if part
        )
        return (
            f"Current weather in {location_name}: {condition}, "
            f"{current['temperature_2m']}°C (feels like {current['apparent_temperature']}°C), "
            f"wind {current['wind_speed_10m']} km/h. "
            "Source: Open-Meteo forecast data."
        )
    except Exception:
        return (
            "I could not retrieve live weather data right now. "
            "Please try again in a moment."
        )


def agent_card(request: Request) -> dict:
    base_url = str(request.base_url).rstrip("/")
    return {
        "protocolVersion": "0.3.0",
        "name": "Starter Weather Agent",
        "description": "An A2A weather agent using live Open-Meteo forecast data.",
        "url": base_url + "/",
        "version": "0.1.0",
        "supportedInterfaces": [
            {
                "url": base_url + "/",
                "protocolBinding": "JSONRPC",
                "protocolVersion": "0.3",
            }
        ],
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "skills": [
            {
                "id": "weather_lookup",
                "name": "Demo weather lookup",
                "description": "Returns live current weather for a requested location.",
                "tags": ["weather", "demo"],
                "examples": ["What is the weather in London?"],
            }
        ],
    }


@app.get("/.well-known/agent-card.json")
async def get_agent_card(request: Request):
    return agent_card(request)


@app.post("/")
async def a2a_endpoint(request: Request):
    payload = await request.json()
    request_id = payload.get("id")
    if payload.get("jsonrpc") != "2.0" or payload.get("method") != "message/send":
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": "Use the message/send method."},
            },
        )

    parts = payload.get("params", {}).get("message", {}).get("parts", [])
    question = " ".join(
        part.get("text", "") for part in parts if part.get("kind") == "text"
    ).strip()
    if not question:
        question = "weather"

    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "id": task_id,
            "status": {"state": "completed", "timestamp": now},
            "artifacts": [
                {
                    "artifactId": "weather-answer",
                    "name": "Demo weather answer",
                    "parts": [{"kind": "text", "text": weather_reply(question)}],
                }
            ],
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
