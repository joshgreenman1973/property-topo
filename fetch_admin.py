#!/usr/bin/env python3
"""Add administrative geography (census tract, county, local area) to terrain_data.js."""
import json, urllib.request, socket
socket.setdefaulttimeout(30)

def gj(url):
    return json.load(urllib.request.urlopen(
        urllib.request.Request(url, headers={'User-Agent': 't/1.0'}), timeout=30))

PTS = {"aquinnah": (-70.810771, 41.336566), "cornwall": (-74.0164057, 41.4200187)}
ST = {"25": "MA", "36": "NY"}

txt = open("terrain_data.js").read()
data = json.loads(txt[txt.index('{'):txt.rstrip().rstrip(';').rindex('}') + 1])

for k, (lon, lat) in PTS.items():
    u = (f"https://geocoding.geo.census.gov/geocoder/geographies/coordinates?x={lon}&y={lat}"
         "&benchmark=Public_AR_Current&vintage=Current_Current&format=json&layers=all")
    g = gj(u)["result"]["geographies"]
    def first(layer):
        return g[layer][0] if g.get(layer) else None
    tract = first("Census Tracts")
    county = first("Counties")
    bg = first("Census Block Groups")
    place = first("Incorporated Places")
    sub = first("County Subdivisions")
    st = ST.get((county["GEOID"][:2] if county else ""), "")
    # local "neighborhood-equivalent": incorporated place (village) if any, else town subdivision
    area = place or sub
    area_name = (area["NAME"] if area else "").strip()
    area_label = "Village" if (place and "village" in area_name.lower()) else "Town"
    admin = {
        "tract": tract["NAME"] if tract else None,
        "tract_geoid": tract["GEOID"] if tract else None,
        "block_group": bg["BASENAME"] if bg else None,
        "county": (f"{county['NAME']}, {st}" if county else None),
        "area": area_name,
        "area_label": area_label,
    }
    data[k]["admin"] = admin
    print(f"[{k}] {admin['tract']} · BG {admin['block_group']} · {admin['county']} · {admin['area_label']}: {admin['area']}")

with open("terrain_data.js", "w") as f:
    f.write("window.TERRAIN = " + json.dumps(data) + ";\n")
print("wrote terrain_data.js")
