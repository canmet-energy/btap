"""OpenStudio-to-EnergyPlus translation contracts that OSM cannot encode."""

from __future__ import annotations

FAN_COIL_MODE_SPECIFIC_AIRFLOW_FEATURE = (
    "btap_fan_coil_mode_specific_sizing_airflows"
)
FAN_COIL_SIZING_SPEC_NAME = "BTAP Fan Coil Mode-Specific Sizing Airflows"


def mark_fan_coil_for_mode_specific_sizing(fan_coil):
    """Require separate cooling/heating sizing airflow for this fan coil."""
    fan_coil.additionalProperties().setFeature(
        FAN_COIL_MODE_SPECIFIC_AIRFLOW_FEATURE, True
    )


def marked_fan_coil_names(model):
    """Return fan-coil names carrying the mode-specific sizing contract."""
    names = []
    for fan_coil in model.getZoneHVACFourPipeFanCoils():
        properties = fan_coil.additionalProperties()
        if not properties.hasFeature(FAN_COIL_MODE_SPECIFIC_AIRFLOW_FEATURE):
            continue
        enabled = properties.getFeatureAsBoolean(
            FAN_COIL_MODE_SPECIFIC_AIRFLOW_FEATURE
        )
        if not enabled.is_initialized():
            raise RuntimeError(
                f"{FAN_COIL_MODE_SPECIFIC_AIRFLOW_FEATURE} on "
                f"{fan_coil.nameString()} must be boolean"
            )
        if enabled.get():
            names.append(fan_coil.nameString())
    return names


def apply_workspace_contracts(model, workspace):
    """Materialize marked model contracts in the translated EnergyPlus input."""
    names = marked_fan_coil_names(model)
    if not names:
        return 0

    import openstudio

    fan_coil_type = openstudio.IddObjectType("ZoneHVAC:FourPipeFanCoil")
    sizing_type = openstudio.IddObjectType("DesignSpecification:ZoneHVAC:Sizing")
    translated = {}
    for fan_coil in workspace.getObjectsByType(fan_coil_type):
        key = fan_coil.nameString().casefold()
        if key in translated:
            raise RuntimeError(
                "translated EnergyPlus input contains duplicate fan-coil name "
                f"{fan_coil.nameString()}"
            )
        translated[key] = fan_coil

    missing = [name for name in names if name.casefold() not in translated]
    if missing:
        raise RuntimeError(
            "marked fan coils were not translated to EnergyPlus: "
            + ", ".join(sorted(missing))
        )

    existing_names = {
        obj.nameString().casefold()
        for obj in workspace.getObjectsByType(sizing_type)
    }
    spec_name = _unique_name(FAN_COIL_SIZING_SPEC_NAME, existing_names)
    specification = openstudio.IdfObject(sizing_type)
    values = {
        "Name": spec_name,
        "Cooling Supply Air Flow Rate Method":
            "FractionOfAutosizedCoolingAirflow",
        "Cooling Fraction of Autosized Cooling Supply Air Flow Rate": "1.0",
        "No Load Supply Air Flow Rate Method": "None",
        "Heating Supply Air Flow Rate Method":
            "FractionOfAutosizedHeatingAirflow",
        "Heating Fraction of Heating Supply Air Flow Rate": "1.0",
        "Cooling Design Capacity Method":
            "FractionOfAutosizedCoolingCapacity",
        "Fraction of Autosized Cooling Design Capacity": "1.0",
        "Heating Design Capacity Method":
            "FractionOfAutosizedHeatingCapacity",
        "Fraction of Autosized Heating Design Capacity": "1.0",
    }
    for field, value in values.items():
        _set_field(specification, field, value)

    added = workspace.addObject(specification)
    if not added.is_initialized():
        raise RuntimeError(
            "could not add DesignSpecification:ZoneHVAC:Sizing for marked "
            "fan coils"
        )

    for name in names:
        _set_field(
            translated[name.casefold()],
            "Design Specification ZoneHVAC Sizing Object Name",
            spec_name,
        )
    return len(names)


def _set_field(obj, field_name, value):
    idd = obj.iddObject()
    for index in range(idd.numFields()):
        field = idd.getField(index)
        if field.is_initialized() and field.get().name() == field_name:
            if not obj.setString(index, value):
                raise RuntimeError(
                    f"could not set {idd.name()} field {field_name} to {value!r}"
                )
            return
    raise RuntimeError(f"{idd.name()} has no field named {field_name}")


def _unique_name(base, existing):
    if base.casefold() not in existing:
        return base
    suffix = 2
    while f"{base} {suffix}".casefold() in existing:
        suffix += 1
    return f"{base} {suffix}"
