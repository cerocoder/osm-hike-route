"""IGN España's MTN (Mapa Topografico Nacional) layer via WMTS KVP
addressing — official Spanish government topographic map. Region-limited
by nature (Spain only), so always live-probed, never always_available.
Exact query-string parameters sourced from tile-providers-research.md's
working example (2026-09-28) — reconfirm with a real rendered map before
trusting in production, per this skill's own established verification
bar (SKILL.md Common Mistakes: curl alone has missed a cache-masked
block before)."""
from .base import TileProviderPlugin


class IgnEsMtnProvider(TileProviderPlugin):
    provider_id = "ign_es_mtn"
    display_name = "IGN España (MTN)"
    tile_url_template = (
        "https://www.ign.es/wmts/mapa-raster?service=WMTS&request=GetTile"
        "&version=1.0.0&layer=MTN&style=default&format=image/jpeg"
        "&TileMatrixSet=GoogleMapsCompatible&TileMatrix={z}&TileRow={y}&TileCol={x}"
    )
    attribution = "CC-BY 4.0 ign.es"
    max_zoom = 19
    max_native_zoom = 19
    always_available = False
