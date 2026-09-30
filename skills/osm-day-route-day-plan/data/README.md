# Radiation registry (`radiation_zones.json`)

A hand-curated list of contaminated or closed zones, read by
`scripts/day_plan/radiation.py`. It is static: nothing here is fetched at run time.

## Entry format

```json
{
  "id": "unique-slug",
  "severity": "danger | caution | info",
  "advice": "full | mushrooms",
  "approximate": true,
  "name": {"en": "...", "ru": "..."},
  "contamination": {"en": "...", "ru": "..."},
  "status": {"en": "...", "ru": "..."},
  "event": {"en": "short: Chernobyl accident, 1986", "ru": "..."},
  "geometry": {"type": "polygons", "rings": [[[lon, lat], "..."]]},
  "geometry_note": {"en": "...", "ru": "..."},
  "sources": [{"url": "https://...", "title": "...", "kind": "primary | secondary"}]
}
```

- `severity`: `danger` for land that is closed or heavily contaminated (a route
  entering it raises a danger warning); `caution` for a wider affected area
  (a caution warning); `info` for an advisory area (an info line only, and
  only when the route is inside it).
- `advice`: `full` (no mushrooms or berries, no natural water, no dust or open
  fires, wind and wildfire) or `mushrooms` (moderation and local advice, for
  advisory areas such as the Bavarian mushroom areas). `danger` zones need
  `full`, `info` zones use `mushrooms`.
- Geometry is one of `polygons` (a list of closed outer rings), `circle`
  (`center` `[lon, lat]`, `radius_km`) or `buffered_polyline` (`lines`,
  `half_width_km`). Coordinates are `[longitude, latitude]`.
