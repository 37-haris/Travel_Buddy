import asyncio
from server import mcp

async def main():
    print([t.name for t in await mcp.list_tools()])
    print(await mcp.call_tool("calculate_budget", {"city": "Paris", "country": "France", "places": ["Musée du Louvre", "Jardin du Luxembourg"], "hotel_stars": 4, "available_funds": 300}))
    print(await mcp.call_tool("search_places", {"query": "museum", "city": "Paris", "country": "France", "limit": 5}))
    print(await mcp.call_tool("calculate_distance", {"lat1": 48.8566, "lon1": 2.3522, "lat2": 51.5074, "lon2": -0.1278}))
    print(await mcp.call_tool("get_weather", {"latitude": 48.8566, "longitude": 2.3522}))
    print(await mcp.call_tool("search_hotels", {"latitude": 45.7640, "longitude": 4.8357, "radius_km": 1, "limit": 5}))

asyncio.run(main())
