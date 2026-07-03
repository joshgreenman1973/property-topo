#!/usr/bin/env python3
"""Add LiDAR canopy height (height above ground) to terrain_data.js.

Aquinnah: Planetary Computer 3dep-lidar-hag (2 m, USGS 2013-14 Sandy flights).
Cornwall: 3dep-lidar-dsm minus 3dep-lidar-dtm from the same 2013 flight.
Stored per tile pixel as uint8 half-meters (0-255 -> 0-127.5 m), row0 = north.
"""
import json, base64, urllib.request, urllib.parse
import numpy as np
import rasterio
from rasterio.vrt import WarpedVRT
from rasterio.transform import from_bounds
from rasterio.enums import Resampling
from pyproj import Transformer

def gj(url):
    return json.load(urllib.request.urlopen(
        urllib.request.Request(url, headers={'User-Agent': 't/1.0'}), timeout=60))

def sas(coll):
    return gj(f"https://planetarycomputer.microsoft.com/api/sas/v1/token/{coll}")["token"]

def items(coll, lon, lat, pad=0.03):
    u = ("https://planetarycomputer.microsoft.com/api/stac/v1/search?"
         + urllib.parse.urlencode({"collections": coll,
             "bbox": f"{lon-pad},{lat-pad},{lon+pad},{lat+pad}", "limit": 10}))
    return gj(u)["features"]

def read_grid(href, token, epsg, bounds, size):
    with rasterio.open(href + "?" + token) as src:
        t = from_bounds(*bounds, size, size)
        with WarpedVRT(src, crs=f"EPSG:{epsg}", transform=t,
                       width=size, height=size, resampling=Resampling.bilinear) as v:
            a = v.read(1).astype(np.float32)
            if v.nodata is not None:
                a[a == v.nodata] = np.nan
            a[np.abs(a) > 1e4] = np.nan
            return a

def mosaic_grid(feats, token, epsg, bounds, size):
    """Mosaic candidate tiles: NaN pixels filled from each subsequent tile."""
    out, ids = None, []
    for f in feats:
        try:
            a = read_grid(f["assets"]["data"]["href"], token, epsg, bounds, size)
        except Exception:
            continue
        if not np.isfinite(a).any():
            continue
        ids.append(f["id"])
        if out is None:
            out = a
        else:
            gap = ~np.isfinite(out)
            out[gap] = a[gap]
        if np.isfinite(out).all():
            break
    return out, ids

EPSG = {"aquinnah": 32619, "cornwall": 32618}

txt = open("terrain_data.js").read()
data = json.loads(txt[txt.index('{'):txt.rstrip().rstrip(';').rindex('}') + 1])

for k, d in data.items():
    lon, lat = d["center_lonlat"]
    epsg, size, half = EPSG[k], d["size"], d["half"]
    fwd = Transformer.from_crs(4326, epsg, always_xy=True)
    cE, cN = fwd.transform(lon, lat)
    bounds = (cE - half, cN - half, cE + half, cN + half)

    if k == "aquinnah":
        hag, ids = mosaic_grid(items("3dep-lidar-hag", lon, lat), sas("3dep-lidar-hag"), epsg, bounds, size)
        src = "USGS 3DEP LiDAR height-above-ground (2013-14)"
    else:
        # PC's DTM tiles are empty here, so use first-return DSM (2013) minus the
        # bare-earth ground grid we already fetched from the seamless 3DEP DEM.
        dsm, ids = mosaic_grid(items("3dep-lidar-dsm", lon, lat), sas("3dep-lidar-dsm"), epsg, bounds, size)
        ground = np.frombuffer(base64.b64decode(d["heights_b64"]), dtype="<f4").reshape(size, size)
        hag = dsm - ground
        src = "USGS 3DEP LiDAR DSM (2013) minus bare-earth DEM"
    v = float(np.isfinite(hag).mean()); src_id = ",".join(i[-16:] for i in ids)

    hag = np.clip(np.nan_to_num(hag, nan=0.0), 0, 60)
    enc = np.clip(np.round(hag * 2), 0, 255).astype(np.uint8)   # half-meter steps
    p95 = float(np.percentile(hag[hag > 2], 95)) if (hag > 2).any() else 0.0
    print(f"[{k}] canopy from {src_id}  valid={v*100:.0f}%  p95={p95:.1f} m")
    d["canopy_b64"] = base64.b64encode(enc.tobytes()).decode()
    d["canopy_src"] = src

    # tree mask from the LiDAR itself: canopy >= 2.5 m, buildings excluded.
    # (The Esri aerial for Cornwall is leaf-off/off-season, so the old greenness
    # test badly under-detected trees there — LiDAR sees the actual canopy.)
    res = 2 * half / size
    tree = hag >= 2.5
    bmask = np.zeros((size, size), dtype=bool)
    for b in d.get("buildings", []):
        ring = b["mesh"]
        xs = [p[0] for p in ring]; zs = [p[1] for p in ring]
        c0 = max(0, int((min(xs)+half)/res)-1); c1 = min(size-1, int((max(xs)+half)/res)+1)
        r0 = max(0, int((min(zs)+half)/res)-1); r1 = min(size-1, int((max(zs)+half)/res)+1)
        for r_ in range(r0, r1+1):
            z = -half + (r_+0.5)*res
            for c_ in range(c0, c1+1):
                x = -half + (c_+0.5)*res
                inside = False
                for i in range(len(ring)-1):
                    x1, z1 = ring[i]; x2, z2 = ring[i+1]
                    if (z1 > z) != (z2 > z) and x < (x2-x1)*(z-z1)/(z2-z1)+x1:
                        inside = not inside
                if inside: bmask[r_, c_] = True
    for _ in range(2):   # ~2 px dilation so roof-edge LiDAR returns don't read as trees
        bmask |= np.roll(bmask,1,0)|np.roll(bmask,-1,0)|np.roll(bmask,1,1)|np.roll(bmask,-1,1)
    tree &= ~bmask
    print(f"    tree mask (LiDAR >=2.5m, buildings out): {tree.mean()*100:.0f}% of tile")
    d["tree_b64"] = base64.b64encode(tree.astype(np.uint8).tobytes()).decode()
    d["tree_src"] = "LiDAR canopy >= 2.5 m (2013-14), building footprints excluded"

with open("terrain_data.js", "w") as f:
    f.write("window.TERRAIN = " + json.dumps(data) + ";\n")
print("wrote terrain_data.js")
