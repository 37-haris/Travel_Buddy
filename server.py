"""Travel service - MCP server exposing 3 tools for travel planning and recommendations."""
import asyncio
import json
import os
import re
import unicodedata
from datetime import date, timedelta
from math import cos, radians
from pathlib import Path

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(Path(__file__).parent / ".env")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")  # optional: live hotel prices
CACHE_FILE = Path(__file__).parent / ".price_cache.json"


mcp = FastMCP("Travel Service")
HEADER = {"User-Agent": "Travel Buddy", "Accept-Language": "en"}  # English names when OpenStreetMap has them


WEATHER_CODE = {
    0: "Clear sky",
    1: "Mainly clear", 
    2: "Partly cloudy", 
    3: "Overcast", 
    45: "Fog", 
    48: "Depositing rime fog", 
    51: "Drizzle: Light", 
    53: "Drizzle: Moderate", 
    55: "Drizzle: Dense intensity", 
    56: "Freezing Drizzle: Light", 
    57: "Freezing Drizzle: Dense intensity", 
    61: "Rain: Slight", 
    63: "Rain: Moderate", 
    65: "Rain: Heavy intensity", 
    66: "Freezing Rain: Light", 
    67: "Freezing Rain: Heavy intensity", 
    71: "Snow fall: Slight", 
    73: "Snow fall: Moderate", 
    75: "Snow fall: Heavy intensity", 
    77: "Snow grains", 
    80: "Rain showers: Slight", 
    81: "Rain showers: Moderate", 
    82: "Rain showers: Violent", 
    85: "Snow showers slight", 
    86: "Snow showers heavy", 
    95: "Thunderstorm: Slight or moderate", 
    96: "Thunderstorm with slight hail", 
    99: "Thunderstorm with heavy hail"
}

@mcp.tool()
async def get_weather(latitude: float, longitude: float) -> list[dict]:
    """Get the weather forecast for today and the next 2 days (3 days in total) at the given latitude and longitude.
    Returns one entry per day: date, min/max temperature (C), rain probability (%), weather description.
    Get the latitude/longitude first with search_places(query='city center', ...).
    """
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": "temperature_2m_min,temperature_2m_max,precipitation_probability_max,weathercode",
        "timezone": "auto",
        "forecast_days": 3
    }

    r= httpx.get("https://api.open-meteo.com/v1/forecast", params=params, headers=HEADER, timeout=15)
    r.raise_for_status()
    d= r.json()["daily"]
    return [
        {
            "date": d["time"][i],
            "min_temp": d["temperature_2m_min"][i],
            "max_temp": d["temperature_2m_max"][i],
            "rain_probability": d["precipitation_probability_max"][i],
            "weather_description": WEATHER_CODE.get(d["weathercode"][i],
            "Unknown")}
        for i in range(len(d["time"]))]


@mcp.tool()
async def search_places(query: str, city: str, country: str, limit: int = 5) -> list[dict]:
    """Search tourist places (e.g. 'museum', 'park', 'restaurant') in a city using OpenStreetMap/Nominatim.
    Use query='city center' to get the coordinates of the city itself.
    Returns name, type, address, latitude, longitude and entry fee (EUR, with its source) for each place."""
    is_city = query.strip().lower() in {"city center", "city centre", city.strip().lower()}
    # "museum in Lyon" triggers Nominatim's category search; "museum, Lyon" only matches names
    attempts = [f"{city}, {country}"] if is_city else [f"{query} in {city}, {country}", f"{query}, {city}, {country}"]
    # Skip transport matches (e.g. a bus stop named "Museum")
    skip = {"railway", "highway", "public_transport", "aeroway"}
    places = []
    for q in attempts:
        params = {"q": q, "format": "json", "limit": limit * 3, "extratags": 1}  # extra results, some are filtered out
        r = httpx.get("https://nominatim.openstreetmap.org/search", params=params, headers=HEADER, timeout=15)
        r.raise_for_status()
        places = [p for p in r.json() if is_city or p.get("class") not in skip]
        if places:
            break
    return [
        {
            "name": place.get("name") or place.get("display_name", ""),
            "type": place.get("type", ""),
            "address": short_address(place.get("display_name", "")),
            "latitude": float(place.get("lat", 0)),
            "longitude": float(place.get("lon", 0)),
            "entry_fee": entry_fee(place)[0],
            "entry_fee_source": entry_fee(place)[1],
        }
        for place in places[:limit]
    ]


