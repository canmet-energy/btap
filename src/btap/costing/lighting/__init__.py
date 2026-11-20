"""btap.costing.lighting — lighting fixture costing.

Facade: ``cost(model, ...)``, as ``btap.costing.envelope.cost`` and
``btap.costing.shw.cost``. The domain modules are importable directly.
"""

def __getattr__(name):
    # Lazy, so importing the package does not import the SDK-backed report
    # module; `cost` is here so every domain is costed as
    # `btap.costing.<domain>.cost` (#237).
    if name == "cost":
        from btap.costing.lighting.report import cost
        return cost
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["cost"]
