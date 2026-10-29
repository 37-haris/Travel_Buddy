"""Travel Buddy - Streamlit interface, talks to the FastAPI backend (api.py).

Run: streamlit run app.py   (with the API started: uvicorn api:app)
"""

import gzip
import html
import json
import os
from datetime import date, timedelta
from pathlib import Path

import httpx
import pandas as pd
import pydeck as pdk
import streamlit as st

API_URL = os.getenv("TRAVEL_BUDDY_API", "http://localhost:8000")  # where `uvicorn api:app` runs
PACE_HINTS = {
    "Relaxed": ":material/self_improvement: 2 places · starts at 10:00 · long lunch",
    "Balanced": ":material/directions_walk: 3 places · starts at 09:30",
    "Packed": ":material/directions_run: 5 places · from 08:30 to the evening",
}
SLOT_ICONS = {"place": "place", "lunch": "lunch_dining", "dinner": "dinner_dining"}
CITIES_FILE = Path(__file__).parent / "data" / "cities.json.gz"  # built by scripts/build_cities.py from GeoNames
INTERESTS = {  # label -> Material icon
    "Museums": "museum", "Food": "restaurant", "Parks": "park", "History": "account_balance", "Art": "palette",
    "Shopping": "shopping_bag", "Nightlife": "nightlife", "Cafés": "local_cafe", "Churches": "church", "Temples": "temple_buddhist", "Viewpoints": "landscape",
}
STEP_LABELS = {  # tool -> (icon, what the user sees)
    "search_places": ("search", lambda a: f"Searching {a.get('query', 'places')} in {a.get('city', '')}"),
    "search_hotels": ("hotel", lambda a: "Looking for hotels nearby"),
    "get_weather": ("partly_cloudy_day", lambda a: "Checking the weather forecast"),
    "calculate_distance": ("straighten", lambda a: "Measuring walking distances"),
    "calculate_budget": ("payments", lambda a: "Calculating the budget with real prices"),
}
WEATHER_ICONS = [("Clear", "sunny"), ("Mainly", "partly_cloudy_day"), ("Partly", "partly_cloudy_day"), ("Overcast", "cloud"),
                 ("Fog", "foggy"), ("Depositing", "foggy"), ("Drizzle", "rainy"), ("Freezing", "ac_unit"), ("Rain", "rainy"),
                 ("Snow", "weather_snowy"), ("Thunderstorm", "thunderstorm")]
SOURCE_KINDS = [("live", "Live price"), ("official", "Official fare"), ("no entry fee", "Free"), ("free (", "Free"),
                ("estimate", "Estimate"), ("OpenStreetMap", "OpenStreetMap")]  # first match wins: "estimate" before "OpenStreetMap"

st.set_page_config(page_title="Travel Buddy", page_icon=":material/travel_explore:", layout="wide")

