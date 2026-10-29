"""Travel Buddy - FastAPI backend exposing the agent over HTTP.

Run: uvicorn api:app --reload
"""

import json
import time
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from server import SERPAPI_KEY
from agent import MODEL, build_agent, final_plan, get_traces, plan_trip, trip_events


class PlanRequest(BaseModel):
    request: str = Field(min_length=3, examples=["Plan me a day in Lyon tomorrow. I love museums. My budget is 80 euros."])


class TripRequest(BaseModel):
    """The trip, field by field (what the Streamlit form sends)."""
    city: str = Field(min_length=2, examples=["Lyon"])
    country: str = Field("France", min_length=2)
    trip_date: date
    interests: list[str] = Field(default_factory=list, examples=[["Museums", "Food"]])
    budget: float = Field(gt=0, examples=[150])
    pace: Literal["Relaxed", "Balanced", "Packed"] = "Balanced"
    needs_hotel: bool = False
    hotel_stars: int | None = Field(None, ge=1, le=5)
    stay_near: str = ""
    notes: str = ""


class PlanResponse(BaseModel):
    plan: str
    traces: list[dict]
    model: str
    duration_s: float


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Build the agent once (loads the MCP tools), reuse it for every request
    app.state.agent = await build_agent()
    yield


app = FastAPI(title="Travel Buddy API", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL, "live_prices": bool(SERPAPI_KEY)}


@app.post("/plan", response_model=PlanResponse)
async def plan(body: PlanRequest):
    start = time.perf_counter()
    try:
        messages = await plan_trip(app.state.agent, body.request)
    except Exception as e:  # Ollama down, Nominatim timeout...
        raise HTTPException(status_code=502, detail=f"Agent failed: {e}")
    return PlanResponse(
        plan=final_plan(messages),
        traces=get_traces(messages),
        model=MODEL,
        duration_s=round(time.perf_counter() - start, 1),
    )


@app.post("/trip/stream")
async def trip_stream(trip: TripRequest):
    """Plan a trip from form fields. Streams one JSON line per event: each tool call as it happens, then the result."""
    async def events():
        try:
            async for event in trip_events(app.state.agent, trip.model_dump(mode="json")):
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except Exception as e:  # LLM down, Nominatim timeout...
            yield json.dumps({"type": "error", "detail": f"Agent failed: {e}"}) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson")
