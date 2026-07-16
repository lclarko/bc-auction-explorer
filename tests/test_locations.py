from bc_auction.locations import LocationNormalizer
from bc_auction.models import LocationStatus


def test_known_location_uses_preferred_case() -> None:
    location = LocationNormalizer().normalize("  victoria  ")

    assert location.canonical == "Victoria"
    assert location.qualifier is None
    assert location.status is LocationStatus.EXACT


def test_alias_preserves_qualifier() -> None:
    location = LocationNormalizer().normalize("Victoria - Uvic")

    assert location.canonical == "Victoria"
    assert location.qualifier == "UVic"
    assert location.status is LocationStatus.ALIAS


def test_unknown_location_is_not_fuzzy_matched() -> None:
    location = LocationNormalizer().normalize("Qualicum Beach")

    assert location.canonical == "Qualicum Beach"
    assert location.status is LocationStatus.UNKNOWN
