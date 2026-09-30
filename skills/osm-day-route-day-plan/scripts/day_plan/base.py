"""Shared types for the day-plan plugin system. Mirrors the shape of
place_info/ and tile_providers/: one plugin per topic, a service that runs
them with per-plugin fault isolation."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

SEVERITIES = ("info", "caution", "danger")
CONFIDENCE_TIERS = ("tag-backed", "web-sourced", "derived", "no-data")

# Fixed order of section groups in day-plan-<date>.md (spec, "Output").
# "hazards" is a group: several plugins contribute to it.
SECTION_ORDER = ("summary", "light", "weather", "transit", "pois", "hazards", "cell_coverage")


@dataclass
class PlanWarning:
    severity: str  # one of SEVERITIES
    text: str
    pinned: bool = False  # sorts before other warnings of the same severity in the Summary (radiation)


@dataclass
class Section:
    section_id: str  # one of SECTION_ORDER
    markdown: str
    confidence: str = "no-data"  # one of CONFIDENCE_TIERS
    sources: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    shared: dict = field(default_factory=dict)  # data for dependent plugins
    title: str | None = None  # sub-heading, used when a group has >1 plugin
    omit: bool = False  # "not applicable" or a data-only plugin: left out of the file and not listed as missing data


class SectionPlugin(ABC):
    plugin_id: str
    section_id: str
    version: str = "1"
    depends_on: tuple = ()
    title_key: str | None = None  # i18n key of the sub-heading when the plugin shares a section group

    @abstractmethod
    def run(self, ctx, shared: dict) -> Section:
        """`shared` maps plugin_id -> that plugin's Section.shared for every
        plugin in depends_on that ran successfully (a failed or missing
        dependency is simply absent — handle that). Return a no-data Section
        for an ordinary 'nothing found' outcome; only a genuine
        programming error should raise (the service isolates it)."""
        raise NotImplementedError
