"""Resolve a builder performance profile from an AUTHORED vintage table.

#183 gave `modeling.build_system` a `performance_profile` parameter; this
resolves one from a caller's table keyed by vintage, climate zone and building
type. `btap.modeling` still knows no vintage — the resolution happens here, in
`btap.stock`, and hands `modeling` a flat mapping.

**No table ships with the library.** phylroy, 2026-11-02: "none initially". A
recipe is authored input, not a shipped table, which keeps NECB's edition
snapshots the only authority in the distribution — so the table is a
parameter, and `btap/stock/CLAUDE.md` says an author adding one should expect
to be asked which authority its numbers come from. That matters more here than
for NECB: a Code coefficient can be checked against the Code, while a 1972
Ottawa office's assumed boiler efficiency cannot be checked against anything.

## This is DELIBERATELY not `find_row`

`codes/necb/hvac/efficiency.find_row` matches when every criteria key PRESENT
in the row equals the wanted value — so a MISSING key, a `None` and the
literal `'Any'` are all wildcards — and then returns `rows[0]`. Two
consequences, both refused here:

- a key omitted by accident silently becomes a wildcard. That produced AHJ-17
  (#181): one `AirCooled` chiller row with `compressor_type: null` matched
  every compressor type over an entire capacity band. A vintage table makes
  this MORE likely, because wildcards are how an author avoids writing every
  combination out;
- first-row-wins means a general row can shadow a specific one purely by
  being earlier in the file.

So: wildcards are the explicit string `'any'`, a missing criteria key is an
AUTHORING ERROR, the MOST SPECIFIC row wins, and a tie is an error rather than
a silent pick.
"""

from __future__ import annotations

from collections.abc import Mapping

#: The criteria a row is matched on, in precedence order — most specific
#: first. Order matters only for reporting; specificity decides matches.
CRITERIA = ('vintage', 'climate_zone', 'building_type')

#: The one accepted wildcard. Not `None`, not a missing key, not 'Any' —
#: a single spelling so a reader cannot mistake absence for intent.
ANY = 'any'


class ProfileTableError(ValueError):
    """The table is mis-authored. Raised at validation, never at lookup."""


class ProfileResolutionError(ValueError):
    """No row, or an ambiguous tie. Never resolved by picking one."""


def validate_table(table):
    """Refuse a mis-authored table, loudly and completely.

    Every row must carry EVERY criteria key explicitly, because the whole
    point is that absence is not intent. Reports every offending row at once
    rather than the first, so an author fixes the table in one pass.
    """
    if not isinstance(table, (list, tuple)) or not table:
        raise ProfileTableError(
            'a vintage performance table must be a non-empty list of rows')

    problems = []
    for index, row in enumerate(table):
        if not isinstance(row, Mapping):
            problems.append(f'row {index} is not a mapping')
            continue
        missing = [key for key in CRITERIA if key not in row]
        if missing:
            problems.append(
                f'row {index} omits {", ".join(missing)} — a missing criteria '
                f"key is an AUTHORING ERROR here, not a wildcard. Write "
                f"'{ANY}' if that is what you mean")
        for key in CRITERIA:
            if key in row and row[key] is None:
                problems.append(
                    f"row {index} has {key}=None; use the string '{ANY}'")
        values = row.get('values')
        if not isinstance(values, Mapping) or not values:
            problems.append(
                f'row {index} carries no non-empty "values" mapping')

    if problems:
        raise ProfileTableError(
            'vintage performance table is mis-authored:\n  - '
            + '\n  - '.join(problems))
    return table


def _specificity(row, criteria):
    """How many criteria the row matches EXACTLY rather than by wildcard."""
    return sum(1 for key in criteria if row[key] != ANY)


def _matches(row, criteria):
    return all(row[key] in (ANY, value) for key, value in criteria.items())


def resolve_performance_profile(table, *, vintage, climate_zone,
                                building_type, audit=None, step='stock'):
    """The profile for one (vintage, climate zone, building type).

    :returns: ``(values, provenance)`` — the flat mapping to hand
        `modeling.build_system`, and a record of WHICH row produced it and how
        specific that row was. The provenance is the point: a reader of the
        trail must be able to tell real 1972-Ottawa-office data from a
        three-wildcard fallback, and the two are indistinguishable from the
        values alone.
    :raises ProfileResolutionError: when nothing matches, or when two rows tie
        on specificity. A tie means the table is ambiguous; picking one would
        reintroduce `find_row`'s first-row-wins.
    """
    validate_table(table)
    criteria = {'vintage': vintage, 'climate_zone': climate_zone,
                'building_type': building_type}

    candidates = [row for row in table if _matches(row, criteria)]
    if not candidates:
        raise ProfileResolutionError(
            f'no row matches {criteria!r}. Add one, or add an explicit '
            f"'{ANY}' fallback row — this does NOT fall back silently")

    best = max(_specificity(row, criteria) for row in candidates)
    winners = [row for row in candidates
               if _specificity(row, criteria) == best]
    if len(winners) > 1:
        raise ProfileResolutionError(
            f'{len(winners)} rows tie at specificity {best} for {criteria!r}: '
            + '; '.join(
                repr({k: row[k] for k in CRITERIA}) for row in winners)
            + '. The table is ambiguous — first-row-wins is what AHJ-17 was')

    row = winners[0]
    wildcards = [key for key in CRITERIA if row[key] == ANY]
    provenance = {
        'matched': {key: row[key] for key in CRITERIA},
        'requested': criteria,
        'specificity': best,
        'wildcards': wildcards,
        'exact': not wildcards,
        'source': row.get('source'),
    }

    if audit is not None:
        detail = ('exact match' if not wildcards
                  else 'WILDCARD fallback on ' + ', '.join(wildcards))
        audit.info(
            step, f'vintage performance profile resolved — {detail}',
            target=f'{vintage} / {climate_zone} / {building_type}',
            value=row.get('source') or f'specificity {best}/{len(CRITERIA)}',
            inputs=provenance)

    return dict(row['values']), provenance


def uncovered_combinations(table, *, vintages, climate_zones, building_types):
    """Which combinations resolve only by wildcard, or not at all.

    The inverse of `scripts/necb_orphan_keys.py`: that asks which shipped keys
    nothing reads, this asks which requests the table answers only vaguely. A
    table can be entirely valid and still answer most of the stock with one
    three-wildcard row, and nothing else would say so.

    :returns: ``{'unmatched': [...], 'wildcard_only': [(criteria, wildcards)]}``
    """
    validate_table(table)
    unmatched, wildcard_only = [], []
    for vintage in vintages:
        for zone in climate_zones:
            for building_type in building_types:
                want = {'vintage': vintage, 'climate_zone': zone,
                        'building_type': building_type}
                try:
                    _, provenance = resolve_performance_profile(
                        table, vintage=vintage, climate_zone=zone,
                        building_type=building_type)
                except ProfileResolutionError:
                    unmatched.append(want)
                    continue
                if provenance['wildcards']:
                    wildcard_only.append((want, provenance['wildcards']))
    return {'unmatched': unmatched, 'wildcard_only': wildcard_only}
