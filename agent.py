"""A tiny, public A2A-compatible weather demo agent.

It deliberately returns demo data and needs no external API key. Replace
weather_reply() with a real provider only after deployment is working.
"""

import os
import re
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


app = FastAPI(title="Starter Weather Agent")


def weather_reply(question: str) -> str:
    """Return a clearly labelled non-production response."""
    match = re.search(r"(?:in|for)\s+([A-Za-z][A-Za-z .'-]{1,50})", question, re.I)
    place = match.group(1).strip(" ?.!") if match else "the requested location"
    return (
        f"Demo weather result for {place}: sunny, 22°C. "
        "This is sample data, not a live weather forecast."
    )


def agent_card(request: Request) -> dict:
    base_url = str(request.base_url).rstrip("/")
    return {
        "protocolVersion": "0.3.0",
        "name": "Starter Weather Agent",
        "description": "A harmless A2A weather demo agent with no API key.",
        "url": base_url + "/",
        "version": "0.1.0",
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "skills": [
            {
                "id": "weather_lookup",
                "name": "Demo weather lookup",
                "description": "Returns clearly labelled demonstration weather information.",
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
