"""Edition-specific NECB modules.

Everything under ``btap.codes.necb`` applies to every supported edition unless
it sits here. One subpackage per edition (``necb2025`` today); nothing in this
package is bound to the pipeline by an edition registry yet — callers import
the edition module they need by name.
"""
