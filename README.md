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
