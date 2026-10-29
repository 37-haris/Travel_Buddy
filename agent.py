"""Travel Buddy - LangChain agent (local Ollama LLM) using the Travel Services MCP tools."""

import asyncio
import json
import sys
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_ollama import ChatOllama

MODEL = "qwen2.5:7b"

SERVER_PATH = Path(__file__).parent / "server.py"

SYSTEM_PROMPT = """You are Travel Buddy, a helpful travel planning assistant.
Always use the provided tools to get places, coordinates, weather, distances and budgets; never invent them.

How to work:
- Call the tools directly, one at a time, and wait for each result before the next call.
- Never write a tool call as text and never use placeholders like <latitude>: use the real values returned by earlier tools.
- To get a city's coordinates, call search_places with query='city center', then pass those coordinates to get_weather.
- For distances, use the latitude/longitude returned by search_places for each place.
- If the user needs a place to stay, call search_hotels with the city center coordinates (or near a place they want to visit).
- Search one kind of place per call (query='museum', then query='restaurant'), never several kinds at once.
- Finally call calculate_budget once with the city, the names of the places in your plan and of the lunch and dinner
  restaurants (exactly as returned by search_places), hotel_name and hotel_stars if the user needs a place to stay,
  trip_date only if the user gave an exact date, and the user's budget as available_funds.
  Never pass prices: the tool finds them itself.
- Never announce the next step ("Next, let's..."): call the tool instead. Only write text once every tool result is in.

When all tool results are in, give the final day plan (morning, afternoon, evening: places, weather, distances).
Only recommend places returned by search_places and hotels returned by search_hotels.
Do not write prices or a budget: the exact budget table is added automatically after your answer.
Answer concisely in the user's language."""


def parse_tool_result(content):
    """MCP results arrive as a list of text blocks (one per list item): turn them back into Python data."""
    if isinstance(content, str):
        content = [content]
    items = []
    for block in content:
        text = block.get("text", "") if isinstance(block, dict) else str(block)
        try:
            items.append(json.loads(text))
        except json.JSONDecodeError:
            items.append(text)
    if len(items) == 1:
        return items[0]
    return items


def get_traces(messages):
    """Item 7: tools called, parameters sent and results returned, in order."""
    results = {m.tool_call_id: parse_tool_result(m.content) for m in messages if isinstance(m, ToolMessage)}
    return [
        {"tool": call["name"], "args": call["args"], "result": results.get(call["id"])}
        for msg in messages if isinstance(msg, AIMessage)
        for call in msg.tool_calls
    ]


def final_budget(traces):
    """Result of the last calculate_budget call (the final budget), or None."""
    budgets = [t["result"] for t in traces if t["tool"] == "calculate_budget" and isinstance(t["result"], dict)]
    return budgets[-1] if budgets else None


def format_budget(budget):
    """Markdown budget table built from the tool result, so the numbers shown are exactly the computed ones."""
    if not budget:
        return "\n\n---\n**Budget:** not calculated."
    rows = "\n".join(f"| {l['category']} | {l['item']} | {l['amount']:.2f} € | {l['source']} |" for l in budget["lines"])
    text = (f"\n\n---\n### 💶 Budget\n| Category | Item | Price | Source |\n|---|---|---:|---|\n{rows}\n"
            f"| **Total** | | **{budget['total']:.2f} €** | {budget['estimated_part']:.2f} € of it is estimated |\n")
    if "remaining_funds" in budget:
        verdict = "✅ within budget" if budget["within_budget"] else "❌ over budget"
        text += f"\nYour budget: {budget['available_funds']:.2f} € → remaining **{budget['remaining_funds']:.2f} €** ({verdict})"
    return text


def final_plan(messages):
    """The LLM's day plan followed by the budget table computed by calculate_budget."""
    return messages[-1].content + format_budget(final_budget(get_traces(messages)))