st.markdown("""
<style>
:root {
  --tb-primary: #0369A1; --tb-primary-dark: #075985; --tb-accent: #EA580C;
  --tb-fg: #0C4A6E; --tb-muted: #475569; --tb-card: #FFFFFF; --tb-border: #BAE6FD;
}
.block-container { padding-top: 4.5rem; max-width: 1200px; }
.tb-hero {
  background: linear-gradient(135deg, var(--tb-primary-dark) 0%, var(--tb-primary) 55%, #0EA5E9 100%);
  color: #FFFFFF; border-radius: 20px; padding: 2rem 2.25rem; margin-bottom: 1.5rem;
  box-shadow: 0 10px 30px -12px rgba(3, 105, 161, .45);
}
.tb-hero h1 { color: #FFFFFF; font-size: 2.2rem; font-weight: 800; margin: 0 0 .35rem 0; padding: 0; }
.tb-hero p { color: #E0F2FE; font-size: 1.05rem; margin: 0; max-width: 46rem; line-height: 1.55; }
.tb-chips { display: flex; flex-wrap: wrap; gap: .5rem; margin-top: 1.1rem; }
.tb-chip {
  display: inline-flex; align-items: center; gap: .45rem; padding: .3rem .8rem; border-radius: 999px;
  background: rgba(255, 255, 255, .16); border: 1px solid rgba(255, 255, 255, .28); color: #FFFFFF;
  font-size: .85rem; font-weight: 600;
}
.tb-dot { width: .55rem; height: .55rem; border-radius: 999px; }
.tb-dot-ok { background: #4ADE80; box-shadow: 0 0 0 3px rgba(74, 222, 128, .25); }
.tb-dot-warn { background: #FBBF24; box-shadow: 0 0 0 3px rgba(251, 191, 36, .25); }
.tb-dot-off { background: #F87171; box-shadow: 0 0 0 3px rgba(248, 113, 113, .25); }
.tb-timeline { display: flex; flex-direction: column; gap: .5rem; margin: .25rem 0 .75rem 0; }
.tb-slot {
  display: flex; align-items: center; gap: .85rem; padding: .65rem .8rem; border-radius: 12px;
  background: #F0F9FF; border: 1px solid var(--tb-border); border-left: 4px solid var(--tb-primary);
}
.tb-slot-lunch, .tb-slot-dinner { border-left-color: var(--tb-accent); background: #FFF7ED; border-color: #FED7AA; }
.tb-time { font-weight: 700; font-variant-numeric: tabular-nums; color: var(--tb-fg); min-width: 3.1rem; }
.tb-what { flex: 1; display: flex; flex-direction: column; color: var(--tb-fg); font-weight: 600; line-height: 1.3; }
.tb-kind { font-size: .72rem; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; color: var(--tb-muted); }
.tb-price { font-size: .85rem; color: var(--tb-muted); white-space: nowrap; }
.tb-how { font-size: .92rem; color: var(--tb-muted); line-height: 1.55; margin: 0 0 .5rem 0; }
.tb-step { display: flex; align-items: center; gap: .6rem; margin: 0 0 .75rem 0; }
.tb-step-num {
  width: 1.9rem; height: 1.9rem; border-radius: 999px; background: var(--tb-primary); color: #FFFFFF;
  display: inline-flex; align-items: center; justify-content: center; font-weight: 700; font-size: .95rem;
}
.tb-step-title { font-weight: 700; font-size: 1.1rem; color: var(--tb-fg); }
div[data-testid="stVerticalBlockBorderWrapper"] { background: var(--tb-card); }
div[data-testid="stMetric"] {
  background: var(--tb-card); border: 1px solid var(--tb-border); border-radius: 14px; padding: .9rem 1.1rem;
}
.stButton button, .stPills button, .stSegmentedControl button { transition: all .2s ease; cursor: pointer; }
/* Selected chips: solid fill, so the choice is obvious (not color-only: the fill also changes the contrast) */
button[aria-pressed="true"]:not(:disabled), button[aria-checked="true"]:not(:disabled) {
  background: var(--tb-primary) !important; color: #FFFFFF !important; border-color: var(--tb-primary) !important;
}
button[aria-pressed="true"]:not(:disabled) *, button[aria-checked="true"]:not(:disabled) * { color: #FFFFFF !important; }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style>
""", unsafe_allow_html=True)


@st.cache_data
def load_cities():
    """Every country -> its cities and towns over 1,000 inhabitants, biggest first ("Yokohama (Kanagawa)" when ambiguous)."""
    with gzip.open(CITIES_FILE, "rt", encoding="utf-8") as f:
        return json.load(f)


def step_header(number, title):
    st.markdown(f'<div class="tb-step"><span class="tb-step-num">{number}</span>'
                f'<span class="tb-step-title">{title}</span></div>', unsafe_allow_html=True)


def results_of(traces, tool):
    """All results returned by one tool, flattened into a single list of dicts."""
    items = []
    for t in traces:
        if t["tool"] == tool and t["result"]:
            items += t["result"] if isinstance(t["result"], list) else [t["result"]]
    return [i for i in items if isinstance(i, dict)]


def source_kind(source):
    return next((label for key, label in SOURCE_KINDS if key in source), "Estimate")


def weather_icon(description):
    return next((icon for key, icon in WEATHER_ICONS if description.startswith(key)), "thermostat")


# ---------- Hero with the connection status ----------
try:
    health = httpx.get(f"{API_URL}/health", timeout=3).json()
except Exception:
    health = None


def chip(text, state):
    return f'<span class="tb-chip"><span class="tb-dot tb-dot-{state}"></span>{html.escape(text)}</span>'


chips = [chip(f"Agent online · {health['model']}", "ok") if health else chip("Agent offline", "off")]
if health:
    chips.append(chip("Live hotel prices", "ok") if health.get("live_prices") else chip("Estimated hotel prices", "warn"))
