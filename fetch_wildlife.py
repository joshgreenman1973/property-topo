#!/usr/bin/env python3
"""Add a wildlife profile to terrain_data.js from GBIF occurrence records
(citizen-science + museum data, mostly eBird/iNaturalist) within ~3 km."""
import json, urllib.request, urllib.parse, socket, time
socket.setdefaulttimeout(30)

def gj(url):
    return json.load(urllib.request.urlopen(
        urllib.request.Request(url, headers={'User-Agent': 'topo/1.0'}), timeout=30))

PTS = {"aquinnah": (-70.810771, 41.336566), "cornwall": (-74.0164057, 41.4200187)}
GROUPS = [("Birds", 212), ("Mammals", 359), ("Amphibians", 131), ("Reptiles", 358)]
R = 0.03  # ~3 km half-box

_vn = {}
def vname(key):
    if key in _vn:
        return _vn[key]
    sci, vn = "?", None
    try:
        d = gj(f"https://api.gbif.org/v1/species/{key}")
        sci = (d.get("canonicalName") or d.get("scientificName") or "?")
        vn = d.get("vernacularName")
        if not vn:
            for r in gj(f"https://api.gbif.org/v1/species/{key}/vernacularNames?limit=30").get("results", []):
                if r.get("language") == "eng":
                    vn = r["vernacularName"]; break
    except Exception:
        pass
    _vn[key] = (sci, vn)
    return sci, vn

txt = open("terrain_data.js").read()
data = json.loads(txt[txt.index('{'):txt.rstrip().rstrip(';').rindex('}') + 1])

for k, (lon, lat) in PTS.items():
    wkt = f"POLYGON(({lon-R} {lat-R},{lon+R} {lat-R},{lon+R} {lat+R},{lon-R} {lat+R},{lon-R} {lat-R}))"
    prof = {"radius_km": 3, "groups": []}
    for label, ckey in GROUPS:
        u = "https://api.gbif.org/v1/occurrence/search?" + urllib.parse.urlencode(
            {"geometry": wkt, "limit": 0, "classKey": ckey, "facet": "speciesKey", "facetLimit": 300})
        try:
            fs = gj(u)["facets"]
            counts = fs[0]["counts"] if fs else []
            ntot = gj("https://api.gbif.org/v1/occurrence/search?" + urllib.parse.urlencode(
                {"geometry": wkt, "limit": 0, "classKey": ckey})).get("count", 0)
            def clean(vn, sci):
                s = (vn or sci or "?").strip()
                low = s.lower()
                if "gull" in low and ("herring" in low or "smithsonian" in low):
                    return "American Herring Gull"
                return " ".join(w if (w.isupper() or w[:1].isupper()) else
                                (w[:1].upper() + w[1:]) for w in s.split())
            merged = {}  # display name -> {count, sci}
            for c in counts[:14]:
                sci, vn = vname(c["name"])
                disp = clean(vn, sci)
                e = merged.setdefault(disp, {"count": 0, "sci": sci})
                e["count"] += c["count"]
                time.sleep(0.05)
            top = [{"name": n, "sci": v["sci"], "count": v["count"]}
                   for n, v in sorted(merged.items(), key=lambda kv: -kv[1]["count"])][:8]
            prof["groups"].append({"label": label, "obs": ntot,
                                   "species": len(counts), "capped": len(counts) >= 300, "top": top})
            print(f"[{k}] {label}: {ntot} obs, {len(counts)} spp")
        except Exception as e:
            print(f"[{k}] {label} ERR {str(e)[:60]}")
    data[k]["wildlife"] = prof

with open("terrain_data.js", "w") as f:
    f.write("window.TERRAIN = " + json.dumps(data) + ";\n")
print("wrote terrain_data.js")
