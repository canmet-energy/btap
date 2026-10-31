"""A serialized, author-supplyable declaration of an air loop's EQUIPMENT CLASS.

Some code requirements turn on what the equipment IS, not on what it does.
NECB Table 8.4.4.7.-A's residential branch is the case that forced this: the
reference is modelled identically to the proposed only where the proposed is
cooled by "an air-cooled unitary, packaged terminal or room air conditioner (or
heat pumps), or fan coils", and everything else takes through-the-wall systems.

A model's TOPOLOGY frequently cannot answer that. A bare `Coil:Cooling:DX*` on a
constant-volume loop describes a certified packaged rooftop unit and a
field-erected built-up DX system equally well, and `coils.supply_components`
must unwrap any `AirLoopHVACUnitarySystem` container to find a staged
reference system's coils at all, so even that container's identity is gone by
the time a classifier runs.

Two WRONG ways to answer it, both tried and rejected:

- **the air loop's NAME.** `classify._recognize_gem_name` resolves a loop name
  against this repository's catalogue. Reading that as an equipment fact made
  the answer depend on who authored the model: two OSMs with identical
  topology differed because one kept a BTAP name (Sol, `331`).
- **zone count.** `_structural_family_guess` calls any single-zone no-reheat
  loop `packaged_single_zone`. That is arithmetic about the model, not evidence
  about the equipment, and D-108 holds it cannot establish a class.

This is the right way, and it is deliberately not BTAP-specific: an
`AdditionalProperties` feature on the air loop, written by whoever knows the
answer. Our own builders declare it where the catalogue row names real
equipment; a design firm's model can carry the same key from their own tooling;
a submitter can add it by hand. It survives the OSM round trip and does NOT
forward-translate, so declaring it changes no simulation result.

The NECB MEANING of a declared value lives in `btap.codes`, never here — this
module only records and reads the fact (D-77).
"""

from __future__ import annotations

#: The `AdditionalProperties` feature name, on an `AirLoopHVAC`.
FEATURE = 'equipment_class'

#: The values this convention defines. Each names a physical equipment class a
#: code may ask about, in the vocabulary building engineers use rather than any
#: one code's wording, so another code family can map them its own way.
#:
#: `air_cooled_unitary` covers factory-made packaged AND matched split systems:
#: NECB Part 5's Table 5.2.12.1.-A lists both under that heading, so the term is
#: about certification and assembly rather than about one physical box.
VALUES = (
    'air_cooled_unitary',
    'packaged_terminal',
    'room_air_conditioner',
    'heat_pump',
    'fan_coil',
    'built_up',
    'evaporative',
)


def declare(air_loop, value):
    """Record `value` as `air_loop`'s equipment class.

    :param air_loop: openstudio.model.AirLoopHVAC
    :param value: one of :data:`VALUES`
    :raises ValueError: for a value outside the convention, because a typo
        would read as "no declaration" and silently fall back to inference
    """
    if value not in VALUES:
        raise ValueError(
            f"equipment_class {value!r} is not one of {VALUES}; an undeclared "
            f"class falls back to inference, so a typo would be silent")
    air_loop.additionalProperties().setFeature(FEATURE, value)


def read(air_loop):
    """`air_loop`'s declared equipment class, or None.

    An UNRECOGNIZED value reads as None rather than raising: a model from
    another tool may use a vocabulary we do not know, and the honest response
    to that is to treat the class as undeclared, not to refuse the model.

    Use `read_raw` to tell "no declaration" from "a declaration we do not
    recognize" — they are the same to this function and VERY different to the
    person who wrote the feature.
    """
    value = read_raw(air_loop)
    return value if value in VALUES else None


def read_raw(air_loop):
    """Whatever the feature says, recognized or not, or None if it is absent.

    `declare` refuses a value outside `VALUES`, but a model does not have to
    come through `declare`: anyone may set the `AdditionalProperties` feature
    directly, which is the point of the convention. A typo then reads as "no
    declaration" and the run refuses for the same reason it refused before,
    with nothing saying a declaration was present and unrecognized — so the
    author retypes the value they already typed (Fable, PR #161 review).
    `classify` warns on exactly that difference.
    """
    feature = air_loop.additionalProperties().getFeatureAsString(FEATURE)
    return feature.get() if feature.is_initialized() else None