st.markdown(f"""
<div class="tb-hero">
  <h1>Travel Buddy</h1>
  <p>Pick a city, a date and what you love. Your local AI agent finds real places, checks the weather and
  calculates the budget with real prices.</p>
  <div class="tb-chips">{"".join(chips)}</div>
</div>
""", unsafe_allow_html=True)
if not health:
    st.error(f"The agent API isn't reachable at {API_URL}. Start it with `uv run uvicorn api:app`, then refresh.",
             icon=":material/cloud_off:")

# ---------- Form: one card per step ----------
col_where, col_like, col_stay = st.columns(3, gap="medium")

with col_where.container(border=True, height="stretch"):
    step_header(1, "Where & when")
    cities = load_cities()
    countries = sorted(cities)
    country = st.selectbox("Country", countries, index=countries.index("France"), key="country",
                           help=f"{len(countries)} countries. Type to search.")
    # One key per country: the list always matches the country, and a new country starts on its biggest city
    city = st.selectbox("City", cities[country], index=0, accept_new_options=True, key=f"city_{country}",
                        help=f"{len(cities[country]):,} cities and towns in {country}, biggest first. "
                             "Type to search, or type a smaller place that isn't listed.")
    trip_date = st.date_input("Date", date.today() + timedelta(days=1), min_value=date.today(),
                              format="DD/MM/YYYY", key="trip_date",
                              help="Weather forecasts cover today and the next 2 days.")

with col_like.container(border=True, height="stretch"):
    step_header(2, "What you like")
    interests = st.pills("Interests", list(INTERESTS), selection_mode="multi", default=["Museums", "Food"],
                         format_func=lambda i: f":material/{INTERESTS[i]}: {i}", key="interests")
    other = st.text_input("Something else?", placeholder="e.g. street art, wine bars", key="other",
                          help="Comma-separated, each one becomes a search.")
    pace = st.segmented_control("Pace", ["Relaxed", "Balanced", "Packed"], default="Balanced", key="pace",
                                help="How full the day is.") or "Balanced"
    st.caption(PACE_HINTS[pace])

with col_stay.container(border=True, height="stretch"):
    step_header(3, "Budget & stay")
    budget = st.number_input("Budget for the day (€)", min_value=10, max_value=5000, value=150, step=10, key="budget",
                             help="Everything included: transport, entries, meals and the hotel if needed.")
    needs_hotel = st.toggle("I need a hotel for the night", key="needs_hotel")
    stars = st.pills("Hotel category", ["Any", "2★", "3★", "4★", "5★"], default="Any",
                     disabled=not needs_hotel, key="stars")
    stay_near = st.text_input("Stay near", placeholder="e.g. Place Bellecour", disabled=not needs_hotel, key="stay_near")

notes = st.text_area("Anything else the agent should know? (optional)", key="notes", height=68,
                     placeholder="e.g. I travel with a child, I don't like long walks")

all_interests = (interests or []) + [i.strip() for i in other.split(",") if i.strip()]
submit = st.button("Plan my day", type="primary", icon=":material/travel_explore:", width="stretch")

if submit and not (city or "").strip():
    st.error("Choose or type a city first.", icon=":material/location_off:")
elif submit:
    payload = {
        # "Yokohama (Kanagawa)" -> "Yokohama, Kanagawa": the region keeps the searches on the right town
        "city": city.strip().replace(" (", ", ").rstrip(")"), "country": country, "trip_date": trip_date.isoformat(),
        "interests": all_interests, "budget": budget, "pace": pace, "needs_hotel": needs_hotel,
        "hotel_stars": int(stars[0]) if needs_hotel and stars and stars != "Any" else None,
        "stay_near": stay_near if needs_hotel else "", "notes": notes,
    }
    with st.status(f"Planning your day in {city}…", expanded=True) as status:
        shown = set()
        try:
            with httpx.stream("POST", f"{API_URL}/trip/stream", json=payload, timeout=600) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    event = json.loads(line)
                    if event["type"] == "fix":
                        st.write(f":material/tune: {event['detail']}")
                    elif event["type"] == "tool":
                        icon, label = STEP_LABELS.get(event["tool"], ("build", lambda a: event["tool"]))
                        text = f":material/{icon}: {label(event['args'])}"
                        if text not in shown:  # the agent often repeats a call: show each step once
                            shown.add(text)
                            st.write(text)
                    elif event["type"] == "result":
                        st.session_state.result = event
                        st.session_state.trip = payload
                        status.update(label=f"Your day in {city} is ready ({event['duration_s']} s)",
                                      state="complete", expanded=False)
                    elif event["type"] == "error":
                        status.update(label="Planning failed", state="error")
                        st.error(event["detail"], icon=":material/error:")
        except httpx.HTTPStatusError as e:
            status.update(label="Planning failed", state="error")
            st.error(f"API error {e.response.status_code}: check the form values.", icon=":material/error:")
        except Exception as e:
            status.update(label="Planning failed", state="error")
            st.error(f"Cannot reach the API at {API_URL}: {e}", icon=":material/cloud_off:")

