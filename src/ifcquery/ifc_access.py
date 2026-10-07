"""Reading values out of an IFC model. This is the only module that knows IfcOpenShell's data model.

Covers:
- direct attributes (``Name``, ``ObjectType``, ...)
- ``PredefinedType``, with the type-object fallback and USERDEFINED handling
- property-set values (``Pset.Property``): the occurrence's value wins over the type's
- quantities converted to SI units (m, m², m³, kg, s)
- spatial descendants, for the ``>`` containment operator
"""

from __future__ import annotations

from typing import Any

import ifcopenshell
import ifcopenshell.util.element as ifc_element
import ifcopenshell.util.unit as ifc_unit

from . import ast
from .errors import QueryEvaluationError

_QUANTITY_UNIT_TYPE = {
    "IfcQuantityLength": "LENGTHUNIT",
    "IfcQuantityArea": "AREAUNIT",
    "IfcQuantityVolume": "VOLUMEUNIT",
    "IfcQuantityWeight": "MASSUNIT",
    "IfcQuantityTime": "TIMEUNIT",
}


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def predefined_type(element) -> tuple[str | None, str | None]:
    """Return ``(enum_value, user_defined_value)``.

    The occurrence's PredefinedType is used unless it's missing or NOTDEFINED,
    in which case the type object's value is used. When the value is
    USERDEFINED, the second item is the custom name: ObjectType on the
    occurrence, or ElementType/ProcessType on the type object.
    """
    raw = getattr(element, "PredefinedType", None)
    if raw == "USERDEFINED":
        return raw, getattr(element, "ObjectType", None)
    if raw not in (None, "NOTDEFINED"):
        return raw, None
    element_type = ifc_element.get_type(element)
    type_raw = getattr(element_type, "PredefinedType", None) if element_type is not None else None
    if type_raw == "USERDEFINED":
        user = getattr(element_type, "ElementType", None) or getattr(element_type, "ProcessType", None)
        return type_raw, user
    if type_raw not in (None, "NOTDEFINED"):
        return type_raw, None
    return raw, None


class ModelAccess:
    """Value lookups on one model. Unit scales are cached per instance."""

    def __init__(self, model: ifcopenshell.file):
        self.model = model
        self._unit_scales: dict[str, float] = {}

    # ---- selection ----------------------------------------------------------------

    def elements(self, ifc_class: str) -> list:
        """All instances of a class, including subtypes (class name is case-insensitive)."""
        try:
            return list(self.model.by_type(ifc_class, include_subtypes=True))
        except RuntimeError:
            schema = getattr(self.model, "schema_identifier", None) or self.model.schema
            raise QueryEvaluationError(f"class {ifc_class!r} does not exist in the model's schema {schema}") from None

    def descendant_ids(self, roots) -> set[int]:
        """IDs of everything below ``roots`` through IfcRelAggregates and
        IfcRelContainedInSpatialStructure, at any depth. Roots are not included."""
        seen: set[int] = set()
        stack = list(roots)
        while stack:
            node = stack.pop()
            children = []
            for rel in getattr(node, "IsDecomposedBy", None) or ():
                children.extend(rel.RelatedObjects)
            for rel in getattr(node, "ContainsElements", None) or ():
                children.extend(rel.RelatedElements)
            for child in children:
                if child.id() not in seen:
                    seen.add(child.id())
                    stack.append(child)
        return seen

    # ---- values ------------------------------------------------------------------------

    def value(self, element, path: ast.Path) -> Any:
        """The value at ``path`` on ``element``, or None when it's absent."""
        if path.is_attribute:
            if path.name == "PredefinedType":
                raw, user = predefined_type(element)
                return user if raw == "USERDEFINED" and user else raw
            try:
                return getattr(element, path.name)
            except AttributeError:
                return None
        return self.property_value(element, path.pset, path.name)

    def property_value(self, element, pset: str, prop: str) -> Any:
        value = ifc_element.get_pset(element, pset, prop)
        if isinstance(value, (list, tuple)) and len(value) == 1:
            value = value[0]  # single-item enumerated or list values
        if is_number(value):
            scale = self._quantity_scale(element, pset, prop)
            if scale != 1:
                value = value * scale
        return value

    # ---- quantities and units ------------------------------------------------------------

    def _quantity(self, element, pset: str, prop: str):
        """The IfcPhysicalSimpleQuantity entity for ``pset.prop``, or None if it's a plain property."""
        for obj in (element, ifc_element.get_type(element)):
            if obj is None:
                continue
            definition = ifc_element.get_pset(obj, pset, should_inherit=False)
            if not definition or "id" not in definition:
                continue
            entity = self.model.by_id(definition["id"])
            if not entity.is_a("IfcElementQuantity"):
                return None
            for quantity in entity.Quantities:
                if quantity.Name == prop:
                    return quantity
        return None

    def _quantity_scale(self, element, pset: str, prop: str) -> float:
        quantity = self._quantity(element, pset, prop)
        if quantity is None:
            return 1
        unit_type = _QUANTITY_UNIT_TYPE.get(quantity.is_a())
        if unit_type is None:
            return 1  # counts and other dimensionless quantities
        if getattr(quantity, "Unit", None) is not None:
            return ifc_unit.get_unit_scale(quantity.Unit)
        if unit_type not in self._unit_scales:
            self._unit_scales[unit_type] = ifc_unit.calculate_unit_scale(self.model, unit_type)
        return self._unit_scales[unit_type]