def print_traces(messages):
    print("\n" + "=" * 60 + "\nEXECUTION TRACES\n" + "=" * 60)
    traces = get_traces(messages)
    for step, trace in enumerate(traces, 1):
        result = json.dumps(trace["result"], ensure_ascii=False)
        short = result if len(result) < 300 else result[:300] + " ...[truncated]"
        print(f"\n[Step {step}] TOOL CALLED : {trace['tool']}")
        print(f"           PARAMETERS  : {json.dumps(trace['args'], ensure_ascii=False)}")
        print(f"           RESULT      : {short}")
    print(f"\nTotal tool calls: {len(traces)}")


async def build_agent():
    # Item 3: connect the MCP server to LangChain (launched as a subprocess over stdio)
    client = MultiServerMCPClient({
        "travel_services": {
            "command": sys.executable,
            "args": [str(SERVER_PATH)],
            "transport": "stdio",
        }
    })
    tools = await client.get_tools()
    print("MCP tools loaded:", [t.name for t in tools])

    # Item 4: local LLM via Ollama
    # temperature=0 (greedy) makes small models loop and trip Ollama's "token repeat limit";
    # a little randomness + repeat_penalty avoids it, and a bigger context fits all tool results.
    llm = ChatOllama(
        model=MODEL,
        temperature=0.2,
        repeat_penalty=1.15,
        num_ctx=8192,
        num_predict=1024,
    )

    # Item 5: the agent picks which tool to call, based on the request
    return create_agent(llm, tools, system_prompt=SYSTEM_PROMPT)


# Interest chosen in the UI -> query for search_places ("castle" finds castles, palaces and forts; "monument" mostly plaques)
INTEREST_QUERIES = {"Museums": "museum", "Food": "restaurant", "Parks": "park", "History": "castle", "Art": "art gallery",
                    "Shopping": "shopping", "Nightlife": "bar", "Cafés": "cafe", "Churches": "church", "Temples": "temple", "Viewpoints": "viewpoint"}
# Each pace is a timetable: "place" slots are filled with the visits, in order
PACES = {
    "Relaxed": [("10:00", "place"), ("12:30", "lunch"), ("15:00", "place"), ("19:30", "dinner")],
    "Balanced": [("09:30", "place"), ("11:30", "place"), ("13:00", "lunch"), ("15:00", "place"), ("19:30", "dinner")],
    "Packed": [("08:30", "place"), ("10:30", "place"), ("12:30", "lunch"), ("14:00", "place"), ("16:00", "place"),
               ("18:00", "place"), ("20:00", "dinner")],
}


def places_needed(pace):
    return sum(kind == "place" for _, kind in PACES.get(pace, PACES["Balanced"]))


def visits(budget):
    """The places visited in a calculate_budget result (not the restaurants)."""
    return [l for l in (budget or {}).get("lines", []) if l["category"] == "activities" and "meal" not in l["source"]]


def day_schedule(pace, budget):
    """The pace's timetable filled with the visits and restaurants of the budget: what the user sees, built by code."""
    places = visits(budget)
    meals = {l["item"].split(" at ")[0]: l for l in (budget or {}).get("lines", []) if l["category"] == "food"}
    schedule = []
    for time, kind in PACES.get(pace, PACES["Balanced"]):
        if kind == "place" and places:
            line = places.pop(0)
            schedule.append({"time": time, "kind": "place", "name": line["item"], "price": line["amount"]})
        elif kind in meals:
            line = meals[kind]
            name = line["item"].split(" at ", 1)[1] if " at " in line["item"] else kind.capitalize()
            schedule.append({"time": time, "kind": kind, "name": name, "price": line["amount"]})
    return schedule


