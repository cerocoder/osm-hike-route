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

    # Rough bounding boxes (lat_min, lon_min, lat_max, lon_max): mainland
    # Spain + Balearics + Ceuta/Melilla, and separately the Canary Islands.
    # IGN's MTN layer has no real data outside Spain and serves a blank
    # beige placeholder tile there that still returns HTTP 200 with a
    # plausible image/jpeg body — a live final-review check caught this
    # (Moscow/Paris/Lisbon all falsely "covered" before this pre-check
    # existed). This geography check avoids a network round-trip for the
    # common case AND fixes the false-positive the generic body-size
    # threshold in probe.py could not reliably catch.
    _SPAIN_BBOXES = [
        (35.0, -9.5, 44.0, 4.5),
        (27.0, -18.5, 29.5, -13.0),
    ]

    def covers(self, points, timeout=5.0):
        if not points:
            return False
        if not all(self._in_spain(lat, lon) for lat, lon in points):
            return False
        return super().covers(points, timeout)

    @classmethod
    def _in_spain(cls, lat, lon):
        return any(
            lat_min <= lat <= lat_max and lon_min <= lon <= lon_max
            for lat_min, lon_min, lat_max, lon_max in cls._SPAIN_BBOXES
        )
