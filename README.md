# Travel Buddy

Day-trip planner: a LangChain agent (local Ollama LLM) using MCP tools (places, hotels, weather, distances, budget).

## Run

```bash
ollama pull qwen2.5:7b          # local LLM, Ollama must be running
uv sync

# Terminal 1: API (http://localhost:8000/docs)
uv run uvicorn api:app --reload

# Terminal 2: interface (http://localhost:8501)
uv run streamlit run app.py
```

CLI only: `uv run python agent.py`

## Files

- `server.py`: MCP server with the tools
- `agent.py`: the agent (`build_agent`, `plan_trip`, `get_traces`) + CLI
- `api.py`: FastAPI backend
  - `POST /trip/stream`: the trip field by field (city, date, interests, budget, hotel...), streams each tool call then the result (NDJSON)
  - `POST /plan {"request": "..."}`: free-text request, one JSON answer
- `app.py`: Streamlit interface: a 3-step form (where & when, what you like, budget & stay), live progress, then plan, map, weather, budget and traces
- `.streamlit/config.toml`: theme (sky blue + orange, Plus Jakarta Sans)

## Live prices (optional)

The budget is computed by `calculate_budget` in `server.py`, never by the LLM:

| Cost | Source |
|---|---|
| Transport | Official fares (table in `server.py`, check them now and then) |
| Entry fees | OpenStreetMap `charge` / `fee` tags, else estimate |
| Hotel night | **Live**: `search_hotels` lists real hotels under your budget with their Google Hotels price for the trip date (SerpApi), else OpenStreetMap + estimate by stars |
| Meals | Reference estimate (Google Maps shows no price range for French restaurants) |

To enable live prices, create a free key on https://serpapi.com (250 searches/month, 1 per plan with a hotel) and put it in `.env`:

```bash
cp .env.example .env   # then fill SERPAPI_KEY=...
```

Answers are cached for the day in `.price_cache.json`.

## Countries and cities

`data/cities.json.gz` lists 246 countries and 169,376 cities and towns over 1,000 inhabitants, from
[GeoNames](https://www.geonames.org) (CC BY 4.0). To refresh it, download `cities1000.zip` (unzip it),
`countryInfo.txt` and `admin1CodesASCII.txt` from https://download.geonames.org/export/dump/ into a folder, then:

```bash
uv run python scripts/build_cities.py <that folder>
```

## Deploy on Streamlit Community Cloud

Online there is no Ollama and no API: `app.py` runs the agent itself, with a hosted model from Groq.

1. Create a free key on https://console.groq.com/keys
2. In the app's **Settings → Secrets** on share.streamlit.io, paste:
   ```toml
   GROQ_API_KEY = "gsk_..."
   SERPAPI_KEY = "..."          # optional: live hotel prices
   # LLM_MODEL = "openai/gpt-oss-120b"   # optional: another Groq model
   ```
3. Entrypoint `app.py`, Python 3.12 or newer. Dependencies are installed from `uv.lock`.

How the app picks its agent: the API at `TRAVEL_BUDDY_API` (default `http://localhost:8000`) if it answers;
otherwise it runs the agent in-process, with Groq if `GROQ_API_KEY` is set, else the local Ollama.
