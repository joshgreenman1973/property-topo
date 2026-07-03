# Property topography — parcel-shaped 3D terrain

Interactive 3D topographic viewers for two properties, clipped to their actual legal
parcel boundaries. Rotate, tilt, zoom; toggle contours, the property line and compass
labels; hover the terrain for live latitude / longitude / elevation.

- **32 Old South Road, Aquinnah, MA 02535** (Martha's Vineyard, up-island)
- **10 Abbott Lane, Cornwall-on-Hudson, NY 12520** (Hudson Highlands, below Storm King)

## Data sources (nothing is a black box)

| Layer | Source | Notes |
|---|---|---|
| Elevation | [USGS 3DEP](https://www.usgs.gov/3d-elevation-program) `3DEPElevation/ImageServer` | LiDAR-derived bare-earth DEM, requested at ~1 m/pixel over each parcel's bounding box. Values are meters above the vertical datum (NAVD88). |
| MA parcel boundary | [MassGIS Standardized Assessors' Parcels (L3)](https://www.mass.gov/info-details/massgis-data-property-tax-parcels) | Boundary polygon + assessor record (address, town, acreage). |
| NY parcel boundary | [NYS Tax Parcels Public](https://gis.ny.gov/parcels) (Orange County, 2025 roll) | Boundary polygon + assessor record. |
| Building footprints | [FEMA USA Structures](https://gis-fema.hub.arcgis.com/pages/usa-structures) (Oak Ridge / USGS) | Footprints >450 sq ft with LiDAR-derived `HEIGHT`. Where height is missing, estimated from the assessor's story count. |
| Aerial photo | [Esri World Imagery](https://www.arcgis.com/home/item.html?id=10df2279f9684e4a9f6a7f08febac2a9) | ~1 m ortho, exported for the same tile as the DEM and draped on the 3D surface. |
| Tree canopy | derived from the aerial photo | Vegetation = excess-green index (2G−R−B); trees = green **and** textured (rough canopy) vs. smooth mown/bare ground. Approximate, not a LiDAR canopy model. |
| Roads | [OpenStreetMap](https://www.openstreetmap.org) via Overpass API | All `highway` ways in the tile, draped on the terrain as ribbons with approximate widths by class (trunk ≈9 m … driveway ≈3 m). Road data © OpenStreetMap contributors. |

## Method

1. Geocode each address, then query the authoritative county/state parcel service to pull
   the **real boundary polygon** and confirm address, town and acreage.
2. Reproject the polygon to UTM (zone 19N for MA, 18N for NY) so distances are true meters.
3. Fetch a square 1 m DEM covering the parcel bounding box plus a ~14% context margin.
4. Build a triangular terrain mesh from the DEM and **clip it to the parcel polygon**, so
   the 3D shape is the shape of the lot — not a square crop.
5. Drape the parcel boundary onto the surface, add vertical "skirt" walls, N/S/E/W markers,
   a contour shader, and a bilinear pixel→lat/long mapping for the hover readout.

`fetch_parcels.py` performs steps 1–4 and writes `terrain_data.js` (elevation grids +
polygons, base64-packed). `index.html` is a self-contained three.js viewer.

## Caveats & confidence

- **Elevation is bare-earth**, so buildings and tree canopy are removed from the ground
  surface. The buildings are added back separately as 3D blocks placed on that surface.
- **Buildings are LOD1 blocks** — real footprint and location, extruded to a single flat-roof
  height. Height is LiDAR-measured where FEMA provides it (Cornwall's two structures, ~7 m),
  otherwise estimated from the assessor's story count (Aquinnah, 2.5 stories → ~8 m). Roof
  pitch and architectural detail are not modeled.
- **Acreage** shown is computed from the polygon (shoelace on UTM coordinates); the
  assessor's stated acreage is shown alongside for comparison. Small differences are normal
  (survey vs. GIS digitizing).
- **Vertical exaggeration** defaults to 1.5× to make gentle terrain readable; set it to 1×
  for true-to-life proportions. Elevation *numbers* are always real regardless of exaggeration.
- Parcel boundaries are assessor/GIS data, **not a survey**; treat the line as approximate
  (typically within a few meters).
- Lat/long hover uses bilinear interpolation across the tile corners — accurate to well
  under a meter at this scale.
- **Trees** are inferred from summer aerial imagery (greenness + canopy texture), so the
  layer is approximate and can miss individual trees or catch dense shrubs. USGS/IO 10 m land
  cover classes both entire parcels as forest; the derived layer's value is showing the
  *cleared* homesite areas within that forest. **No streams or ponds** were found on either
  parcel (confirmed against the aerial imagery and hydrography).
- Only geographic data is published here (address, town, acreage, boundary, elevation).
  Owner names, assessed values and mailing addresses from the assessor records are **not**
  included.

## Run locally

```
python3 -m http.server 8531
# open http://localhost:8531
# to refresh the elevation/parcel data: pip install numpy pillow pyproj && python3 fetch_parcels.py
```