@mcp.tool()
async def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the distance in kilometers between two coordinates using the Haversine formula."""
    from math import radians, sin, cos, sqrt, atan2

    R = 6371.0  # Radius of the Earth in kilometers

    lat1_rad = radians(lat1)
    lon1_rad = radians(lon1)
    lat2_rad = radians(lat2)
    lon2_rad = radians(lon2)

    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad

    a = sin(dlat / 2)**2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    distance = R * c
    return distance

# Official public transport fares (operator websites, checked 2026-10). "day" = unlimited day pass, "single" = 1 trip.
TRANSPORT_FARES = {
    "paris": {"ticket": "Navigo Jour day pass", "price": 12.30, "source": "bonjour-ratp.fr (2026)"},
    "bordeaux": {"ticket": "TBM 24h ticket", "price": 6.50, "source": "infotbm.com (2026)"},
    "lyon": {"ticket": "TCL 24h ticket", "price": 6.70, "source": "tcl.fr fare (2024, may have risen)"},
    "marseille": {"ticket": "4 RTM single tickets x 1.60", "price": 6.40, "source": "rtm.fr (from 2026-11-01)"},
}

# Fallback when there is no SERPAPI_KEY or no live price: fixed reference values (EUR), labelled as estimates.
BIG_CITIES = {"paris"}
MEAL_PRICES = {"breakfast": 6, "lunch": 16, "dinner": 26}
MEAL_PRICES_BIG_CITY = {"breakfast": 8, "lunch": 20, "dinner": 32}
HOTEL_NIGHT = {1: 55, 2: 75, 3: 100, 4: 150, 5: 300}
HOTEL_NIGHT_BIG_CITY = {1: 80, 2: 110, 3: 160, 4: 250, 5: 500}
DEFAULT_ENTRY_FEE = 12  # a paid place whose fee isn't on OpenStreetMap
DEFAULT_TRANSPORT = 7  # a city with no fare in TRANSPORT_FARES
FREE_TYPES = {"park", "garden", "square", "viewpoint", "place_of_worship", "church", "cathedral", "fountain",
              "pedestrian", "monument", "memorial", "artwork", "beach", "city", "town", "administrative"}
FOOD_TYPES = {"restaurant", "fast_food", "cafe", "bar", "pub", "food_court", "bistro", "ice_cream"}


def short_address(display_name: str) -> str:
    """'Le Rectangle, Place Bellecour, Bellecour, Lyon 2e, Lyon, Métropole de Lyon, Rhône, ...' -> first 3 parts.
    Full OpenStreetMap addresses fill the LLM context (and the free Groq token budget) for nothing."""
    return ", ".join(display_name.split(", ")[:3])


def normalize(name: str) -> str:
    """'Lyon ', 'LYON' -> 'lyon'; 'Montréal' -> 'montreal'."""
    return unicodedata.normalize("NFKD", name.strip().lower()).encode("ascii", "ignore").decode()


def entry_fee(place: dict) -> tuple[float, str]:
    """Entry fee of an OpenStreetMap result, and where the number comes from."""
    extra = place.get("extratags") or {}
    charge = re.search(r"\d+(?:[.,]\d+)?", extra.get("charge", ""))
    if charge:
        return float(charge.group().replace(",", ".")), "OpenStreetMap (charge tag)"
    if place.get("type") in FOOD_TYPES:
        return 0.0, "no entry fee (meal counted in food)"
    if extra.get("fee") == "no":
        return 0.0, "OpenStreetMap (fee=no)"
    if extra.get("fee") != "yes" and place.get("type") in FREE_TYPES:
        return 0.0, f"free ({place.get('type')}, estimate)"
    return float(DEFAULT_ENTRY_FEE), "estimate (fee not on OpenStreetMap)"


def serpapi(params: dict) -> dict:
    """Call SerpApi (Google results as JSON). Free key: https://serpapi.com, 250 searches/month.
    Answers are cached on disk for the day, so the same lookup never spends a second search."""
    cache_key = f"{date.today()} {json.dumps(params, sort_keys=True, ensure_ascii=False)}"
    cache = json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}
    if cache_key not in cache:
        r = httpx.get("https://serpapi.com/search.json", params={**params, "api_key": SERPAPI_KEY, "hl": "fr", "gl": "fr"}, timeout=30)
        r.raise_for_status()
        cache = {k: v for k, v in cache.items() if k.startswith(str(date.today()))}  # drop older days
        cache[cache_key] = r.json()
        CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False))
    return cache[cache_key]


def trip_day(trip_date: str | None) -> date:
    """The trip date, or tomorrow if missing, invalid or in the past (small models invent dates)."""
    try:
        day = date.fromisoformat(trip_date or "")
    except ValueError:
        return date.today() + timedelta(days=1)
    return day if day >= date.today() else date.today() + timedelta(days=1)


def hotel_search_params(q: str, check_in: date) -> dict:
    return {"engine": "google_hotels", "q": q, "currency": "EUR", "adults": 1,
            "check_in_date": check_in.isoformat(), "check_out_date": (check_in + timedelta(days=1)).isoformat()}


def live_hotel_price(hotel: str, city: str, check_in: date) -> float | None:
    """Real price of one night at this hotel on this date (lowest offer on Google Hotels, EUR)."""
    # Already seen today in a search_hotels result for that date? Reuse it: same price, no extra search
    if CACHE_FILE.exists():
        for key, data in json.loads(CACHE_FILE.read_text()).items():
            if check_in.isoformat() in key and '"google_hotels"' in key:
                for prop in data.get("properties", []):
                    if normalize(prop.get("name", "")) == normalize(hotel):
                        return (prop.get("rate_per_night") or {}).get("extracted_lowest")
    data = serpapi(hotel_search_params(f"{hotel} {city}", check_in))
    # An exact hotel name returns that hotel directly; otherwise a list of properties, best match first
    prop = data if "rate_per_night" in data else next(iter(data.get("properties", [])), {})
    return (prop.get("rate_per_night") or {}).get("extracted_lowest")


@mcp.tool()
async def calculate_budget(city: str, country: str, places: list[str], restaurants: list[str] | None = None,
                           hotel_name: str | None = None, hotel_stars: int | None = None, needs_hotel: bool = False,
                           trip_date: str | None = None, available_funds: float | None = None) -> dict:
    """Compute the real cost of the day in EUR. Do NOT pass any price: the tool finds them itself.
    - places: names of the places the user will visit (from search_places); entry fees are looked up on OpenStreetMap.
    - restaurants: names of the lunch and dinner restaurants (from search_places).
    - hotel_name / hotel_stars: the hotel you recommend (from search_hotels), if the user needs a night (needs_hotel=true).
    - trip_date: YYYY-MM-DD, only if the user gave an exact date (default: tomorrow). Hotel prices depend on it.
    - available_funds: ALWAYS pass the user's budget if they gave one (e.g. "my budget is 200 euros" -> 200);
      the tool says whether the plan fits and how much is left.
    Call it only once. Returns one line per cost with its source (live price, official fare, OpenStreetMap or estimate) and the totals."""
    key = normalize(city)
    big = key in BIG_CITIES
    day = trip_day(trip_date)
    lines = []

    def live(lookup, *args):
        """Live price from SerpApi, None if no key, not found or the request failed (the caller then estimates)."""
        if not SERPAPI_KEY:
            return None
        try:
            return lookup(*args)
        except (httpx.HTTPError, ValueError):
            return None

    fare = TRANSPORT_FARES.get(key)
    if fare:
        lines.append({"category": "transport", "item": fare["ticket"], "amount": fare["price"], "source": f"official fare, {fare['source']}"})
    else:
        lines.append({"category": "transport", "item": "public transport for the day", "amount": DEFAULT_TRANSPORT, "source": "estimate (no fare for this city)"})

    restaurants = restaurants or []
    for i, name in enumerate([p for p in places if p not in restaurants][:6]):  # Nominatim allows 1 request per second
        if i:
            await asyncio.sleep(1)
        params = {"q": f"{name}, {city}, {country}", "format": "json", "limit": 1, "extratags": 1}
        r = httpx.get("https://nominatim.openstreetmap.org/search", params=params, headers=HEADER, timeout=15)
        found = r.json() if r.status_code == 200 else []
        amount, source = entry_fee(found[0]) if found else (float(DEFAULT_ENTRY_FEE), "estimate (place not found)")
        lines.append({"category": "activities", "item": name, "amount": amount, "source": source})

    reference = MEAL_PRICES_BIG_CITY if big else MEAL_PRICES
    # Google Maps has no price range for French restaurants (checked with SerpApi), so meals stay estimates
    for meal, restaurant in zip(["lunch", "dinner"], restaurants + [None, None]):
        item = f"{meal} at {restaurant}" if restaurant else meal
        lines.append({"category": "food", "item": item, "amount": reference[meal], "source": "estimate (reference meal price)"})

    if needs_hotel or hotel_name or hotel_stars:
        price = live(live_hotel_price, hotel_name, city, day) if hotel_name else None
        if price:
            lines.append({"category": "accommodation", "item": f"1 night at {hotel_name} on {day}", "amount": price,
                          "source": f"live price, Google Hotels ({date.today()})"})
        else:
            stars = min(max(int(hotel_stars or 3), 1), 5)
            night = (HOTEL_NIGHT_BIG_CITY if big else HOTEL_NIGHT)[stars]
            lines.append({"category": "accommodation", "item": f"1 night, {stars}-star hotel" + ("" if hotel_stars else " (stars unknown)"),
                          "amount": night, "source": "estimate (reference price by stars)"})

    result = {c: round(sum(l["amount"] for l in lines if l["category"] == c), 2)
              for c in ["transport", "activities", "food", "accommodation"]}
    result["total"] = round(sum(l["amount"] for l in lines), 2)
    result["estimated_part"] = round(sum(l["amount"] for l in lines if "estimate" in l["source"]), 2)
    result["live_prices"] = bool(SERPAPI_KEY)
    result["lines"] = lines

    if available_funds is not None:
        result["available_funds"] = available_funds
        result["remaining_funds"] = round(available_funds - result["total"], 2)
        result["within_budget"] = result["total"] <= available_funds
    # Small models re-call the tool or redo the maths: tell them it's done and give the exact numbers to quote
    result["next_step"] = (f"Budget done, do not call calculate_budget again. If you mention it, the total is exactly {result['total']} EUR"
                           + (f" and {result['remaining_funds']} EUR is left." if available_funds is not None else "."))
    return result

async def google_hotels(latitude, longitude, city, near, max_price, stars, check_in) -> list[dict]:
    """Real hotels with live prices from one Google Hotels search, closest to the point first."""
    params = hotel_search_params(f"hotels near {near}, {city}" if near else f"hotels in {city} city center", check_in)
    if max_price:
        params["max_price"] = int(max_price)
    if stars:
        params["hotel_class"] = str(min(max(int(stars), 2), 5))  # Google Hotels filters 2 to 5 stars
    hotels = []
    for prop in serpapi(params).get("properties", []):
        gps, price = prop.get("gps_coordinates") or {}, (prop.get("rate_per_night") or {}).get("extracted_lowest")
        if not gps or not price:
            continue
        distance = round(await calculate_distance(latitude, longitude, gps["latitude"], gps["longitude"]), 2)
        if distance > 10:  # another town with the same name, or the search drifted
            continue
        hotels.append({
            "name": prop["name"], "type": prop.get("type", "hotel"), "stars": prop.get("extracted_hotel_class"),
            "price_per_night": price, "price_source": f"live, Google Hotels ({check_in})",
            "rating": prop.get("overall_rating"), "address": (prop.get("description") or "")[:100], "website": prop.get("link"),
            "latitude": gps["latitude"], "longitude": gps["longitude"], "distance_km": distance,
        })
    # Cheapest first among those within 1.5 km (the agent tends to pick the first one), then the others by distance
    return sorted(hotels, key=lambda h: (h["distance_km"] > 1.5, h["price_per_night"] if h["distance_km"] <= 1.5 else h["distance_km"]))


@mcp.tool()
async def search_hotels(latitude: float, longitude: float, city: str = "", near: str = "", max_price_per_night: float | None = None,
                        stars: int | None = None, trip_date: str | None = None, radius_km: float = 2, limit: int = 5) -> list[dict]:
    """Find hotels around a point: the cheapest close ones first.
    Pass the coordinates of the city center or of a place the user wants to stay near (from search_places),
    the city, the place name as near (e.g. 'Eiffel Tower'), the max price per night and the stars the user asked for.
    With live prices on, returns real hotels from Google Hotels with their price_per_night for trip_date (default tomorrow);
    otherwise OpenStreetMap hotels without prices. Each result: name, type, stars, price_per_night, address, website,
    latitude, longitude, distance_km. Pass the hotel you recommend to calculate_budget (hotel_name, hotel_stars)."""
    if SERPAPI_KEY and city:
        try:
            hotels = await google_hotels(latitude, longitude, city, near, max_price_per_night, stars, trip_day(trip_date))
            if hotels:
                return hotels[:limit]
        except (httpx.HTTPError, ValueError):
            pass  # fall back to OpenStreetMap
    # Box of +/- radius_km around the point (1 degree of latitude ~ 111 km; longitude degrees shrink with latitude)
    dlat = radius_km / 111
    dlon = radius_km / (111 * cos(radians(latitude)))
    params = {
        "q": "hotel",
        "format": "json",
        "limit": 50,  # Nominatim doesn't sort by distance, so fetch many and sort here
        "viewbox": f"{longitude - dlon},{latitude + dlat},{longitude + dlon},{latitude - dlat}",
        "bounded": 1,
        "extratags": 1  # contains "stars" and "website"
    }
    r = httpx.get("https://nominatim.openstreetmap.org/search", params=params, headers=HEADER, timeout=15)
    r.raise_for_status()
    hotels = []
    for place in r.json():
        if place.get("class") != "tourism" or place.get("type") not in {"hotel", "hostel", "guest_house"}:
            continue
        extra = place.get("extratags") or {}
        lat, lon = float(place["lat"]), float(place["lon"])
        hotels.append({
            "name": place.get("name") or place.get("display_name", ""),
            "type": place["type"],
            "stars": extra.get("stars"),
            "address": short_address(place.get("display_name", "")),
            "website": extra.get("website") or extra.get("contact:website"),
            "latitude": lat,
            "longitude": lon,
            "distance_km": round(await calculate_distance(latitude, longitude, lat, lon), 2)
        })
    hotels = [h for h in hotels if h["distance_km"] <= radius_km]  # the box corners are further than radius_km
    return sorted(hotels, key=lambda h: h["distance_km"])[:limit]


if __name__ == "__main__":
    mcp.run()

    