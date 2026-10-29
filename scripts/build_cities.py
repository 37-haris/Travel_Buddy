"""Build data/cities.json.gz (every country -> its cities, biggest first) from the free GeoNames dumps.

Download from https://download.geonames.org/export/dump/ : cities1000.zip (unzip it), countryInfo.txt, admin1CodesASCII.txt
Run: python scripts/build_cities.py <folder with the 3 files>
"""

import csv
import gzip
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

src = Path(sys.argv[1])
out = Path(__file__).parent.parent / "data" / "cities.json.gz"
csv.field_size_limit(10**7)


def rows(name):
    with open(src / name, encoding="utf-8") as f:
        yield from csv.reader((line for line in f if not line.startswith("#")), delimiter="\t", quoting=csv.QUOTE_NONE)


countries = {r[0]: r[4] for r in rows("countryInfo.txt")}  # "FR" -> "France"
regions = {r[0]: r[1] for r in rows("admin1CodesASCII.txt")}  # "FR.11" -> "Île-de-France"

cities = defaultdict(list)  # country name -> [(population, city, region)]
for r in rows("cities1000.txt"):
    name, code, admin1, population = r[1], r[8], r[10], int(r[14] or 0)
    if code in countries:
        cities[countries[code]].append((population, name, regions.get(f"{code}.{admin1}", "")))

result = {}
for country, items in sorted(cities.items()):
    items.sort(key=lambda c: (-c[0], c[1]))
    seen = Counter(name for _, name, _ in items)
    # Same name twice in a country (several Saint-Denis): add the region so the user picks the right one
    labels = [f"{name} ({region})" if seen[name] > 1 and region else name for _, name, region in items]
    result[country] = list(dict.fromkeys(labels))  # drop exact duplicates, keep the order

out.parent.mkdir(exist_ok=True)
with gzip.open(out, "wt", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
print(f"{len(result)} countries, {sum(map(len, result.values()))} cities -> {out} ({out.stat().st_size // 1024} KB)")
