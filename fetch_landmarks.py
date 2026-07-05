#!/usr/bin/env python3
"""Compute which named landmarks are visible from each house (true line-of-sight
over a regional bare-earth DEM, with Earth-curvature + refraction). Stores the
visible ones (name, bearing, distance, elevation) in terrain_data.js."""
import json, math, io, urllib.request, urllib.parse, socket
import numpy as np
from PIL import Image
socket.setdefaulttimeout(60)

PTS = {"aquinnah": (-70.810771, 41.336566), "cornwall": (-74.0164057, 41.4200187)}
EYE = 8.0          # observer eye height above ground (m) — upper floor / deck
R_EFF = 6371000 * 7.0/6.0   # earth radius w/ standard atmospheric refraction

def gj(url, data=None):
    req = urllib.request.Request(url, data=data, headers={'User-Agent': 'topo/1.0'})
    return json.load(urllib.request.urlopen(req, timeout=90))

def regional_dem(lon, lat, dpad=0.34, size=760):
    bbox = f"{lon-dpad*1.3},{lat-dpad},{lon+dpad*1.3},{lat+dpad}"
    url = ("https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage"
           f"?bbox={bbox}&bboxSR=4326&size={size},{size}&imageSR=4326"
           "&format=tiff&pixelType=F32&interpolation=RSP_BilinearInterpolation&f=image")
    a = np.array(Image.open(io.BytesIO(urllib.request.urlopen(
        urllib.request.Request(url, headers={'User-Agent': 'topo/1.0'}), timeout=120).read())), dtype=np.float32)
    a[a < -1e5] = 0.0   # ocean / nodata -> sea level
    ext = (lon-dpad*1.3, lon+dpad*1.3, lat-dpad, lat+dpad)  # W,E,S,N
    return a, ext

def demval(a, ext, lon, lat):
    W, E, S, N = ext; H, Wd = a.shape
    if not (W <= lon <= E and S <= lat <= N):
        return 0.0
    c = (lon-W)/(E-W)*(Wd-1); r = (N-lat)/(N-S)*(H-1)   # row0 = north
    c0, r0 = int(c), int(r); c1, r1 = min(c0+1, Wd-1), min(r0+1, H-1)
    fc, fr = c-c0, r-r0
    v = (a[r0, c0]*(1-fc)+a[r0, c1]*fc)*(1-fr) + (a[r1, c0]*(1-fc)+a[r1, c1]*fc)*fr
    return float(v)

def haversine(lo1, la1, lo2, la2):
    R = 6371000; p1, p2 = math.radians(la1), math.radians(la2)
    dp = math.radians(la2-la1); dl = math.radians(lo2-lo1)
    x = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(x))

def bearing(lo1, la1, lo2, la2):
    p1, p2 = math.radians(la1), math.radians(la2); dl = math.radians(lo2-lo1)
    x = math.sin(dl)*math.cos(p2)
    y = math.cos(p1)*math.sin(p2) - math.sin(p1)*math.cos(p2)*math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360

def visible(a, ext, olon, olat, oelev, tlon, tlat, telev):
    d = haversine(olon, olat, tlon, tlat)
    if d < 50: return True
    n = max(24, int(d/120))
    maxang = -math.inf
    for i in range(1, n):
        f = i/n
        lo = olon + (tlon-olon)*f; la = olat + (tlat-olat)*f
        di = d*f
        h = demval(a, ext, lo, la) - di*di/(2*R_EFF)   # curvature drop
        ang = math.atan2(h - oelev, di)
        if di < d*0.985:          # ignore samples right at the target
            maxang = max(maxang, ang)
    tang = math.atan2((telev - d*d/(2*R_EFF)) - oelev, d)
    return tang > maxang + 0.0009   # ~0.05 deg margin

import time
def overpass(ql):
    mirrors = ("https://overpass-api.de/api/interpreter",
               "https://overpass.kumi.systems/api/interpreter",
               "https://overpass.osm.jp/api/interpreter",
               "https://maps.mail.ru/osm/tools/overpass/api/interpreter")
    for attempt in range(3):
        for m in mirrors:
            try:
                r = gj(m, urllib.parse.urlencode({"data": ql}).encode())
                if r.get("elements") is not None:
                    return r
            except Exception as e:
                print(f"  overpass [{m.split('/')[2]}] {str(e)[:40]}")
        time.sleep(8 * (attempt + 1))
    return {"elements": []}

txt = open("terrain_data.js").read()
data = json.loads(txt[txt.index('{'):txt.rstrip().rstrip(';').rindex('}')+1])

