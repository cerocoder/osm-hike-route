"""Esri's public World_Street_Map REST tiles — already the production
base layer before this plugin system existed (SKILL.md Common Mistakes:
tile.openstreetmap.org, CARTO Voyager, and Wikimedia osm-intl were all
tried first and rejected). Worldwide Esri REST service — treated as
always available, same as esri_satellite."""
from .base import TileProviderPlugin


class EsriStreetProvider(TileProviderPlugin):
    provider_id = "esri_street"
    display_name = "Esri Street Map"
    tile_url_template = ("https://server.arcgisonline.com/ArcGIS/rest/services/"
                          "World_Street_Map/MapServer/tile/{z}/{y}/{x}")
    attribution = ("Tiles &copy; Esri &mdash; Source: Esri, DeLorme, NAVTEQ, USGS, "
                   "Intermap, iPC, NRCAN, Esri Japan, METI, Esri China (Hong Kong), "
                   "Esri (Thailand), TomTom")
    max_zoom = 19
    max_native_zoom = 19
    always_available = True