- `scope.boxes` (in the file's header) are the rectangles the registry is meant
  to cover; a route outside all of them gets no radiation part.
- `approximate` is true whenever the shape is not a published outline; the
  `geometry_note` then says how it was made. It is required for approximate
  zones and shown to the reader.
- `status` and `contamination` say only what the sources say. Every entry needs
  at least one source, and one `primary` (an official, scientific or
  regulatory document) for a zone that raises a warning.
- Outlines taken from OpenStreetMap are simplified (Douglas–Peucker, a few
  hundred metres) and credited in `geometry_note` (ODbL).
- `tests/test_radiation_registry.py` validates every entry and pins where
  each zone must lie; add the new zone's box and a known inside/outside point
  there.

## Provenance of the shipped zones

| id | geometry | sources read for this entry |
|---|---|---|
| `ural-eurt-core` | OSM way 256825533 (East Ural reserve) | NRPA Bulletin 8-07 (about 180 km² still off-limits); Wikipedia (not open to the public) |
| `ural-eurt-trace` | centre line through Bagaryak, Kamensk-Uralsky and the area between Bogdanovich and Kamyshlov (the settlements named on the NRPA figure), starting 25 km downwind of Mayak (the outline has round ends) and spanning 300 km from Mayak, half-width 25 km | NRPA Bulletin 8-07 (300 km long, 30–50 km wide, 23 communities evacuated) |
| `ural-techa-river` | OSM relation 2124164 (waterway) plus ways 1104519187, 125750492, 786464969 upstream of its west end, half-width 1.5 km; the reservoir cascade is not outlined | NRPA Report 2008:3 (floodplain 240 km², 80 km² above 3.7×10¹⁰ Bq/km²) |
| `ural-mayak-site` | circle at 55°44′N 60°54′E, r = 6 km | NRPA Report 2008:3 (site about 90 km²) |
| `ural-karachay` | circle at 55.6783°N 60.7997°E (Wikipedia), r = 3 km assumed | NRPA Report 2008:3 (1967 dispersal); Wikipedia |
| `ua-chernobyl-exclusion-zone` | OSM relation 3311547 | IAEA/UIAR presentation (evacuated in 1986, 2 122 km²) |
| `by-polesie-reserve` | OSM relation 3397849 | Order No. 39 of the Belarus Ministry for Emergency Situations, 1995 (FAOLEX) |
| `ru-bryansk-contaminated-districts` | OSM boundaries of seven districts | Radiation Hygiene 2023;16(4):55-63 (districts, mushrooms up to 75–82 % of the internal dose); Government decree No. 1074 of 8 Oct 2015 |
| `kz-semipalatinsk-test-site` | OSM way 932505322 (boundary=hazard) | National Nuclear Center of Kazakhstan, radioecological surveys |
| `ru-central-chernobyl-districts` | OSM boundaries of nine districts (Tula: Arsenyevsky, Belevsky, Plavsky, Chernsky, Shchekinsky; Kaluga: Zhizdra, Ulyanovo, Khvastovichi; Orel: Bolkhov) | Government decree No. 1074 of 8 Oct 2015 (the list itself, read at government.ru: zone of residence with the right to resettle) |
| `de-bavaria-wild-food-areas` | OSM: Bayerischer Wald region, Landkreis Berchtesgadener Land, Mittenwald, Karlshuld (stands for the Donaumoos) | BfS press release of 10 Sep 2024 (regions, 600 Bq/kg, moderate consumption harmless) |
| `no-wild-mushroom-municipalities` | OSM boundaries of seven municipalities (Innlandet: Øystre Slidre, Sel, Dovre, Folldal; Trøndelag: Lierne, Tydal; Nordland: Hattfjelldal); Orkland is sampled too but not singled out, so it is not outlined | DSA report 2/2026 (April 2026): highest caesium in wild mushrooms from the most contaminated areas of Innlandet, Trøndelag and Nordland, 17 000 Bq/kg at Øystre Slidre, no clear decline, advice 80 000 Bq a year |
| `ru-yenisei-mcc-floodplain` | OSM relation 181988 (Yenisei), main channel, first 100 km below the vertex nearest to Zheleznogorsk, half-width 2 km assumed | Scientific Reports 7:11132 (2017): floodplain contaminated, particles from the combine to more than 800 km downstream |

## Researched and not added

| Candidate | What the sources say | Why it is not in the registry |
|---|---|---|
| Totskoye 1954 (52°38′N 52°48′E) | Read (abstracts; the full texts sit behind publishers): Dubasov et al., Radium Institute, Radiochemistry 46(6), 2004 — soil plutonium has the isotopic composition of global fallout, so either no long-lived fission products from the 1954 explosion or levels within the fluctuations of global fallout; induced cobalt-60 and europium-152 only at the epicentre. Boev et al. (Orenburg, 1994 data, 1996 symposium) — plutonium in topsoil 5–20 times background, strontium and caesium 1.5 times; Gig. Sanit. 1998 — caesium higher than in a control area. | The studies disagree, give no absolute levels or area, and the largest excess of caesium is a factor of 1.5: no basis for a warning or an outline. |
| Novaya Zemlya | IAEA reference (read): raised dose rates only on small plots in three test areas (Chernaya Bay, Matochkin Shar, Sukhoy Nos); elsewhere caesium-137 about 3.3 kBq/m², the regional background. | Local plots of at most about 1 km² without published coordinates; the archipelago is a closed test site, which is an access note (`people_hazards`), not a contamination zone. |
| Seversk (Tomsk-7), 1993 | IAEA report (read): the area above 0.2 µGy/h fell from 30 km² in May 1993 to nothing by January 1994. | No lasting outline. |
| Peaceful underground explosions (Taiga 61.30°N 56.60°E, Kraton-3 65°N 112°E, Crystal 66.8°N 113.9°E, Globus-1 in the Ivanovo region) | Sites and local raised dose rates appear in search results and news (for Kraton-3 0.5–1.4 µSv/h in places against 0.08 in the forest); the survey papers were not read. | No published extents; read the surveys first. |
| Sweden and Finland | The Swedish National Food Agency (search result and press release) says berries, mushrooms and game can be eaten throughout Sweden without a health risk from caesium, levels being generally low; STUK (Finland, search results) puts Chernobyl food contamination at under 1 % of the average annual dose. | The authorities themselves see no need for an advisory; not added. |
| Peaceful explosions, measured | Ramzaev et al., J. Environ. Radioact. 92 (2007): caesium-137 at the Crystal site (Yakutia) 1.3–64 kBq/m², at Kraton-3 1.7–6900 kBq/m² (the maximum on a decontaminated plot) against a background of about 0.84 kBq/m². | Confirms real local contamination, but the paper gives no extents or coordinates of the plots; no outline. |
| Sellafield, La Hague, Andreeva Bay, Wismut, Jáchymov, Balkan depleted uranium | Not researched. | Operating or closed facilities and point hazards (radon in mine workings, penetrator fragments): access notes rather than land-contamination zones. |
