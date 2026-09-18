# Starter Weather A2A Agent

An A2A-compatible weather service. It uses Open-Meteo's public geocoding and
forecast APIs, so the starter needs no API key for this demonstration.

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

The card describes how another A2A client reaches the JSON-RPC endpoint. Before using this beyond a demo, add authentication and rate limiting. Review Open-Meteo's terms and attribution requirements before commercial use.