# ---------- Result ----------
result, trip = st.session_state.get("result"), st.session_state.get("trip")
if result:
    traces, budget_res = result["traces"], result["budget"]
    st.subheader(f"Your day in {trip['city'].split(',')[0]} · {date.fromisoformat(trip['trip_date']):%A %d %B}")

    c1, c2, c3, c4 = st.columns(4)
    if budget_res:
        verified = round(budget_res["total"] - budget_res["estimated_part"], 2)
        c1.metric("Total cost", f"{budget_res['total']:.2f} €")
        if "remaining_funds" in budget_res:
            c2.metric("Left from your budget", f"{budget_res['remaining_funds']:.2f} €",
                      delta="within budget" if budget_res["within_budget"] else "over budget",
                      delta_color="normal" if budget_res["within_budget"] else "inverse")
        c3.metric("Real prices", f"{verified:.2f} €", help="Live hotel price, official fares and OpenStreetMap fees.")
    c4.metric("Planned in", f"{result['duration_s']} s", help=f"{len(traces)} tool calls by {result['model']}")

    tab_plan, tab_map, tab_weather, tab_budget, tab_hood = st.tabs([
        ":material/event_note: Day plan", ":material/map: Map", ":material/partly_cloudy_day: Weather",
        ":material/payments: Budget", ":material/terminal: Under the hood"])

    with tab_plan:
        timetable, story = st.columns([2, 3], gap="medium")
        with timetable.container(border=True):
            st.markdown(f"**:material/schedule: Your timetable** · {result.get('pace', '')} pace")
            rows = "".join(
                f'<div class="tb-slot tb-slot-{item["kind"]}"><span class="tb-time">{item["time"]}</span>'
                f'<span class="tb-what"><span class="tb-kind">{"Visit" if item["kind"] == "place" else item["kind"].capitalize()}</span>'
                f'{html.escape(item["name"])}</span><span class="tb-price">'
                f'{"free" if not item["price"] else f"{item["price"]:.0f} €"}</span></div>'
                for item in result.get("schedule", []))
            st.markdown(f'<div class="tb-timeline">{rows}</div>', unsafe_allow_html=True)
            st.caption("Built by code from the places in your budget, following the pace.")
        with story.container(border=True):
            st.markdown("**:material/auto_stories: The plan**")
            st.markdown(result["text"])
        story.caption("Written by the local LLM from the tool results. The numbers in the Budget tab are the exact ones.")

    with tab_map:
        places = results_of(traces, "search_places")
        hotels = results_of(traces, "search_hotels")
        points = [{**p, "kind": "Place", "color": [3, 105, 161, 220]} for p in places if p.get("type") not in {"city", "administrative"}] + \
                 [{**h, "kind": "Hotel", "color": [234, 88, 12, 230]} for h in hotels]
        if points:
            df = pd.DataFrame(points)
            layer = pdk.Layer("ScatterplotLayer", df, get_position=["longitude", "latitude"], get_fill_color="color",
                              get_radius=60, radius_min_pixels=7, radius_max_pixels=14, pickable=True,
                              stroked=True, get_line_color=[255, 255, 255], line_width_min_pixels=2)
            view = pdk.ViewState(latitude=df["latitude"].mean(), longitude=df["longitude"].mean(), zoom=13)
            st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view, map_style="light",
                                     tooltip={"html": "<b>{name}</b><br/>{kind} · {type}"}), height=460)
            st.markdown(":blue-badge[:material/place: Places] :orange-badge[:material/hotel: Hotels] "
                        "· hover a point for its name")
            left, right = st.columns(2)
            if places:
                left.markdown("**Places found**")
                left.dataframe(pd.DataFrame(places)[["name", "type", "entry_fee"]], hide_index=True, width="stretch",
                               column_config={"entry_fee": st.column_config.NumberColumn("entry", format="%.2f €")})
            if hotels:
                right.markdown("**Hotels found**")
                hotels_df = pd.DataFrame(hotels)
                columns = [c for c in ["name", "stars", "price_per_night", "distance_km", "website"] if c in hotels_df]
                right.dataframe(hotels_df[columns], hide_index=True, width="stretch", column_config={
                    "website": st.column_config.LinkColumn(display_text="Open"),
                    "price_per_night": st.column_config.NumberColumn("night", format="%.0f €"),
                    "distance_km": st.column_config.NumberColumn("km", format="%.2f")})
        else:
            st.info("No places or hotels were searched for this plan.", icon=":material/info:")

    with tab_weather:
        days = {}
        for day in results_of(traces, "get_weather"):
            days.setdefault(day["date"], day)  # several calls return the same days: keep the first
        if days:
            for col, day in zip(st.columns(len(days)), days.values()):
                is_trip = day["date"] == trip["trip_date"]
                with col.container(border=True):
                    st.markdown(f"### :material/{weather_icon(day['weather_description'])}: "
                                f"{date.fromisoformat(day['date']):%a %d %b}")
                    st.write(day["weather_description"])
                    if is_trip:
                        st.badge("Your trip", icon=":material/flag:", color="orange")
                    st.metric("Temperature", f"{day['min_temp']:.0f}° / {day['max_temp']:.0f}°C")
                    st.metric("Chance of rain", f"{day['rain_probability']} %")
            if trip["trip_date"] not in days:
                st.warning("Your date is beyond the 3-day forecast: these are the next days instead.", icon=":material/info:")
        else:
            st.info("The agent did not check the weather.", icon=":material/info:")

    with tab_budget:
        if budget_res:
            available = budget_res.get("available_funds")
            if available:
                used = budget_res["total"] / available
                st.markdown(f"**{budget_res['total']:.2f} €** of your **{available:.2f} €** budget "
                            f"({used:.0%})")
                st.progress(min(used, 1.0))
            lines = pd.DataFrame(budget_res["lines"])
            lines["kind"] = lines["source"].map(source_kind)
            st.dataframe(lines[["category", "item", "amount", "kind", "source"]], hide_index=True, width="stretch",
                         column_config={
                             "category": st.column_config.TextColumn("Category"),
                             "item": st.column_config.TextColumn("Item", width="medium"),
                             "amount": st.column_config.NumberColumn("Price", format="%.2f €"),
                             "kind": st.column_config.TextColumn("Type"),
                             "source": st.column_config.TextColumn("Source", width="large"),
                         })
            verified = budget_res["total"] - budget_res["estimated_part"]
            st.caption(f"Computed by the calculate_budget tool, not by the LLM. {verified:.2f} € comes from live prices, "
                       f"official fares or OpenStreetMap; {budget_res['estimated_part']:.2f} € is estimated "
                       "(meals have no free price source).")
        else:
            st.info("The agent did not calculate a budget.", icon=":material/info:")

    with tab_hood:
        st.markdown("**Request sent to the agent** (built from your form)")
        st.code(result["request"], language=None, wrap_lines=True)
        st.markdown(f"**{len(traces)} tool calls**")
        for step, t in enumerate(traces, 1):
            icon = STEP_LABELS.get(t["tool"], ("build",))[0]
            with st.expander(f"Step {step} · {t['tool']}", icon=f":material/{icon}:"):
                st.markdown("**Parameters**")
                st.json(t["args"])
                st.markdown("**Result**")
                st.json(t["result"], expanded=False)

# ---------- How it works ----------
st.divider()
st.markdown("#### How it works")
how = st.columns(3, gap="medium")
for col, (icon, title, text) in zip(how, [
    ("public", "Real data", "Places and hotels come from OpenStreetMap, the weather from Open-Meteo, "
                            "and the 246 countries and 169,000 cities from GeoNames."),
    ("calculate", "An exact budget", "Computed by code, never by the AI: official transport fares, entry fees from "
                                     "OpenStreetMap and live hotel prices. Only meals are estimated."),
    ("memory", "A local AI", "A model running on your own computer with Ollama chooses the searches and writes "
                             "the schedule from their results. Nothing is sent to an AI service."),
]):
    with col.container(border=True):
        st.markdown(f"**:material/{icon}: {title}**")
        st.markdown(f'<p class="tb-how">{text}</p>', unsafe_allow_html=True)
