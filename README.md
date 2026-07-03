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

- **Elevation is bare-earth**, so buildings and tree canopy are not represented — this is
  the ground surface.
- **Acreage** shown is computed from the polygon (shoelace on UTM coordinates); the
  assessor's stated acreage is shown alongside for comparison. Small differences are normal
  (survey vs. GIS digitizing).
- **Vertical exaggeration** defaults to 1.5× to make gentle terrain readable; set it to 1×
  for true-to-life proportions. Elevation *numbers* are always real regardless of exaggeration.
- Parcel boundaries are assessor/GIS data, **not a survey**; treat the line as approximate
  (typically within a few meters).
- Lat/long hover uses bilinear interpolation across the tile corners — accurate to well
  under a meter at this scale.
- Only geographic data is published here (address, town, acreage, boundary, elevation).
  Owner names, assessed values and mailing addresses from the assessor records are **not**
  included.

## Run locally

```
python3 -m http.server 8531
# open http://localhost:8531
# to refresh the elevation/parcel data: pip install numpy pillow pyproj && python3 fetch_parcels.py
```
