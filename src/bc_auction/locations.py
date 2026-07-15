from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from bc_auction.models import LocationStatus, NormalizedLocation


@dataclass(frozen=True, slots=True)
class LocationAlias:
    canonical: str
    qualifier: str | None = None


DEFAULT_LOCATIONS = (
    "100 Mile House",
    "Abbotsford",
    "Aldergrove",
    "Annacis Island",
    "Armstrong",
    "Ashcroft",
    "Bella Coola",
    "Bridge River",
    "Burnaby",
    "Campbell River",
    "Castlegar",
    "Chemainus",
    "Clearwater",
    "Coldstream",
    "Comox",
    "Coquitlam",
    "Courtenay",
    "Cranbrook",
    "Dawson Creek",
    "Delta",
    "Duncan",
    "Enderby",
    "Fort St. James",
    "Fort St. John",
    "Golden",
    "Grand Forks",
    "Hope",
    "Kamloops",
    "Kelowna",
    "Kitimat",
    "Ladysmith",
    "Lake Country",
    "Langley",
    "Lillooet",
    "Lumby",
    "Lytton",
    "Maple Ridge",
    "McBride",
    "Merritt",
    "Mission",
    "Nanaimo",
    "Nelson",
    "New Westminster",
    "North Cowichan",
    "Osoyoos",
    "Parksville",
    "Peachland",
    "Penticton",
    "Port Alberni",
    "Port McNeill",
    "Prince George",
    "Prince Rupert",
    "Princeton",
    "Qualicum Bay",
    "Quesnel",
    "Revelstoke",
    "Richmond",
    "Salmon Arm",
    "Sechelt",
    "Smithers",
    "Sparwood",
    "Squamish",
    "Summerland",
    "Surrey",
    "Telkwa",
    "Terrace",
    "Tumbler Ridge",
    "Valemount",
    "Vancouver",
    "Vanderhoof",
    "Vernon",
    "Victoria",
    "Williams Lake",
)

DEFAULT_ALIASES = {
    "victoria - uvic": LocationAlias(canonical="Victoria", qualifier="UVic"),
}


class LocationNormalizer:
    def __init__(
        self,
        known_locations: Iterable[str] = DEFAULT_LOCATIONS,
        aliases: Mapping[str, LocationAlias] = DEFAULT_ALIASES,
    ) -> None:
        self._known = {_key(location): location for location in known_locations}
        self._aliases = {_key(raw): alias for raw, alias in aliases.items()}

    def normalize(self, raw: str) -> NormalizedLocation:
        cleaned = _clean(raw)
        key = _key(cleaned)

        alias = self._aliases.get(key)
        if alias is not None:
            return NormalizedLocation(
                raw=raw,
                canonical=alias.canonical,
                qualifier=alias.qualifier,
                status=LocationStatus.ALIAS,
            )

        canonical = self._known.get(key)
        if canonical is not None:
            return NormalizedLocation(
                raw=raw,
                canonical=canonical,
                status=LocationStatus.EXACT,
            )

        return NormalizedLocation(
            raw=raw,
            canonical=cleaned,
            status=LocationStatus.UNKNOWN,
        )


def _clean(value: str) -> str:
    return " ".join(value.split())


def _key(value: str) -> str:
    return _clean(value).casefold()
