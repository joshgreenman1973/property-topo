#!/usr/bin/env python3
"""Add watershed (USGS WBD) + EPA radon zone (county) to terrain_data.js."""
import json, urllib.request, urllib.parse, socket
socket.setdefaulttimeout(30)

def q(url, p):
    return json.load(urllib.request.urlopen(urllib.request.Request(
        url + "?" + urllib.parse.urlencode(p), headers={'User-Agent': 't/1.0'}), timeout=30))

PTS = {"aquinnah": (-70.810771, 41.336566), "cornwall": (-74.0164057, 41.4200187)}
DRAINS = {"aquinnah": "Vineyard Sound & the Atlantic", "cornwall": "the Hudson River via Moodna Creek"}
# EPA Map of Radon Zones (county-level predicted indoor average):
RADON = {"aquinnah": (3, "Zone 3 — lowest predicted (< 2 pCi/L avg)"),
         "cornwall": (1, "Zone 1 — highest predicted (> 4 pCi/L avg)")}
WBD = "https://hydro.nationalmap.gov/arcgis/rest/services/wbd/MapServer"

txt = open("terrain_data.js").read()
data = json.loads(txt[txt.index('{'):txt.rstrip().rstrip(';').rindex('}') + 1])

for k, (lon, lat) in PTS.items():
    names = {}
    for lid, key in [(6, "sub"), (5, "ws"), (4, "basin")]:
        r = q(WBD + f"/{lid}/query", {"geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint",
              "inSR": "4326", "spatialRel": "esriSpatialRelIntersects", "outFields": "*",
              "returnGeometry": "false", "f": "json"})
        fs = r.get("features", [])
        if fs:
            a = fs[0]["attributes"]
            names[key] = a.get("NAME") or a.get("Name") or a.get("name")
    rz, rdesc = RADON[k]
    data[k]["env"] = {
        "watershed": names.get("ws"), "subwatershed": names.get("sub"),
        "drains_to": DRAINS[k], "radon_zone": rz, "radon_desc": rdesc,
    }
    print(f"[{k}] watershed {names.get('ws')} -> drains to {DRAINS[k]}; radon Zone {rz}")

with open("terrain_data.js", "w") as f:
    f.write("window.TERRAIN = " + json.dumps(data) + ";\n")
print("wrote terrain_data.js")
