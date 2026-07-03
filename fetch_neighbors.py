#!/usr/bin/env python3
"""Add adjoining-parcel owners to terrain_data.js.

Queries each state's assessor parcel service for parcels intersecting the
property polygon (i.e., sharing a boundary), captures owner / address / acreage
and boundary geometry in mesh coords.
"""
import json, urllib.request, urllib.parse
from pyproj import Transformer

def q(url, params):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(params).encode(),
                                 headers={'User-Agent': 't/1.0'})
    return json.load(urllib.request.urlopen(req, timeout=90))

MA_GEO = "https://arcgisserver.digital.mass.gov/arcgisserver/rest/services/AGOL/MassachusettsPropertyTaxParcels/FeatureServer/1/query"
MA_TAB = "https://arcgisserver.digital.mass.gov/arcgisserver/rest/services/AGOL/MassachusettsPropertyTaxParcels/FeatureServer/4/query"
NY_GEO = "https://gisservices.its.ny.gov/arcgis/rest/services/NYS_Tax_Parcels_Public/FeatureServer/1/query"

txt = open("terrain_data.js").read()
data = json.loads(txt[txt.index('{'):txt.rstrip().rstrip(';').rindex('}') + 1])

EPSG = {"aquinnah": 32619, "cornwall": 32618}
SELF = {"aquinnah": "M_257897_787708", "cornwall": "124-1-16.1"}

for k, d in data.items():
    epsg = EPSG[k]
    fwd = Transformer.from_crs(4326, epsg, always_xy=True)
    lon, lat = d["center_lonlat"]
    cE, cN = fwd.transform(lon, lat)
    outer_ll = max(d["poly_lonlat"], key=len)
    geo = json.dumps({"rings": [outer_ll], "spatialReference": {"wkid": 4326}})
    base = {"geometry": geo, "geometryType": "esriGeometryPolygon", "inSR": "4326",
            "outSR": "4326", "spatialRel": "esriSpatialRelIntersects",
            "returnGeometry": "true", "f": "json"}
    neighbors = []
    if k == "aquinnah":
        r = q(MA_GEO, {**base, "outFields": "LOC_ID"})
        locs = [f for f in r.get("features", []) if f["attributes"]["LOC_ID"] != SELF[k]]
        ids = [f["attributes"]["LOC_ID"] for f in locs if f["attributes"].get("LOC_ID")]
        att = {}
        if ids:
            where = "LOC_ID IN (" + ",".join(f"'{i}'" for i in ids) + ")"
            t = q(MA_TAB, {"where": where, "outFields": "LOC_ID,OWNER1,SITE_ADDR,LOT_SIZE",
                           "returnGeometry": "false", "f": "json"})
            for f in t.get("features", []):
                a = f["attributes"]; att[a["LOC_ID"]] = a
        for f in locs:
            lid = f["attributes"]["LOC_ID"]; a = att.get(lid, {})
            neighbors.append({
                "owner": (a.get("OWNER1") or "unknown").title(),
                "addr": (a.get("SITE_ADDR") or "").title(),
                "acres": a.get("LOT_SIZE"),
                "rings_ll": f["geometry"]["rings"],
            })
    else:
        r = q(NY_GEO, {**base, "outFields": "PRINT_KEY,PRIMARY_OWNER,PARCEL_ADDR,ACRES"})
        for f in r.get("features", []):
            a = f["attributes"]
            if a.get("PRINT_KEY") == SELF[k]:
                continue
            neighbors.append({
                "owner": (a.get("PRIMARY_OWNER") or "unknown").title(),
                "addr": (a.get("PARCEL_ADDR") or "").title(),
                "acres": a.get("ACRES"),
                "rings_ll": f["geometry"]["rings"],
            })
    # to mesh coords
    for nb in neighbors:
        rings = []
        for ring in nb.pop("rings_ll"):
            pts = []
            for lo, la in ring:
                E, Nn = fwd.transform(lo, la)
                pts.append([round(E - cE, 1), round(-(Nn - cN), 1)])
            rings.append(pts)
        nb["rings"] = rings
    d["neighbors"] = neighbors
    print(f"[{k}] {len(neighbors)} adjoining parcels:")
    for nb in neighbors:
        print(f"    {nb['owner']} | {nb['addr'] or '(no address)'} | {nb['acres']} ac")

with open("terrain_data.js", "w") as f:
    f.write("window.TERRAIN = " + json.dumps(data) + ";\n")
print("wrote terrain_data.js")
