#!/usr/bin/env python3
"""Canopy height from the NEWEST USGS LiDAR flights (2021 MA / 2022 NY),
computed directly from the raw point clouds.

For each property: download the LPC LAZ tile(s) intersecting the terrain tile,
grid the max return height per 1 m cell, subtract the bare-earth grid already
in terrain_data.js (same flights via the seamless DEM), write canopy + tree mask.
"""
import json, base64, math, os, urllib.request, urllib.parse
import numpy as np
import laspy
from pyproj import Transformer, CRS

CACHE = "/private/tmp/claude-501/-Users-joshgreenman-Experiments/1a54d4e4-6fb0-43ce-9283-7346cacb4ed5/scratchpad/laz"
os.makedirs(CACHE, exist_ok=True)

PROJECTS = {"aquinnah": ("MA_CentralEastern_2021", "2021", 32619),
            "cornwall": ("NY_SouthEast4County_A22", "2022", 32618)}

def gj(url):
    return json.load(urllib.request.urlopen(
        urllib.request.Request(url, headers={'User-Agent': 't/1.0'}), timeout=60))

def download(url, dest):
    # expected size from server; a cached file is valid only if complete
    req = urllib.request.Request(url, method="HEAD", headers={'User-Agent': 't/1.0'})
    expected = int(urllib.request.urlopen(req, timeout=30).headers.get("Content-Length", 0))
    if os.path.exists(dest) and expected and os.path.getsize(dest) == expected:
        return dest
    for attempt in range(4):
        try:
            print(f"    downloading {url.rsplit('/',1)[-1]} (try {attempt+1}) ...")
            urllib.request.urlretrieve(url, dest)
            if not expected or os.path.getsize(dest) == expected:
                print(f"    {os.path.getsize(dest)/1e6:.0f} MB")
                return dest
        except Exception as e:
            print(f"    retry after: {str(e)[:80]}")
        if os.path.exists(dest):
            os.remove(dest)
    raise RuntimeError(f"could not download {url}")

txt = open("terrain_data.js").read()
data = json.loads(txt[txt.index('{'):txt.rstrip().rstrip(';').rindex('}') + 1])

for k, d in data.items():
    proj, year, epsg = PROJECTS[k]
    N, half = d["size"], d["half"]
    res = 2 * half / N
    lon, lat = d["center_lonlat"]
    fwd = Transformer.from_crs(4326, epsg, always_xy=True)
    cE, cN = fwd.transform(lon, lat)
    c = d["corners"]
    bbox_ll = f"{c['sw'][0]},{c['sw'][1]},{c['ne'][0]},{c['ne'][1]}"

    # find LAZ tiles of the target project intersecting our tile
    u = ("https://tnmaccess.nationalmap.gov/api/v1/products?"
         + urllib.parse.urlencode({"datasets": "Lidar Point Cloud (LPC)",
                                   "bbox": bbox_ll, "outputFormat": "JSON", "max": 40}))
    items = [it for it in gj(u).get("items", []) if proj in it.get("title", "")]
    # dedupe by URL
    urls = sorted({it["downloadURL"] for it in items})
    print(f"[{k}] {proj}: {len(urls)} LAZ tile(s)")

    maxz = np.full((N, N), -np.inf, dtype=np.float32)
    for url in urls:
        path = download(url, os.path.join(CACHE, url.rsplit('/', 1)[-1]))
        with laspy.open(path) as lf:
            src_crs = None
            try:
                src_crs = lf.header.parse_crs()
            except Exception:
                pass
            tf = None
            if src_crs is not None and CRS(src_crs).to_epsg() != epsg:
                tf = Transformer.from_crs(src_crs, epsg, always_xy=True)
                print(f"    reprojecting from {CRS(src_crs).to_epsg()}")
            n_pts = 0
            for pts in lf.chunk_iterator(3_000_000):
                x = np.asarray(pts.x); y = np.asarray(pts.y); z = np.asarray(pts.z)
                cls = np.asarray(pts.classification)
                ok = (cls != 7) & (cls != 18)          # drop noise points
                x, y, z = x[ok], y[ok], z[ok]
                if tf is not None:
                    x, y = tf.transform(x, y)
                # vertical: projects deliver NAVD88 m (matches the DEM)
                col = ((x - (cE - half)) / res - 0.5).round().astype(np.int64)
                row = (((cN + half) - y) / res - 0.5).round().astype(np.int64)  # row0 = north
                m = (col >= 0) & (col < N) & (row >= 0) & (row < N)
                if not m.any():
                    continue
                n_pts += int(m.sum())
                np.maximum.at(maxz, (row[m], col[m]), z[m].astype(np.float32))
            print(f"    {n_pts:,} points in tile")

    ground = np.frombuffer(base64.b64decode(d["heights_b64"]), dtype="<f4").reshape(N, N)
    hag = maxz - ground
    hag[~np.isfinite(hag)] = 0.0
    hag = np.clip(hag, 0, 60)
    # fill empty cells (no returns) from 4-neighbor mean, two passes
    empty = (maxz == -np.inf)
    for _ in range(2):
        if not empty.any():
            break
        nb = (np.roll(hag, 1, 0) + np.roll(hag, -1, 0) + np.roll(hag, 1, 1) + np.roll(hag, -1, 1)) / 4
        hag[empty] = nb[empty]
        empty &= False

    p95 = float(np.percentile(hag[hag > 2], 95)) if (hag > 2).any() else 0.0
    print(f"    canopy {year}: p95={p95:.1f} m  cover>=2.5m={(hag>=2.5).mean()*100:.0f}%")

    # tree mask: canopy >= 2.5 m, buildings (dilated) excluded
    tree = hag >= 2.5
    bmask = np.zeros((N, N), dtype=bool)
    for b in d.get("buildings", []):
        ring = b["mesh"]
        xs = [p[0] for p in ring]; zs = [p[1] for p in ring]
        c0 = max(0, int((min(xs)+half)/res)-1); c1 = min(N-1, int((max(xs)+half)/res)+1)
        r0 = max(0, int((min(zs)+half)/res)-1); r1 = min(N-1, int((max(zs)+half)/res)+1)
        for r_ in range(r0, r1+1):
            z_ = -half + (r_+0.5)*res
            for c_ in range(c0, c1+1):
                x_ = -half + (c_+0.5)*res
                inside = False
                for i in range(len(ring)-1):
                    x1, z1 = ring[i]; x2, z2 = ring[i+1]
                    if (z1 > z_) != (z2 > z_) and x_ < (x2-x1)*(z_-z1)/(z2-z1)+x1:
                        inside = not inside
                if inside: bmask[r_, c_] = True
    for _ in range(2):
        bmask |= np.roll(bmask,1,0)|np.roll(bmask,-1,0)|np.roll(bmask,1,1)|np.roll(bmask,-1,1)
    tree &= ~bmask

    d["canopy_b64"] = base64.b64encode(np.clip(np.round(hag*2),0,255).astype(np.uint8).tobytes()).decode()
    d["canopy_src"] = f"USGS 3DEP LiDAR {proj} ({year} flight), max return minus bare earth"
    d["canopy_yr"] = year
    d["tree_b64"] = base64.b64encode(tree.astype(np.uint8).tobytes()).decode()
    d["tree_src"] = f"LiDAR canopy >= 2.5 m ({year}), building footprints excluded"

with open("terrain_data.js", "w") as f:
    f.write("window.TERRAIN = " + json.dumps(data) + ";\n")
print("wrote terrain_data.js")
