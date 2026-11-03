#!/usr/bin/env python3
"""The parcel's own LiDAR point cloud, for drawing the real trees and house.

Downloads the newest USGS 3DEP LAZ tile(s) over the parcel (same flight as the
canopy grid), keeps every non-noise return inside the parcel boundary that sits
at least 0.4 m above the bare-earth grid, and writes a compact binary:
  header  uint32 n
  then per point: int16 x_cm_from_tile_center, int16 z_cm, uint16 hag_cm, uint8 cls, uint8 intensity_8bit
x east / z south in mesh meters (same frame as terrain_data.js), hag = height above
the bare-earth grid. Loaded by index.html with fetch() when the layer is turned on.
"""
import json, base64, os, sys, urllib.request, urllib.parse
import numpy as np, laspy
from pyproj import Transformer, CRS
from matplotlib.path import Path

CACHE = os.path.join(os.environ.get("SCRATCH", "/tmp"), "laz"); os.makedirs(CACHE, exist_ok=True)
PROJECTS = {"aquinnah": ("MA_CentralEastern_2021", 32619), "cornwall": ("NY_SouthEast4County_A22", 32618)}
KEYS = sys.argv[1:] or ["cornwall"]
MIN_HAG = 0.4

def gj(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'property-topo/1.0'}), timeout=60))
def download(url, dest):
    import subprocess, time
    expected = 0
    for attempt in range(5):   # the USGS host rate-limits; back off and retry
        try:
            req = urllib.request.Request(url, method="HEAD", headers={'User-Agent': 'property-topo/1.0'})
            expected = int(urllib.request.urlopen(req, timeout=30).headers.get("Content-Length", 0)); break
        except Exception as e:
            print(f"    HEAD failed ({str(e)[:40]}), waiting {15*(attempt+1)} s", flush=True); time.sleep(15 * (attempt + 1))
    if os.path.exists(dest) and expected and os.path.getsize(dest) == expected: return dest
    for attempt in range(6):
        print(f"    downloading {url.rsplit('/',1)[-1]} (try {attempt+1}) ...", flush=True)
        r = subprocess.run(["curl", "-sSL", "--retry", "3", "--retry-delay", "10", "-C", "-", "-A", "property-topo/1.0", "-o", dest, url])
        if r.returncode == 0 and os.path.exists(dest) and (not expected or os.path.getsize(dest) == expected):
            print(f"    {os.path.getsize(dest)/1e6:.0f} MB", flush=True); return dest
        time.sleep(20 * (attempt + 1))
    raise RuntimeError("could not download " + url)

txt = open("terrain_data.js").read()
data = json.loads(txt[txt.index('{'):txt.rstrip().rstrip(';').rindex('}') + 1])
for k in KEYS:
    d = data[k]; proj, epsg = PROJECTS[k]
    N, half = d["size"], d["half"]; res = 2 * half / N
    lon, lat = d["center_lonlat"]
    cE, cN = Transformer.from_crs(4326, epsg, always_xy=True).transform(lon, lat)
    c = d["corners"]
    u = ("https://tnmaccess.nationalmap.gov/api/v1/products?" + urllib.parse.urlencode(
        {"datasets": "Lidar Point Cloud (LPC)", "bbox": f"{c['sw'][0]},{c['sw'][1]},{c['ne'][0]},{c['ne'][1]}", "outputFormat": "JSON", "max": 40}))
    urls = sorted({it["downloadURL"] for it in gj(u).get("items", []) if proj in it.get("title", "")})
    print(f"[{k}] {proj}: {len(urls)} LAZ tile(s)")
    ground = np.frombuffer(base64.b64decode(d["heights_b64"]), dtype="<f4").reshape(N, N)
    ring = max(d["poly_mesh"], key=len); P = Path(ring)
    xs_ = [p[0] for p in ring]; zs_ = [p[1] for p in ring]
    keep = []
    for url in urls:
        path = download(url, os.path.join(CACHE, url.rsplit('/', 1)[-1]))
        with laspy.open(path) as lf:
            try: src = lf.header.parse_crs()
            except Exception: src = None
            tf = Transformer.from_crs(src, epsg, always_xy=True) if src is not None and CRS(src).to_epsg() != epsg else None
            for pts in lf.chunk_iterator(3_000_000):
                x = np.asarray(pts.x); y = np.asarray(pts.y); z = np.asarray(pts.z)
                cls = np.asarray(pts.classification); inten = np.asarray(pts.intensity)
                ok = (cls != 7) & (cls != 18)
                x, y, z, cls, inten = x[ok], y[ok], z[ok], cls[ok], inten[ok]
                if tf is not None: x, y = tf.transform(x, y)
                mx = x - cE; mz = cN - y            # mesh frame: x east, z south
                m = (mx >= min(xs_)) & (mx <= max(xs_)) & (mz >= min(zs_)) & (mz <= max(zs_))
                if not m.any(): continue
                mx, mz, z, cls, inten = mx[m], mz[m], z[m], cls[m], inten[m]
                inside = P.contains_points(np.c_[mx, mz])
                mx, mz, z, cls, inten = mx[inside], mz[inside], z[inside], cls[inside], inten[inside]
                col = np.clip(((mx + half) / res - 0.5).round().astype(int), 0, N - 1)
                row = np.clip(((mz + half) / res - 0.5).round().astype(int), 0, N - 1)
                hag = z - ground[row, col]
                a = (hag >= MIN_HAG) & (cls != 2)   # ground-class returns above the grid are grid error, not vegetation
                keep.append(np.c_[mx[a], mz[a], hag[a], cls[a], inten[a]])
    allp = np.vstack(keep) if keep else np.zeros((0, 5))
    print(f"    {len(allp):,} points above {MIN_HAG} m inside the parcel; classes {dict(zip(*np.unique(allp[:,3].astype(int), return_counts=True)))}")
    i8 = allp[:, 4]; i8 = np.clip(i8 / max(1, np.percentile(i8, 98)) * 255, 0, 255) if len(i8) else i8
    out = np.zeros(len(allp), dtype=[('x', '<i2'), ('z', '<i2'), ('h', '<u2'), ('c', 'u1'), ('i', 'u1')])
    out['x'] = np.round(allp[:, 0] * 100); out['z'] = np.round(allp[:, 1] * 100)
    out['h'] = np.clip(np.round(allp[:, 2] * 100), 0, 65535); out['c'] = allp[:, 3]; out['i'] = i8
    fn = f"{k}_points.bin"
    with open(fn, "wb") as f: f.write(np.uint32(len(out)).tobytes()); f.write(out.tobytes())
    print(f"    wrote {fn}: {os.path.getsize(fn)/1e6:.1f} MB; hag p50 {np.percentile(allp[:,2],50):.1f} p95 {np.percentile(allp[:,2],95):.1f} max {allp[:,2].max():.1f} m")
