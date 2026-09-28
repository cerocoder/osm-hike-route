"""CyclOSM — actively maintained OpenStreetMap-France infrastructure,
cycling-oriented style. Not global-by-declaration like the Esri layers,
so it's live-probed per route (tile-providers-research.md found unique
data through z19 at the one point tested, not confirmed worldwide).

NOTE: the bare host `tile-cyclosm.openstreetmap.fr` (no subdomain) does
NOT resolve (NXDOMAIN) — only the load-balanced subdomains `a.`, `b.`,
`c.tile-cyclosm.openstreetmap.fr` actually serve tiles (confirmed live
during the final whole-branch review, 2026-09-28). This was a real bug:
every CyclOSM probe failed DNS and the provider could never be offered.
Leaflet's `{s}` subdomain-rotation placeholder is intentionally NOT used
here — `probe_tile`'s `.format(z=, x=, y=)` would raise `KeyError` on an
unfilled `{s}` — so this hardcodes the single `a.` subdomain, which is a
pragmatic fix, not full load-balancing, given this project's traffic
level."""
from .base import TileProviderPlugin


class CyclOsmProvider(TileProviderPlugin):
    provider_id = "cyclosm"
    display_name = "CyclOSM"
    # NOTE: {z}/{x}/{y} order — the opposite of the two Esri templates
    # above, which use {z}/{y}/{x}. See Global Constraints / Review Focus.
    tile_url_template = "https://a.tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png"
    attribution = ('Map data &copy; <a href="https://www.openstreetmap.org/copyright">'
                   'OpenStreetMap</a> contributors, Tiles style &copy; '
                   '<a href="https://github.com/cyclosm/cyclosm-cartocss-style/releases">CyclOSM</a>')
    max_zoom = 19
    max_native_zoom = 19
    always_available = False
