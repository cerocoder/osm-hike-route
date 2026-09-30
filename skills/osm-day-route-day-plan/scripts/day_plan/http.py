"""One stdlib JSON GET helper. Plugins receive it as ctx.http so tests can
pass a fake instead of patching urllib."""
import json
import urllib.error
import urllib.request

# Nominatim's usage policy asks for an identifying User-Agent.
USER_AGENT = "osm-day-route-day-plan/1.0 (+https://github.com/cerocoder/osm-hike-route)"


class HttpError(Exception):
    pass


def _open(req, timeout):
    return urllib.request.urlopen(req, timeout=timeout)


def get_text(url: str, timeout: float = 10.0) -> str:
    """The body of a GET as text (for services that answer HTML, such as the
    GWIS WMS GetFeatureInfo). Same failure contract as get_json."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with _open(req, timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise HttpError(str(e)) from e


def get_json(url: str, timeout: float = 10.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with _open(req, timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise HttpError(str(e)) from e
