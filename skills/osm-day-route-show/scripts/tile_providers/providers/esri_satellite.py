"""Esri's public World_Imagery REST tiles (satellite) — same trusted host
as esri_street, genuinely unique high-res data through z20+ at the point
tested in tile-providers-research.md. Worldwide Esri REST service —
treated as always available, same reasoning as esri_street."""
from .base import TileProviderPlugin


class EsriSatelliteProvider(TileProviderPlugin):
    provider_id = "esri_satellite"
    display_name = "Esri Satellite"
    tile_url_template = ("https://server.arcgisonline.com/ArcGIS/rest/services/"
                          "World_Imagery/MapServer/tile/{z}/{y}/{x}")
    attribution = ("Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, "
                   "and the GIS User Community")
    max_zoom = 20
    max_native_zoom = 20
    always_available = True