def build_request(city, country, trip_date, interests, budget, pace="Balanced", needs_hotel=False,
                  hotel_stars=None, stay_near="", notes=""):
    """Turn the form fields into one precise request, so the agent doesn't have to guess anything."""
    queries = [INTEREST_QUERIES.get(i, i.lower()) for i in interests] or ["tourist attraction"]
    lines = [
        f"Plan a day in {city}, {country} on {trip_date} (pass trip_date='{trip_date}' to calculate_budget).",
        f"Search places with these queries, one call each: {', '.join(queries)}. Also search 'restaurant' for lunch and dinner.",
        f"Pace: {pace}. Choose exactly {places_needed(pace)} places to visit (not restaurants) and pass exactly those "
        f"{places_needed(pace)} names as places to calculate_budget. Follow this timetable in the plan: "
        + "; ".join(f"{time} {kind}" for time, kind in PACES.get(pace, PACES["Balanced"])) + ".",
        f"My budget is {budget} euros (pass available_funds={budget}).",
    ]
    if needs_hotel:
        # Keep ~60 EUR for transport, entries and meals: the rest is the most a night can cost
        cap = max(round(float(budget) - 60), 40)
        where = f"near {stay_near} (search_places for '{stay_near}' first and use its coordinates)" if stay_near else "near the city center"
        args = f"city='{city}', near='{stay_near}', max_price_per_night={cap}, trip_date='{trip_date}'"
        if hotel_stars:
            args += f", stars={hotel_stars}"
        lines.append(f"I need a hotel for the night {where}. Call search_hotels with {args}. "
                     "Recommend one hotel it returns, and pass its exact name as hotel_name and its stars as hotel_stars to calculate_budget.")
    else:
        lines.append("I don't need a hotel.")
    if notes.strip():
        lines.append(f"Also: {notes.strip()}")
    return "\n".join(lines)


async def run_agent(agent, request, pace=None):
    """Run the agent and yield events as they happen: each tool call, then the full messages at the end.
    With a pace, also checks that the budget has the right number of places for it."""
    messages = [HumanMessage(request)]
    pace_fixed = False
    for attempt in range(4):
        async for update in agent.astream({"messages": messages}, stream_mode="updates"):
            for node in update.values():
                for msg in (node or {}).get("messages", []):
                    messages.append(msg)
                    if isinstance(msg, AIMessage):
                        for call in msg.tool_calls:
                            yield {"type": "tool", "tool": call["name"], "args": call["args"]}
        # Small models sometimes stop with "Next, let's calculate the budget..." instead of calling the tool:
        # the agent sees no tool call and ends. Nudge it to continue until the weather and the budget are in.
        traces = get_traces(messages)
        missing = {"get_weather", "calculate_budget"} - {t["tool"] for t in traces}
        if attempt == 3:
            break
        if missing:
            messages.append(HumanMessage(f"Continue: call {' and '.join(sorted(missing))} now (real tool calls), then give the final day plan."))
            continue
        # The pace is a number of places: if the budget doesn't have it, ask once more with the exact count.
        # Only once: each retry costs a full model run, and a place short is better than a 5-minute wait.
        planned, needed = len(visits(final_budget(traces))), places_needed(pace) if pace else None
        if not needed or planned == needed or pace_fixed:
            break
        pace_fixed = True
        yield {"type": "fix", "detail": f"Adjusting the plan to {needed} places ({pace} pace)"}
        messages.append(HumanMessage(
            f"The {pace} pace needs exactly {needed} places to visit, but calculate_budget got {planned}. "
            f"Restaurants don't count, they go in restaurants. Pick exactly {needed} museums, parks or sights from the "
            f"search_places results, searching more if needed, "
            f"call calculate_budget again with those {needed} places, then rewrite the day plan following the timetable."))
    yield {"type": "done", "messages": messages}


async def plan_trip(agent, request):
    """Run the agent on a request and return all the messages (the last one is the day plan)."""
    async for event in run_agent(agent, request):
        if event["type"] == "done":
            return event["messages"]


async def main():
    agent = await build_agent()
    request = input("\nWhere do you want to go? > ").strip() or (
        "Plan me a day in Lyon tomorrow. I love museums and good food. My budget is 80 euros."
    )
    messages = await plan_trip(agent, request)

    print_traces(messages)
    print("\n" + "=" * 60 + "\nYOUR DAY PLAN\n" + "=" * 60)
    print(final_plan(messages))


if __name__ == "__main__":
    asyncio.run(main())
