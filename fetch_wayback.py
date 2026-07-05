#!/usr/bin/env python3
"""Historical aerial imagery time-slider frames from Esri World Imagery Wayback.
For a spread of dates, stitch web-mercator tiles over each parcel and resample to
the terrain tile (using its corner lat/lons), dedupe near-identical frames, store."""
import json, math, io, base64, hashlib, socket, urllib.request
import numpy as np
from PIL import Image
socket.setdefaulttimeout(40)

def gj(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 't/1.0'}), timeout=40))
def getbytes(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 't/1.0'}), timeout=40).read()

Z = 18
SIZE = 320                    # output frame resolution
TARGET_DATES = ["2014-07", "2016-07", "2018-07", "2020-07", "2021-07",
                "2022-07", "2023-07", "2024-07", "2025-07", "2026-06"]

cfg = gj("https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/waybackconfig.json")
rels = []
for rid, v in cfg.items():
    t = v.get("itemTitle", "")
    if "Wayback " in t:
        d = t.split("Wayback ")[1].rstrip(")")
        rels.append((d, int(rid)))
rels.sort()
def nearest(target):
    ty, tm = int(target[:4]), int(target[5:7])
    return min(rels, key=lambda r: abs((int(r[0][:4])-ty)*12 + (int(r[0][5:7])-tm)))
picks, seenr = [], set()
for td in TARGET_DATES:
    d, rid = nearest(td)
    if rid not in seenr:
        seenr.add(rid); picks.append((d, rid))

def lonlat_to_px(lon, lat, z):
    n = 256 * (2**z)
    mx = (lon + 180.0)/360.0 * n
    s = math.sin(math.radians(lat))
    my = (0.5 - math.log((1+s)/(1-s))/(4*math.pi)) * n
    return mx, my

def tile_url(rid, z, x, y):
    return (f"https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/"
            f"WMTS/1.0.0/default028mm/MapServer/tile/{rid}/{z}/{y}/{x}")

txt = open("terrain_data.js").read()
data = json.loads(txt[txt.index('{'):txt.rstrip().rstrip(';').rindex('}')+1])

for k, d in data.items():
    c = d["corners"]; N = SIZE
    # per-output-pixel lon/lat via bilinear over tile corners (nw,ne,sw,se)
    us = (np.arange(N)+0.5)/N; vs = (np.arange(N)+0.5)/N
    U, V = np.meshgrid(us, vs)                       # U: west->east, V: north->south
    tLon = c["nw"][0] + (c["ne"][0]-c["nw"][0])*U;  tLat = c["nw"][1] + (c["ne"][1]-c["nw"][1])*U
    bLon = c["sw"][0] + (c["se"][0]-c["sw"][0])*U;  bLat = c["sw"][1] + (c["se"][1]-c["sw"][1])*U
    LON = tLon + (bLon-tLon)*V;  LAT = tLat + (bLat-tLat)*V
    n = 256*(2**Z)
    MX = (LON+180.0)/360.0*n
    s = np.sin(np.radians(LAT)); MY = (0.5 - np.log((1+s)/(1-s))/(4*math.pi))*n
    x0, x1 = int(MX.min()//256), int(MX.max()//256)
    y0, y1 = int(MY.min()//256), int(MY.max()//256)
    frames = []; hashes = []
    for date, rid in picks:
        mos = Image.new("RGB", ((x1-x0+1)*256, (y1-y0+1)*256))
        ok = True
        for tx in range(x0, x1+1):
            for ty in range(y0, y1+1):
                try:
                    b = getbytes(tile_url(rid, Z, tx, ty))
                    mos.paste(Image.open(io.BytesIO(b)).convert("RGB"), ((tx-x0)*256, (ty-y0)*256))
                except Exception:
                    ok = False
        if not ok:
            continue
        arr = np.asarray(mos)
        px = (MX - x0*256).clip(0, mos.width-1).astype(int)
        py = (MY - y0*256).clip(0, mos.height-1).astype(int)
        out = arr[py, px]                            # nearest-sample resample to tile grid
        im = Image.fromarray(out.astype(np.uint8))
        buf = io.BytesIO(); im.save(buf, "JPEG", quality=82)
        jpg = buf.getvalue()
        h = hashlib.md5(np.asarray(im.resize((32, 32))).tobytes()).hexdigest()[:8]
        # dedupe near-identical consecutive frames
        thumb = np.asarray(im.resize((24, 24)), dtype=np.int16)
        dup = any(np.abs(thumb - t).mean() < 6 for t in hashes)
        if dup:
            continue
        hashes.append(thumb)
        frames.append({"date": date, "b64": base64.b64encode(jpg).decode()})
    d["wayback"] = frames
    print(f"[{k}] {len(picks)} dates -> {len(frames)} distinct frames: " + ", ".join(f['date'] for f in frames))

with open("terrain_data.js", "w") as f:
    f.write("window.TERRAIN = " + json.dumps(data) + ";\n")
print("wrote terrain_data.js")
