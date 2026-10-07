"""IFC schema lookups (classes, attributes, enumerations) via IfcOpenShell's schema wrapper."""

from __future__ import annotations

import difflib
from functools import lru_cache

import ifcopenshell

from .errors import QuerySchemaError

_W = ifcopenshell.ifcopenshell_wrapper


@lru_cache(maxsize=None)
def get_schema(name: str):
    """Return the wrapper schema for e.g. "IFC4", "IFC2X3", "IFC4X3_ADD2"."""
    try:
        return _W.schema_by_name(name.upper())
    except Exception:
        raise QuerySchemaError(f"unknown IFC schema {name!r}") from None


@lru_cache(maxsize=None)
def _entity_names(schema_name: str) -> tuple[str, ...]:
    return tuple(e.name() for e in get_schema(schema_name).entities())


def entity(schema_name: str, name: str):
    """Entity declaration for a class name (case-insensitive), or None."""
    try:
        decl = get_schema(schema_name).declaration_by_name(name)
    except Exception:
        return None
    return decl if isinstance(decl, _W.entity) else None


def attribute(decl, name: str):
    """Attribute (including inherited ones) with this exact name, or None."""
    for attr in decl.all_attributes():
        if attr.name() == name:
            return attr
    return None


def attribute_names(decl) -> list[str]:
    return [a.name() for a in decl.all_attributes()]


def enum_items(attr) -> tuple[str, ...] | None:
    """The enumeration values of an attribute's type, or None if it isn't an enumeration."""
    t = attr.type_of_attribute()
    while True:
        if isinstance(t, (_W.named_type, _W.type_declaration)):
            t = t.declared_type()
        elif isinstance(t, _W.enumeration_type):
            return tuple(t.enumeration_items())
        else:
            return None


def suggest(name: str, candidates) -> str:
    """' Did you mean X?' for the closest candidate, or ''."""
    by_lower = {c.lower(): c for c in candidates}
    match = difflib.get_close_matches(name.lower(), list(by_lower), n=1, cutoff=0.75)
    return f" Did you mean {by_lower[match[0]]}?" if match else ""


def entity_suggestion(schema_name: str, name: str) -> str:
    return suggest(name, _entity_names(schema_name))
