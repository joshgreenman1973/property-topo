#!/usr/bin/env python3
"""Individual trees from the LiDAR canopy height grid already in terrain_data.js.

Each tree is a crown top: a local maximum of the (lightly smoothed) canopy height
model, found with a search window that grows with tree height (small trees have
small crowns). A watershed from those tops over the inverted canopy surface gives
each crown its extent; the crown radius is that of a circle of equal area, capped.
Only crowns at least 5 m tall and inside the parcel are kept; the CHM is 1 m, so
this resolves the canopy-dominant trees, not the understory beneath them.

Writes d["trees"] = {src, n, items:[[x, z, h, r], ...]} in mesh meters (x east,
z south, h height m, r crown radius m) and leaves everything else untouched.
"""
import json, base64, re
import numpy as np
from scipy import ndimage
from skimage.segmentation import watershed
from matplotlib.path import Path

MIN_H = 5.0        # m: anything shorter is sapling / shrub
txt = open("terrain_data.js").read()
head = txt[:txt.index('{')]
data = json.loads(txt[txt.index('{'):txt.rstrip().rstrip(';').rindex('}') + 1])

for key, d in data.items():
    N, half, res = d["size"], d["half"], d["res"]
    chm = np.frombuffer(base64.b64decode(d["canopy_b64"]), dtype=np.uint8).reshape(N, N) / 2.0
    tm = np.frombuffer(base64.b64decode(d["tree_b64"]), dtype=np.uint8).reshape(N, N) > 0
    chm = np.where(tm, chm, 0.0)
    sm = ndimage.gaussian_filter(chm, 0.8)
    # crown tops: local maxima, window scaled to height band
    peaks = []
    for rad, lo, hi in [(2, MIN_H, 12), (3, 12, 20), (4, 20, 99)]:
        mx = ndimage.maximum_filter(sm, size=2 * rad + 1)
        ys, xs = np.where((sm == mx) & (sm >= lo) & (sm < hi))
        peaks += [(int(y), int(x), float(sm[y, x])) for y, x in zip(ys, xs)]
    peaks.sort(key=lambda t: -t[2])
    kept = []
    for y, x, h in peaks:   # two tops within 2 m are one tree
        if all((y - ky) ** 2 + (x - kx) ** 2 >= 4 for ky, kx, _ in kept):
            kept.append((y, x, h))
    # crown extents: watershed from the tops over the inverted canopy, within canopy >= 2.5 m
    markers = np.zeros((N, N), dtype=np.int32)
    for i, (y, x, _) in enumerate(kept, 1):
        markers[y, x] = i
    seg = watershed(-sm, markers, mask=chm >= 2.5)
    areas = np.bincount(seg.ravel(), minlength=len(kept) + 1)
    ring = max(d["poly_mesh"], key=len)
    P = Path(ring)
    items = []
    for i, (y, x, h) in enumerate(kept, 1):
        mx_, mz_ = -half + (x + 0.5) * res, -half + (y + 0.5) * res
        if not P.contains_point((mx_, mz_)):
            continue
        r = float(np.sqrt(areas[i] / np.pi)) * res
        r = max(1.2, min(r, 0.35 * h, 9.0))          # a crown is never wider than ~70% of its height
        items.append([round(mx_, 1), round(mz_, 1), round(h, 1), round(r, 1)])
    items.sort(key=lambda t: -t[2])
    hs = np.array([t[2] for t in items])
    d["trees"] = {"src": f"crown tops detected in the {d['canopy_yr']} LiDAR canopy grid (1 m); canopy-dominant trees >= {MIN_H:g} m, understory not resolved",
                  "n": len(items), "median_h": round(float(np.median(hs)), 1), "max_h": round(float(hs.max()), 1),
                  "items": items}
    print(f"{key}: {len(items)} trees on parcel, median {np.median(hs):.1f} m, tallest {hs.max():.1f} m, "
          f"crown r median {np.median([t[3] for t in items]):.1f} m")

open("terrain_data.js", "w").write(head + json.dumps(data, separators=(',', ':')) + ";\n")
