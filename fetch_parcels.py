#!/usr/bin/env python3
"""Fetch real parcel polygons + DEM clipped to each lot, pack to terrain_data.js."""
import urllib.request, urllib.parse, io, json, base64, math
import numpy as np
from PIL import Image
from pyproj import Transformer

def q(url, params):
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={'User-Agent': 'topo/1.0'})
    return json.load(urllib.request.urlopen(req, timeout=90))

PROPS = [
    {
        "id": "aquinnah",
        "label": "32 Old South Road",
        "town": "Aquinnah, MA 02535",
        "acres_src": 9.58,
        "utm_epsg": 32619,
        "parcel_url": "https://arcgisserver.digital.mass.gov/arcgisserver/rest/services/AGOL/MassachusettsPropertyTaxParcels/FeatureServer/1/query",
        "where": "LOC_ID='M_257897_787708'",
        # FEMA had no LiDAR height for this building; assessor says 2.5 stories -> ~8 m
        "fallback_height": 8.0, "fallback_src": "est. from 2.5 stories (assessor)",
    },
    {
        "id": "cornwall",
        "label": "10 Abbott Lane",
        "town": "Cornwall-on-Hudson, NY 12520",
        "acres_src": 9.60,
        "utm_epsg": 32618,
        "parcel_url": "https://gisservices.its.ny.gov/arcgis/rest/services/NYS_Tax_Parcels_Public/FeatureServer/1/query",
        "where": "PRINT_KEY='124-1-16.1' AND MUNI_NAME='Cornwall-on-Hudson'",
        "fallback_height": 7.0, "fallback_src": "est. 2-story default",
    },
]

FEMA_URL = ("https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/"
            "USA_Structures_View/FeatureServer/0/query")

DEM_SERVICE = ("https://elevation.nationalmap.gov/arcgis/rest/services/"
               "3DEPElevation/ImageServer/exportImage")
PAD = 0.14        # fraction of parcel extent added as context margin
MAX_PX = 380      # cap DEM grid dimension