for k, (lon, lat) in PTS.items():
    print(f"[{k}] regional DEM ...")
    dem, ext = regional_dem(lon, lat)
    oelev = demval(dem, ext, lon, lat) + EYE
    q1 = f"""[out:json][timeout:90];(
      node["natural"="peak"]["name"](around:34000,{lat},{lon});
      node["natural"="cape"]["name"](around:34000,{lat},{lon});
      node["natural"="cliff"]["name"](around:20000,{lat},{lon});
      node["man_made"="lighthouse"]["name"](around:38000,{lat},{lon});
      node["place"="island"]["name"](around:34000,{lat},{lon});
      way["place"="island"]["name"](around:34000,{lat},{lon});
      node["natural"="bay"]["name"](around:30000,{lat},{lon});
      way["historic"="castle"]["name"](around:34000,{lat},{lon});
      node["tourism"="attraction"]["name"](around:18000,{lat},{lon});
    );out center;"""
    q2 = f"""[out:json][timeout:90];(
      way["waterway"="river"]["name"](around:14000,{lat},{lon});
      way["natural"="water"]["name"](around:12000,{lat},{lon});
    );out geom;"""
    els = overpass(q1).get("elements", []) + overpass(q2).get("elements", [])
    seen, cands = set(), []
    def nearest_geom_pt(geom):
        best, bd = None, 1e18
        for g in geom:
            d = (g["lon"]-lon)**2 + (g["lat"]-lat)**2
            if d < bd: bd, best = d, (g["lon"], g["lat"])
        return best
    for e in els:
        t = e.get("tags", {}); nm = t.get("name")
        if not nm or nm in seen: continue
        if "geometry" in e and e["geometry"]:
            pt = nearest_geom_pt(e["geometry"])           # nearest point of rivers/lakes/islands
            elon, elat = pt
        else:
            elon = e.get("lon") or e.get("center", {}).get("lon")
            elat = e.get("lat") or e.get("center", {}).get("lat")
        if elon is None: continue
        seen.add(nm)
        kind = ("peak" if t.get("natural") == "peak" else "lighthouse" if t.get("man_made") == "lighthouse"
                else "island" if t.get("place") == "island" else "castle" if t.get("historic") == "castle"
                else "cape" if t.get("natural") == "cape" else "cliff" if t.get("natural") == "cliff"
                else "water" if (t.get("natural") == "water" or t.get("waterway") == "river" or t.get("natural") == "bay")
                else "place")
        ele = None
        try: ele = float(t.get("ele")) if t.get("ele") else None
        except: ele = None
        cands.append((nm, elon, elat, kind, ele))
    vis = []
    for nm, elon, elat, kind, ele in cands:
        base = (ele if ele is not None else demval(dem, ext, elon, elat))
        telev = base + (0.5 if kind == "water" else 3)   # water: see the surface; else summit
        d = haversine(lon, lat, elon, elat)
        if d < 120: continue
        if visible(dem, ext, lon, lat, oelev, elon, elat, telev):
            vis.append({"name": nm, "kind": kind, "bearing": round(bearing(lon, lat, elon, elat), 1),
                        "dist_km": round(d/1000, 1), "elev": round(base)})
    # ocean check for coastal sites: sample sea points offshore in an arc, keep if visible
    ocean_dirs = []
    for brg in range(0, 360, 15):
        b = math.radians(brg); ok = False
        for dm in (2200, 4000, 7000):
            dlat = (dm*math.cos(b))/111320; dlon = (dm*math.sin(b))/(111320*math.cos(math.radians(lat)))
            slon, slat = lon+dlon, lat+dlat
            if demval(dem, ext, slon, slat) < 1.0 and visible(dem, ext, lon, lat, oelev, slon, slat, 0.5):
                ok = True; break
        if ok: ocean_dirs.append(brg)
    if ocean_dirs:
        # central bearing of the ocean arc
        bc = sum(ocean_dirs)/len(ocean_dirs)
        vis.append({"name": "Atlantic Ocean", "kind": "water", "bearing": round(bc, 1),
                    "dist_km": None, "elev": 0})
    vis.sort(key=lambda v: (v["dist_km"] is None, v["dist_km"] or 0))
    data[k]["landmarks"] = {"eye": EYE, "items": vis}
    print(f"    {len(cands)} candidates -> {len(vis)} visible: " + ", ".join(v["name"] for v in vis[:12]))

with open("terrain_data.js", "w") as f:
    f.write("window.TERRAIN = " + json.dumps(data) + ";\n")
print("wrote terrain_data.js")
