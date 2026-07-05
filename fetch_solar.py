#!/usr/bin/env python3
"""Compute an average direct-sun-hours-per-day grid for each parcel, accounting for
terrain self-shading (horizon method) and tree canopy (cells under trees get deep shade).
Stored as uint8 (sun-hours x10) in terrain_data.js."""
import json, base64, math
import numpy as np

txt = open("terrain_data.js").read()
data = json.loads(txt[txt.index('{'):txt.rstrip().rstrip(';').rindex('}') + 1])

AZ_N = 24                       # horizon azimuth bins
MONTHS = [15, 46, 74, 105, 135, 166, 196, 227, 258, 288, 319, 349]  # mid-month day-of-year
HOURS = np.arange(4.0, 20.01, 0.5)

def sun_pos(lat, doy, hour):
    dec = math.radians(23.44 * math.sin(2*math.pi*(284+doy)/365))
    lr = math.radians(lat); H = math.radians((hour-12)*15)
    sinel = math.sin(lr)*math.sin(dec) + math.cos(lr)*math.cos(dec)*math.cos(H)
    el = math.asin(max(-1, min(1, sinel)))
    az = math.atan2(math.sin(H), math.cos(H)*math.sin(lr) - math.tan(dec)*math.cos(lr)) + math.pi
    return (math.degrees(az) % 360), math.degrees(el)

for k, d in data.items():
    N, half = d["size"], d["half"]
    res = 2*half/N
    lat = d["center_lonlat"][1]
    Z = np.frombuffer(base64.b64decode(d["heights_b64"]), dtype="<f4").reshape(N, N).astype(np.float32)
    canopy = (np.frombuffer(base64.b64decode(d["canopy_b64"]), dtype=np.uint8).reshape(N, N).astype(np.float32)/2
              if d.get("canopy_b64") else np.zeros((N, N), np.float32))

    # horizon angle per cell for each azimuth (direction TOWARD the sun)
    az_list = np.arange(0, 360, 360/AZ_N)
    horizons = np.zeros((AZ_N, N, N), np.float32)
    maxstep = int(N*0.9)
    for ai, A in enumerate(az_list):
        dx = math.sin(math.radians(A)); dz = -math.cos(math.radians(A))
        hz = np.full((N, N), -1.5, np.float32)
        step = 1
        while step < maxstep:
            ro = -int(round(dz*step)); co = -int(round(dx*step))
            if ro == 0 and co == 0:
                step += 1; continue
            ahead = np.roll(np.roll(Z, ro, axis=0), co, axis=1)
            ang = np.arctan2(ahead - Z, step*res)
            np.maximum(hz, ang, out=hz)
            step = step + 1 if step < 8 else step + 2   # coarser far out
        horizons[ai] = hz

    # accumulate lit half-hours across 12 representative days, then average
    lit = np.zeros((N, N), np.float32)
    for doy in MONTHS:
        for h in HOURS:
            az, el = sun_pos(lat, doy, h)
            if el <= 1.0:
                continue
            ai = int(round(az/(360/AZ_N))) % AZ_N
            lit += ((math.radians(el) > horizons[ai]) * 0.5).astype(np.float32)
    sun_hours = lit / len(MONTHS)              # avg direct-sun hours/day (terrain only)
    sun_hours *= np.where(canopy >= 2.5, 0.12, 1.0)   # deep shade under trees

    enc = np.clip(np.round(sun_hours*10), 0, 255).astype(np.uint8)
    d["solar_b64"] = base64.b64encode(enc.tobytes()).decode()
    openpx = sun_hours[canopy < 2.5]
    p90 = float(np.percentile(openpx, 90)) if openpx.size else 0
    print(f"[{k}] sun-hours/day: open-ground p90={p90:.1f}h, tile max={sun_hours.max():.1f}h")

with open("terrain_data.js", "w") as f:
    f.write("window.TERRAIN = " + json.dumps(data) + ";\n")
print("wrote terrain_data.js")
