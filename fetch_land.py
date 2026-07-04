#!/usr/bin/env python3
"""Add natural/regulatory land layers to terrain_data.js:
- USDA SSURGO soil map units (polygons, drainage class, septic rating)
- FEMA NFHL flood zone (fact)
- USFWS NWI wetlands presence (fact)
- Macrostrat geology (fact)
"""
import json, re, socket, urllib.request, urllib.parse
from pyproj import Transformer
socket.setdefaulttimeout(45)

def gj(url):
    return json.load(urllib.request.urlopen(
        urllib.request.Request(url, headers={'User-Agent': 't/1.0'}), timeout=45))

def sda(sql):
    body = json.dumps({"query": sql, "format": "JSON"}).encode()
    req = urllib.request.Request("https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest",
                                 data=body, headers={'Content-Type': 'application/json', 'User-Agent': 't/1.0'})
    return json.load(urllib.request.urlopen(req, timeout=60))

def parse_wkt_polys(wkt):
    """Return list of rings (each list of [lon,lat]) from POLYGON/MULTIPOLYGON WKT."""
    rings = []
    for ringtxt in re.findall(r'\(([^()]+)\)', wkt or ""):
        pts = []
        for pair in ringtxt.split(','):
            xy = pair.split()
            if len(xy) >= 2:
                pts.append([float(xy[0]), float(xy[1])])
        if len(pts) >= 4:
            rings.append(pts)
    return rings

EPSG = {"aquinnah": 32619, "cornwall": 32618}

txt = open("terrain_data.js").read()
data = json.loads(txt[txt.index('{'):txt.rstrip().rstrip(';').rindex('}') + 1])

for k, d in data.items():
    lon, lat = d["center_lonlat"]
    epsg = EPSG[k]
    fwd = Transformer.from_crs(4326, epsg, always_xy=True)
    cE, cN = fwd.transform(lon, lat)
    ring = max(d["poly_lonlat"], key=len)
    wkt = "POLYGON((" + ", ".join(f"{lo} {la}" for lo, la in ring) + "))"

    # --- soils ---
    sql = f"""
    SELECT mu.mukey, mu.muname,
      (SELECT TOP 1 c.drainagecl FROM component c WHERE c.mukey=mu.mukey AND c.majcompflag='Yes' ORDER BY c.comppct_r DESC),
      (SELECT TOP 1 ci.interphrc FROM component c JOIN cointerp ci ON ci.cokey=c.cokey
        WHERE c.mukey=mu.mukey AND c.majcompflag='Yes' AND ci.mrulename='ENG - Septic Tank Absorption Fields'
          AND ci.ruledepth=0 ORDER BY c.comppct_r DESC),
      mup.mupolygongeo.STIntersection(geometry::STGeomFromText('{wkt}',4326)).STAsText()
    FROM mupolygon mup INNER JOIN mapunit mu ON mu.mukey=mup.mukey
    WHERE mup.mupolygongeo.STIntersects(geometry::STGeomFromText('{wkt}',4326))=1
    """
    soils = []
    try:
        rows = sda(sql).get("Table", [])
        # merge rows by mukey (a unit can appear as several polygons)
        by = {}
        for mukey, muname, drain, septic, geom in rows:
            e = by.setdefault(mukey, {"name": muname, "drainage": drain, "septic": septic, "rings": []})
            for r_ in parse_wkt_polys(geom):
                e["rings"].append([[round(x, 1) for x in
                                    (lambda E, Nn: [E - cE, -(Nn - cN)])(*fwd.transform(lo, la))]
                                   for lo, la in r_])
        soils = [v for v in by.values() if v["rings"]]
    except Exception as ex:
        print(f"[{k}] soils ERR {str(ex)[:80]}")
    d["soils"] = soils
    print(f"[{k}] soils: " + "; ".join(f"{s['name'][:38]} ({s['drainage']}, septic: {s['septic']})" for s in soils))

    # --- flood zone ---
    try:
        u = ("https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query?"
             + urllib.parse.urlencode({"geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint",
                                       "inSR": "4326", "spatialRel": "esriSpatialRelIntersects",
                                       "outFields": "FLD_ZONE,ZONE_SUBTY", "returnGeometry": "false", "f": "json"}))
        fs = gj(u).get("features", [])
        if fs:
            a = fs[0]["attributes"]
            d["flood"] = f"Zone {a['FLD_ZONE']}" + (f" — {a['ZONE_SUBTY'].lower()}" if a.get("ZONE_SUBTY") else "")
        else:
            d["flood"] = "no zone mapped"
    except Exception as ex:
        print(f"[{k}] flood ERR {str(ex)[:60]}")
    # --- wetlands ---
    try:
        u = ("https://fwspublicservices.wim.usgs.gov/wetlandsmapservice/rest/services/Wetlands/MapServer/0/query?"
             + urllib.parse.urlencode({"geometry": f"{lon-0.0025},{lat-0.0025},{lon+0.0025},{lat+0.0025}",
                                       "geometryType": "esriGeometryEnvelope", "inSR": "4326",
                                       "spatialRel": "esriSpatialRelIntersects", "outFields": "WETLAND_TYPE",
                                       "returnGeometry": "false", "f": "json"}))
        fs = gj(u).get("features", [])
        d["wetlands"] = (", ".join(sorted({f['attributes']['WETLAND_TYPE'] for f in fs}))
                         if fs else "none mapped within 250 m")
    except Exception as ex:
        print(f"[{k}] wetlands ERR {str(ex)[:60]}")
    # --- geology ---
    try:
        r = gj(f"https://macrostrat.org/api/v2/geologic_units/map?lat={lat}&lng={lon}")
        units = r.get("success", {}).get("data", [])
        d["geology"] = [{"name": u.get("name"), "age": f"{u.get('b_age')}–{u.get('t_age')} Ma"}
                        for u in units[:2]]
    except Exception as ex:
        print(f"[{k}] geology ERR {str(ex)[:60]}")
    print(f"    flood: {d.get('flood')} | wetlands: {d.get('wetlands')} | geology: {[g['name'] for g in d.get('geology',[])]}")

with open("terrain_data.js", "w") as f:
    f.write("window.TERRAIN = " + json.dumps(data) + ";\n")
print("wrote terrain_data.js")
