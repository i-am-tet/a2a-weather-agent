# Starter Weather A2A Agent

A safe A2A-compatible weather demonstration service. It has no API key and deliberately returns sample weather data.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python agent.py
```

In another terminal:

```bash
curl http://localhost:10000/.well-known/agent-card.json
curl -X POST http://localhost:10000/ -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":"test-1","method":"message/send","params":{"message":{"role":"user","parts":[{"kind":"text","text":"What is the weather in London?"}]}}}'
```

The card describes how another A2A client reaches the JSON-RPC endpoint. Before using this beyond a demo, add authentication, rate limiting, and a real weather provider whose credentials are stored as deployment environment variables.
