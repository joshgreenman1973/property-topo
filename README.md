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
| Tree canopy | USGS 3DEP LiDAR point clouds ([MA_CentralEastern_2021](https://www.sciencebase.gov/catalog), NY_SouthEast4County_A22 2022) | Computed directly from the raw LAZ point clouds: max return height per 1 m cell minus the bare-earth grid (same flights as the terrain). Trees = canopy ≥ 2.5 m, building footprints excluded. Encoded in half-meter steps. Replaces an earlier 2013-14 version (leaf-off Sandy-era LiDAR that underestimated canopy tops). |
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

## Derived layers

- **Slope** — per-pixel gradient of the 1 m elevation grid (central differences), shown in
  degrees: green ≈ flat, yellow ≈ 15–25°, red ≈ 45°+. Hover reads the exact value.
- **Aspect** — the compass direction each slope faces (downhill direction): blue N, green E,
  gold S, purple W; near-flat ground (<2°) is gray. South-facing slopes get the most sun.
- **Sun** — modeled average direct-sun hours per day over the year, from the horizon method:
  for 12 representative days × half-hourly sun positions at the site latitude, each cell is
  lit if the sun clears its local terrain horizon; cells under tree canopy (≥2.5 m) are put in
  deep shade. Bright = open, sunny ground; dark = shaded. A model (within-tile terrain +
  canopy), not a measurement — the layer for siting a garden or panels.
- **Relief** — the headline figure is highest minus lowest ground elevation **within the
  parcel boundary**; the secondary figure is the same range across the whole square view
  tile (parcel + context margin). Parcel extremes cross-checked against the USGS EPQS
  point-elevation service (agreement to the centimeter).
- **Drainage paths** — D8 flow accumulation over the 1 m grid: each cell drains to its
  steepest neighbor; traces are drawn where ≥150 upslope cells feed through, clipped to the
  parcel. These are ephemeral runoff concentration paths, not mapped streams.
- **Real sun by date & time** — NOAA solar-position formulas (declination + hour angle) for
  the property's latitude, local solar time; sunlight dims and warms near the horizon and
  the scene falls to ambient after sunset. Accurate to ~1°, ignores the equation of time.
- **Viewshed** — 720 sight rays swept from an observer 2 m above ground at the house,
  against the bare-earth surface, clipped to the parcel. Terrain-only: trees and buildings
  are not occluders, so it is the cleared/leaf-off upper bound on visibility.
- **Elevation profile** — click two points; the cross-section samples the 1 m grid every
  ~0.4% of the line and reports length, high/low, climb and descent.
- **Visible landmarks** — named features (peaks, water, cliffs, islands, lighthouses) that are
  in true line of sight from the house, computed over a regional bare-earth DEM (3DEP, ~100 m)
  with Earth-curvature and refraction. Labels float toward each one's bearing with its distance;
  faint sightlines run from the house. Bare-earth — tree cover can block a view the terrain
  allows. (Cornwall correctly sees Butter Hill/Storm King, not the Hudson — the ridge blocks it.)
- **Adjoining owners** — parcels intersecting the property boundary, from the same assessor
  services (owner of record, site address, acreage — all public record), drawn as a
  color-coded plat mosaic with matching labels and list swatches. Assessor-layer duplicates
  of the subject parcel are filtered; unattributed neighbors are labeled "no owner on
  public roll."
- **Soils** — USDA SSURGO map units intersecting the parcel (Soil Data Access spatial SQL),
  draped in color with series name, natural drainage class, and the USDA septic-field
  interpretation for the dominant component. Map-unit level, not site-specific.
- **Administrative geography** — census tract, county, and the local incorporated area
  (Aquinnah *town*; Cornwall-on-Hudson *village* — the closest equivalent to an NYC NTA for
  places this size) from the US Census Bureau geocoder, shown in the coordinates panel.
- **Flood zone** — FEMA National Flood Hazard Layer zone at the parcel center.
- **Wetlands** — USFWS National Wetlands Inventory presence within ~250 m.
- **Geology** — Macrostrat map units at the parcel center (surface unit + bedrock, with ages).

## Caveats & confidence

- **Elevation is bare-earth**, so buildings and tree canopy are removed from the ground
  surface. The buildings are added back separately as 3D blocks placed on that surface.
- **Buildings** — real footprint and location; walls rise to the eave and a gabled roof to
  the ridge, oriented along the footprint's long axis. Aquinnah's eave (5.8 m) and ridge
  (8.3 m) are measured from building-classified LiDAR returns (892 points); Cornwall's roof
  returns are hidden under tree canopy, so its form is estimated from the FEMA height
  (eave ≈ 70%, ridge = measured building height). Roof color is sampled from the aerial
  photo. The gable is an idealization — real roofs may be hipped or more complex.
- **Construction history** (facts panel) — year built, style, stories, areas, rooms and
  systems from the town/county assessor records (Aquinnah FY2025; Orange County 2025 roll).
- **Seasons** — purely visual simulation: fall foliage palette in ~8 m crown patches,
  winter snow (ground, roofs, frost-gray canopy) and cold light, spring leaf-out. No
  measurement changes; if "real sun" is on, the month follows the season.
- **House materials** — wall and roof colors are set from ground truth: Aquinnah from an
  owner photo (weathered gray cedar shingle, ~#a39a90 walls); Cornwall from the real-estate
  listing + aerial (1975 natural-wood contemporary with a dark roof). Snow-swapped in winter.
- **Decks** — the Aquinnah house's large west-side deck (raised wood platform, fascia and
  railing) is placed from the owner's aerial/photo. Approximate footprint, not a survey.
- **Wildlife** — species recorded within ~3 km in [GBIF](https://www.gbif.org) (mostly eBird
  + iNaturalist), grouped into birds/mammals/amphibians/reptiles with observation counts,
  species richness and the most-reported species. Citizen-science sampling over-records birds
  and under-records mammals/reptiles — low counts mean under-observed, not absent. This is the
  neighborhood's fauna, not a parcel survey.
- **Cornwall's house appears in FEMA's data as two separate footprints** 5.4 m apart. The
  LiDAR shows 4–12 m returns over the gap — tree canopy arching over the middle of the
  house — so FEMA's imagery-based extraction couldn't see the connecting section. The
  assessor records one dwelling (3,518 sq ft living ≈ the two footprints × 2 stories) and
  the owner confirms one building, so footprints within 8 m are clustered as one building
  and joined by an **inferred connector** (5 m wide, at the lower wing's height). The
  connector's exact shape is not measured — it is marked as inferred in the data. Its form
  (a cylindrical rotunda with a conical roof linking the two rectangular wings) is set from
  the owner's first-hand description.
- **Acreage** shown is computed from the polygon (shoelace on UTM coordinates); the
  assessor's stated acreage is shown alongside for comparison. Small differences are normal
  (survey vs. GIS digitizing).
- **Vertical exaggeration** defaults to 1.5× to make gentle terrain readable; set it to 1×
  for true-to-life proportions. Elevation *numbers* are always real regardless of exaggeration.
- Parcel boundaries are assessor/GIS data, **not a survey**; treat the line as approximate
  (typically within a few meters).
- Lat/long hover uses bilinear interpolation across the tile corners — accurate to well
  under a meter at this scale.
- **Trees**: both *where* trees are and *how tall* come from the newest USGS LiDAR flights
  (Aquinnah 2021, Cornwall 2022), computed from the raw point clouds: any 1 m cell with
  vegetation ≥ 2.5 m above ground is drawn as a translucent canopy surface at its measured
  height (buildings excluded), readable per-spot via hover. Both parcels are densely wooded
  (~72–80% canopy; Cornwall p95 ≈ 26 m, Aquinnah ≈ 17 m). Two earlier versions are
  superseded: tree *locations* from aerial-photo greenness (failed on Cornwall's leaf-off
  ortho) and *heights* from 2013-14 Sandy-era LiDAR (leaf-off, low density — underestimated
  canopy tops by ~10 m on Cornwall). The aerial-photo drape still shows the leaf-off look;
  summer imagery (e.g. Google) shows the dense cover the LiDAR confirms. **No streams or
  ponds** were found on either parcel (confirmed against the aerial imagery and hydrography).
- The published data is address, town, acreage, boundary, elevation, and — added at the
  owner's request — the **names of record and lot sizes of adjoining parcels** (public
  assessor data). Assessed values and mailing addresses are not included.

## Run locally

```
python3 -m http.server 8531
# open http://localhost:8531
# to refresh the elevation/parcel data: pip install numpy pillow pyproj && python3 fetch_parcels.py
```
