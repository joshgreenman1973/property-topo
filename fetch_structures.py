#!/usr/bin/env python3
"""Structure details:
- assessor construction history -> d["built"]
- roof form per building measured from the cached LiDAR point clouds
  (eave height, ridge height, ridge axis) + roof color from the aerial.
"""
import json, base64, io, math, os, glob
import numpy as np
import laspy
from PIL import Image
from pyproj import Transformer, CRS

CACHE = "/private/tmp/claude-501/-Users-joshgreenman-Experiments/1a54d4e4-6fb0-43ce-9283-7346cacb4ed5/scratchpad/laz"
EPSG = {"aquinnah": 32619, "cornwall": 32618}
LAZ = {"aquinnah": "USGS_LPC_MA_*.laz", "cornwall": "USGS_LPC_NY_*.laz"}

BUILT = {
    "aquinnah": {"year": 1990, "style": "AQ Custom", "stories": "2.5",
                 "living_sqft": 2024, "gross_sqft": 5424,
                 "sale": "last transfer Jan 2003 (deed bk 924 / pg 817)",
                 "src": "Aquinnah assessor, FY2025 roll"},
    "cornwall": {"year": 1975, "style": "Contemporary", "stories": "2",
                 "living_sqft": 3518, "beds": 3, "baths": 4,
                 "heat": "hot water/steam, oil", "utilities": "gas & electric",
                 "water": "private well", "sewer": "private septic",
                 "src": "Orange County assessor, 2025 roll"},
}

txt = open("terrain_data.js").read()
data = json.loads(txt[txt.index('{'):txt.rstrip().rstrip(';').rindex('}') + 1])

def inpoly(x, z, ring):
    inside = False
    for i in range(len(ring) - 1):
        x1, z1 = ring[i]; x2, z2 = ring[i + 1]
        if (z1 > z) != (z2 > z) and x < (x2 - x1) * (z - z1) / (z2 - z1) + x1:
            inside = not inside
    return inside

for k, d in data.items():
    d["built"] = BUILT[k]
    N, half = d["size"], d["half"]
    res = 2 * half / N
    lon, lat = d["center_lonlat"]
    fwd = Transformer.from_crs(4326, EPSG[k], always_xy=True)
    cE, cN = fwd.transform(lon, lat)
    ground = np.frombuffer(base64.b64decode(d["heights_b64"]), dtype="<f4").reshape(N, N)
    rgb = np.asarray(Image.open(io.BytesIO(base64.b64decode(d["aerial_b64"]))).convert("RGB"))

    parts = [b for b in d["buildings"] if b.get("occ") != "connector"]
    # collect LiDAR points per building part
    pts_by = {i: [] for i in range(len(parts))}
    for path in glob.glob(os.path.join(CACHE, LAZ[k])):
        with laspy.open(path) as lf:
            for chunk in lf.chunk_iterator(3_000_000):
                x = np.asarray(chunk.x); y = np.asarray(chunk.y); z = np.asarray(chunk.z)
                cls = np.asarray(chunk.classification)
                mx = x - cE; mz = -(y - cN)
                sel = (np.abs(mx) < half) & (np.abs(mz) < half) & (cls == 6)  # building returns only
                mx, mz, z = mx[sel], mz[sel], z[sel]
                for i, b in enumerate(parts):
                    ring = b["mesh"]
                    xs = [p[0] for p in ring]; zs = [p[1] for p in ring]
                    box = (mx >= min(xs)) & (mx <= max(xs)) & (mz >= min(zs)) & (mz <= max(zs))
                    if not box.any():
                        continue
                    for xx, zz, hz in zip(mx[box], mz[box], z[box]):
                        if inpoly(xx, zz, ring):
                            pts_by[i].append((xx, zz, hz))
    for i, b in enumerate(parts):
        ring = b["mesh"]
        # ground at footprint = min of grid ground under it
        gs = []
        for xx, zz in ring:
            c = min(N - 1, max(0, int((xx + half) / res))); r = min(N - 1, max(0, int((zz + half) / res)))
            gs.append(ground[r, c])
        g0 = float(np.min(gs))
        P = np.array(pts_by[i]) if pts_by[i] else np.zeros((0, 3))
        if len(P) >= 30:
            hag = P[:, 2] - g0
            hag = hag[(hag > 1) & (hag < 20)]
            if len(hag) >= 20:
                eave = float(np.percentile(hag, 25))
                ridge = float(np.percentile(hag, 97))
            else:
                eave, ridge = b["height"] * 0.7, b["height"]
        else:
            eave, ridge = b["height"] * 0.7, b["height"]
        # ridge axis = direction of longest footprint edge
        best, ang = 0, 0.0
        for j in range(len(ring) - 1):
            dx = ring[j + 1][0] - ring[j][0]; dz = ring[j + 1][1] - ring[j][1]
            L = math.hypot(dx, dz)
            if L > best:
                best, ang = L, math.atan2(dz, dx)
        # roof color = mean aerial pixel over footprint
        cols = []
        for xx, zz in [( (ring[j][0]+ring[j+1][0])/2, (ring[j][1]+ring[j+1][1])/2 ) for j in range(len(ring)-1)] + \
                      [(sum(p[0] for p in ring)/len(ring), sum(p[1] for p in ring)/len(ring))]:
            c = min(N - 1, max(0, int((xx + half) / res))); r = min(N - 1, max(0, int((zz + half) / res)))
            cols.append(rgb[r, c])
        mean = np.mean(cols, axis=0).astype(int)
        b["eave"] = round(max(2.2, eave), 1)
        b["ridge"] = round(max(eave + 0.5, ridge), 1)
        b["axis"] = round(ang, 3)
        b["roof_rgb"] = [int(v) for v in mean]
        print(f"[{k}] part {i}: {len(P)} pts  eave={b['eave']} ridge={b['ridge']} axis={math.degrees(ang):.0f}° roof_rgb={b['roof_rgb']}")

with open("terrain_data.js", "w") as f:
    f.write("window.TERRAIN = " + json.dumps(data) + ";\n")
print("wrote terrain_data.js")
