"""Where a model is costed — resolved once, the same way for every domain (#237).

Two silent wrong answers lived in the four copies of this resolution:

- with no city given, the location came from the model's SITE, and a model
  whose site was never set sits at latitude 0, longitude 0 — whose nearest
  cost location is ST JOHNS, NEWFOUNDLAND. It was logged as `info`;
- the regional-factor lookup is an exact string match against the table's
  UPPER-CASE spelling, so ``city="Toronto"`` found no factor and every item
  fell back to 100 with a warning indistinguishable from a real typo.

So an unset site is refused, a named city is matched to the table's own
spelling case-insensitively, and a city the table does not list is refused
rather than priced at the 100 fallback.
"""

from __future__ import annotations

import difflib


def site_location(closest_location, site):
    """The cost location nearest the model's site, refusing an UNSET site."""
    latitude, longitude = site.latitude(), site.longitude()
    if latitude == 0.0 and longitude == 0.0:
        raise ValueError(
            "the model's site location is unset (latitude 0, longitude 0), so "
            "there is no nearest cost location — pass city= and "
            "province_state=, or set the site (e.g. attach the weather file) "
            "first")
    location = closest_location(latitude, longitude)
    if location is None:
        raise ValueError("pass city=/province_state= — locations.csv unavailable")
    return location


def _key(value):
    return " ".join(str(value).split()).casefold()


def canonical(locations, city, province_state):
    """``(city, province_state)`` as the cost table spells them.

    Matched ignoring case and surrounding whitespace. With no table to check
    against, the pair is returned unchanged.

    :raises ValueError: when the table does not list the place.
    """
    if not locations:
        return city, province_state
    wanted = (_key(province_state), _key(city))
    for row in locations:
        if (_key(row.get("province_state", "")), _key(row.get("city", ""))) == wanted:
            return row["city"], row["province_state"]
    places = [f"{row.get('city')}, {row.get('province_state')}" for row in locations]
    near = difflib.get_close_matches(f"{city}, {province_state}".upper(), places, n=3)
    raise ValueError(
        f"{city!r}, {province_state!r} is not a cost location"
        + (f" — did you mean {' or '.join(repr(n) for n in near)}?" if near else "")
        + f" ({len(places)} are listed in btap/costing/data/locations.csv)")