out = {}
for p in PROPS:
    # 1. parcel polygon in lon/lat
    r = q(p["parcel_url"], {"where": p["where"], "outFields": "*",
                            "returnGeometry": "true", "outSR": "4326", "f": "json"})
    feat = r["features"][0]
    rings_ll = feat["geometry"]["rings"]           # list of rings, each [ [lon,lat], ... ]
    outer_ll = max(rings_ll, key=len)              # largest ring = outer boundary

    fwd = Transformer.from_crs(4326, p["utm_epsg"], always_xy=True)
    inv = Transformer.from_crs(p["utm_epsg"], 4326, always_xy=True)
    rings_utm = [[fwd.transform(lon, lat) for lon, lat in ring] for ring in rings_ll]
    outer_utm = max(rings_utm, key=len)
    xs = [x for x, y in outer_utm]; ys = [y for x, y in outer_utm]
    minE, maxE, minN, maxN = min(xs), max(xs), min(ys), max(ys)
    # square bbox centered on parcel bbox center, padded
    cE, cN = (minE + maxE) / 2, (minN + maxN) / 2
    ext = max(maxE - minE, maxN - minN)
    half = ext * (1 + 2 * PAD) / 2
    bbE0, bbE1, bbN0, bbN1 = cE - half, cE + half, cN - half, cN + half

    # 2. DEM over square bbox
    size = min(int(round(2 * half)), MAX_PX)
    res = (2 * half) / size
    bbox = f"{bbE0},{bbN0},{bbE1},{bbN1}"
    url = (f"{DEM_SERVICE}?bbox={bbox}&bboxSR={p['utm_epsg']}"
           f"&size={size},{size}&imageSR={p['utm_epsg']}"
           "&format=tiff&pixelType=F32&interpolation=RSP_BilinearInterpolation&f=image")
    print(f"[{p['id']}] parcel verts={len(outer_ll)} bbox={2*half:.0f} m  size={size}px res={res:.2f} m")
    req = urllib.request.Request(url, headers={'User-Agent': 'topo/1.0'})
    arr = np.array(Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=90).read())), dtype=np.float32)
    arr[arr < -1e5] = np.nan
    if np.isnan(arr).any():
        arr[np.isnan(arr)] = np.nanmin(arr)
    # ArcGIS row0 = NORTH (maxN). keep that orientation.
    zmin, zmax = float(arr.min()), float(arr.max())
    print(f"    elev {zmin:.1f}-{zmax:.1f} m  relief {zmax-zmin:.1f} m")

    # 3. polygon -> local mesh coords: x = E-cE (east +), z = -(N-cN) (north = -Z)
    def to_mesh(E, N): return [E - cE, -(N - cN)]
    poly_mesh = [[to_mesh(x, y) for x, y in ring] for ring in rings_utm]
    outer_mesh = max(poly_mesh, key=len)

    # 4. corner lat/lons (NW,NE,SW,SE) for on-the-fly readouts
    corners = {
        "nw": list(inv.transform(bbE0, bbN1)), "ne": list(inv.transform(bbE1, bbN1)),
        "sw": list(inv.transform(bbE0, bbN0)), "se": list(inv.transform(bbE1, bbN0)),
    }
    center_ll = list(inv.transform(cE, cN))

    # parcel true area (shoelace on UTM outer ring), acres
    A = abs(sum(outer_utm[i][0]*outer_utm[i+1][1] - outer_utm[i+1][0]*outer_utm[i][1]
                for i in range(len(outer_utm)-1))) / 2.0
    acres = A / 4046.8564224

    # 5. building footprints on the parcel (FEMA USA Structures)
    poly4326 = {"rings": [outer_ll], "spatialReference": {"wkid": 4326}}
    fb = q(FEMA_URL, {"geometry": json.dumps(poly4326), "geometryType": "esriGeometryPolygon",
                      "inSR": "4326", "outSR": "4326", "spatialRel": "esriSpatialRelIntersects",
                      "outFields": "BUILD_ID,HEIGHT,OCC_CLS,PRIM_OCC,SQFEET", "returnGeometry": "true", "f": "json"})
    buildings = []
    for f in fb.get("features", []):
        a = f["attributes"]
        h = a.get("HEIGHT")
        if h and h > 1.5:
            height, hsrc = float(h), "LiDAR (FEMA USA Structures)"
        else:
            height, hsrc = p["fallback_height"], p["fallback_src"]
        ring_ll = max(f["geometry"]["rings"], key=len)
        ring_mesh = [to_mesh(*fwd.transform(lon, lat)) for lon, lat in ring_ll]
        buildings.append({
            "mesh": ring_mesh, "lonlat": ring_ll,
            "height": round(height, 1), "height_src": hsrc,
            "occ": a.get("PRIM_OCC"), "sqft": round(a.get("SQFEET") or 0),
        })
    print(f"    buildings: {len(buildings)} -> " +
          ", ".join(f"{b['occ']} {b['sqft']}sf h={b['height']}m" for b in buildings))

    # 6. aerial ortho (Esri World Imagery) for the photo drape + tree detection
    ao = ("https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/export"
          f"?bbox={bbox}&bboxSR={p['utm_epsg']}&size={size},{size}&imageSR={p['utm_epsg']}&format=jpg&f=image")
    jpg = urllib.request.urlopen(urllib.request.Request(ao, headers={'User-Agent': 'topo/1.0'}), timeout=90).read()
    rgb = np.asarray(Image.open(io.BytesIO(jpg)).convert('RGB')).astype(np.float32)  # row0 = north, matches DEM
    R, G, B = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    exg = 2*G - R - B                       # excess-green vegetation index
    gray = (R + G + B) / 3.0
    gx = np.abs(np.diff(gray, axis=1, prepend=gray[:, :1]))
    gy = np.abs(np.diff(gray, axis=0, prepend=gray[:1, :]))
    tex = gx + gy                           # local roughness: tree canopy is rough, mown lawn is smooth
    def smooth(a): return (a + np.roll(a, 1, 0) + np.roll(a, -1, 0) + np.roll(a, 1, 1) + np.roll(a, -1, 1)) / 5.0
    tex_s = smooth(smooth(tex))
    veg = exg > 22
    thr = float(np.percentile(tex_s[veg], 33)) if veg.any() else 0.0
    tree = (veg & (tex_s > thr)).astype(np.uint8)   # green AND textured -> woody canopy
    print(f"    aerial {len(jpg)//1024} KB  tree cover {tree.mean()*100:.0f}% of tile")

    out[p["id"]] = {
        "id": p["id"], "label": p["label"], "town": p["town"],
        "acres": round(acres, 2), "acres_assessor": p["acres_src"],
        "half": half, "size": size, "res": res,
        "zmin": zmin, "zmax": zmax,
        "center_lonlat": center_ll, "corners": corners,
        "poly_mesh": poly_mesh,          # rings in mesh xz
        "poly_lonlat": rings_ll,         # rings in lon/lat
        "buildings": buildings,          # footprints (mesh xz) + heights
        "aerial_b64": base64.b64encode(jpg).decode(),        # ortho photo (jpg) for the drape
        "tree_b64": base64.b64encode(tree.tobytes()).decode(),  # uint8 tree mask, row0=north
        "heights_b64": base64.b64encode(arr.astype('<f4').tobytes()).decode(),
    }

with open("terrain_data.js", "w") as f:
    f.write("window.TERRAIN = " + json.dumps(out) + ";\n")
print("wrote terrain_data.js")
