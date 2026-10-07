"""Generate a buildingSMART IDS from IFCQuery queries.

A query only gives a trustworthy answer if the model contains the data it
reads. This module turns that into an IDS (Information Delivery
Specification): every path a query reads becomes a requirement.

- A projected path (``-> P``) is required on the elements the filter selects.
- A path read by a filter condition is required on the elements where the
  rest of the filter holds, so the filter never silently skips an element
  because a value is missing.
- Some rule patterns map to specification cardinality. ``COUNT(Q) = 0``
  becomes prohibited, ``COUNT(Q) > 0`` and ``FIRST(Q ...)`` become required,
  and ``COUNT(Q[... and not exists(P)]) = 0`` makes P required.

Conditions IDS can't express (``!=``, ``~=``, ``or``, ``not``, filters on
the left side of ``>``) are left out of the applicability. That makes it
broader, and each omission is reported in ``IdsResult.warnings``.

    result = ifcquery.generate_ids([Path("rules.ifq")], title="Licensing")
    result.to_xml("rules.ids")

Command line: ``python -m ifcquery.idscli rules.ifq -o rules.ids`` (see idscli.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Union

import ifcopenshell.util.pset
from ifctester import ids as ifc_ids

from . import ast, schema
from .errors import QuerySchemaError

Source = Union[str, Path, ast.Program]

_BOUNDS = {"<": "maxExclusive", "<=": "maxInclusive", ">": "minExclusive", ">=": "minInclusive"}

_QUANTITY_DATA_TYPE = {
    "Q_LENGTH": "IFCLENGTHMEASURE",
    "Q_AREA": "IFCAREAMEASURE",
    "Q_VOLUME": "IFCVOLUMEMEASURE",
    "Q_COUNT": "IFCCOUNTMEASURE",
    "Q_WEIGHT": "IFCMASSMEASURE",
    "Q_TIME": "IFCTIMEMEASURE",
}


# ---- internal facet model ------------------------------------------------------------------
# Plain, hashable descriptions of IDS facets. They are converted to ifctester
# objects only at the end, which keeps the derivation logic easy to test.


@dataclass(frozen=True)
class Value:
    """A facet value: ``exact`` (one value), ``enum`` (any of several) or ``bounds``.

    For bounds, ``items`` holds pairs such as ("minInclusive", 100).
    """

    kind: str
    items: tuple

    def __str__(self) -> str:
        if self.kind == "exact":
            return _lit(self.items[0])
        if self.kind == "enum":
            return "(" + ", ".join(_lit(v) for v in self.items) + ")"
        symbols = {"minInclusive": ">=", "minExclusive": ">", "maxInclusive": "<=", "maxExclusive": "<"}
        return " and ".join(f"{symbols[k]} {_lit(v)}" for k, v in self.items)


@dataclass(frozen=True)
class Facet:
    """kind is "entity", "partof", "attribute" or "property".

    For entity facets, ``value`` is the PredefinedType constraint. ``name`` is
    the class name (entity and partof), the attribute name, or the property's
    base name.
    """

    kind: str
    name: str
    pset: str | None = None
    value: Value | None = None
    data_type: str | None = None

    def label(self) -> str:
        if self.kind == "entity":
            return self.name + (f"[PredefinedType {_op(self.value)}{self.value}]" if self.value else "")
        if self.kind == "partof":
            return f"in {self.name}"
        path = self.name if self.pset is None else f"{self.pset}.{self.name}"
        return path + (f" {_op(self.value)}{self.value}" if self.value else " exists")


def _op(value: Value) -> str:
    return {"exact": "= ", "enum": "in ", "bounds": ""}[value.kind]


class _EnumText(str):
    """An enumeration literal (bare UPPERCASE word). Compares like the plain string; only printing differs."""


def _literal_value(lit: ast.Literal):
    return _EnumText(lit.value) if lit.kind == "enum" else lit.value


def _lit(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, _EnumText):
        return str(v)
    if isinstance(v, str):
        return f'"{v}"'
    return str(v)


@dataclass(frozen=True)
class Origin:
    label: str
    line: int
    text: str

    def __str__(self) -> str:
        where = f"{self.label}:{self.line}" if self.label else f"line {self.line}"
        return f"{where}: {' '.join(self.text.split())}"


@dataclass(frozen=True)
class Need:
    """One thing the queries need. A None ``requirement`` only sets the specification's cardinality."""

    applicability: tuple[Facet, ...]
    requirement: Facet | None
    usage: str  # "optional" | "required" | "prohibited"
    origin: Origin


# ---- result ------------------------------------------------------------------------------------


@dataclass
class IdsResult:
    ids: ifc_ids.Ids
    warnings: list[str] = field(default_factory=list)
    needs: list[Need] = field(default_factory=list)

    def to_string(self) -> str:
        return self.ids.to_string()

    def to_xml(self, path: str | Path) -> None:
        """Write the IDS. ifctester validates it against the IDS 1.0 XSD while writing."""
        self.ids.to_xml(str(path))


# ---- condition helpers ----------------------------------------------------------------------------


def _conjuncts(cond: ast.Condition | None) -> list[ast.Condition]:
    if cond is None:
        return []
    if isinstance(cond, ast.And):
        out = []
        for item in cond.items:
            out.extend(_conjuncts(item))
        return out
    return [cond]


def _is_ptype(path: ast.Path) -> bool:
    return path.is_attribute and path.name == "PredefinedType"


def _paths_read(cond: ast.Condition) -> list[ast.Path]:
    """Paths whose values a condition reads. Paths only tested by exists() and PredefinedType are excluded."""
    if isinstance(cond, (ast.Comparison, ast.InList)):
        return [] if _is_ptype(cond.path) else [cond.path]
    if isinstance(cond, ast.Exists):
        return []
    if isinstance(cond, ast.Not):
        return _paths_read(cond.item)
    out = []
    for item in cond.items:
        for p in _paths_read(item):
            if p not in out:
                out.append(p)
    return out


def _cond_text(cond: ast.Condition) -> str:
    if isinstance(cond, ast.Comparison):
        lit = cond.literal
        shown = lit.value if lit.kind == "enum" else _lit(lit.value)
        return f"{cond.path} {cond.op} {shown}"
    if isinstance(cond, ast.InList):
        items = ", ".join(lit.value if lit.kind == "enum" else _lit(lit.value) for lit in cond.literals)
        return f"{cond.path} in ({items})"
    if isinstance(cond, ast.Exists):
        return f"exists({cond.path})"
    if isinstance(cond, ast.Not):
        return f"not {_cond_text(cond.item)}"
    joiner = " and " if isinstance(cond, ast.And) else " or "
    return "(" + joiner.join(_cond_text(c) for c in cond.items) + ")"


# ---- schema helpers -----------------------------------------------------------------------------------


def ids_version(schema_name: str) -> str:
    name = schema_name.upper()
    if name in ("IFC2X3", "IFC4"):
        return name
    if name.startswith("IFC4X3"):
        return "IFC4X3_ADD2"
    raise QuerySchemaError(f"IDS 1.0 supports IFC2X3, IFC4 and IFC4X3_ADD2, not {schema_name}")


@lru_cache(maxsize=None)
def concrete_classes(schema_name: str, ifc_class: str) -> tuple[str, ...]:
    """Upper-case names of a class and its non-abstract subtypes. An IDS entity facet matches exact classes only."""
    root = schema.entity(schema_name, ifc_class)
    out, stack = [], [root]
    while stack:
        decl = stack.pop()
        if not decl.is_abstract():
            out.append(decl.name().upper())
        stack.extend(decl.subtypes())
    return tuple(sorted(out))


@lru_cache(maxsize=None)
def _templates(schema_name: str):
    try:
        return ifcopenshell.util.pset.get_template(schema_name)
    except Exception:  # unknown schema identifiers, missing template files
        return None


def template_data_type(schema_name: str, pset: str, prop: str) -> str | None:
    """dataType of a standard Pset_/Qto_ property, from buildingSMART's templates."""
    templates = _templates(schema_name)
    template = templates.get_by_name(pset) if templates else None
    if template is None:
        return None
    for prop_template in template.HasPropertyTemplates or ():
        if prop_template.Name != prop:
            continue
        if prop_template.TemplateType in _QUANTITY_DATA_TYPE:
            return _QUANTITY_DATA_TYPE[prop_template.TemplateType]
        measure = getattr(prop_template, "PrimaryMeasureType", None)
        return measure.upper() if measure else None
    return None


# ---- derivation ------------------------------------------------------------------------------------------


class _Collector:
    def __init__(self, schema_name: str, data_types: dict[str, str | None], literal_kinds: dict[str, set[str]]):
        self.schema_name = schema_name
        self.data_types = data_types
        self.literal_kinds = literal_kinds
        self.needs: list[Need] = []
        self.warnings: list[str] = []
        self.origin: Origin | None = None

    # -- helpers --

    def warn(self, message: str) -> None:
        text = f"{self.origin}\n    {message}" if self.origin else message
        if text not in self.warnings:
            self.warnings.append(text)

    def cls(self, name: str) -> str:
        return schema.entity(self.schema_name, name).name()

    def data_type(self, path: ast.Path) -> str | None:
        key = str(path)
        if key in self.data_types:
            return self.data_types[key]
        found = template_data_type(self.schema_name, path.pset, path.name)
        if found:
            return found
        kinds = self.literal_kinds.get(key, set())
        if kinds and kinds <= {"string", "enum"}:
            return "IFCLABEL"
        if kinds == {"boolean"}:
            return "IFCBOOLEAN"
        return None

    def requirement(self, path: ast.Path) -> Facet:
        if path.is_attribute:
            return Facet("attribute", path.name)
        return Facet("property", path.name, path.pset, data_type=self.data_type(path))

    def add(self, applicability, requirement: Facet | None, usage: str = "optional") -> None:
        self.needs.append(Need(tuple(applicability), requirement, usage, self.origin))

    # -- translating filter conditions to applicability facets --

    def facet_for(self, cond: ast.Condition):
        """("ptype", Value) | ("facet", Facet) | None when IDS can't express the condition."""
        if isinstance(cond, ast.Comparison):
            if cond.op in ("!=", "~="):
                return None
            if cond.op == "=":
                value = Value("exact", (_literal_value(cond.literal),))
            else:
                value = Value("bounds", ((_BOUNDS[cond.op], cond.literal.value),))
            return self._facet(cond.path, value)
        if isinstance(cond, ast.InList):
            return self._facet(cond.path, Value("enum", tuple(_literal_value(lit) for lit in cond.literals)))
        if isinstance(cond, ast.Exists) and not _is_ptype(cond.path):
            return self._facet(cond.path, None)
        return None

    def _facet(self, path: ast.Path, value: Value | None):
        if _is_ptype(path):
            return ("ptype", value) if value is not None and value.kind != "bounds" else None
        if path.is_attribute:
            return ("facet", Facet("attribute", path.name, value=value))
        # Only template types go on applicability facets: guessing a type there
        # (e.g. IfcLabel for text) could make the IDS skip elements.
        data_type = self.data_types.get(str(path)) or template_data_type(self.schema_name, path.pset, path.name)
        return ("facet", Facet("property", path.name, path.pset, value=value, data_type=data_type))

    def applicability(self, entity: ast.Entity, partofs: list[Facet], skip: int | None = None, report=True):
        """Facets for ``entity`` from all translatable top-level conjuncts except number ``skip``.

        Returns (facets, exact). ``exact`` is False when some condition had to be left out."""
        ptype: Value | None = None
        facets: list[Facet] = []
        exact = True
        for i, cond in enumerate(_conjuncts(entity.condition)):
            if i == skip:
                continue
            translated = self.facet_for(cond)
            if translated is None or (translated[0] == "ptype" and ptype is not None):
                exact = False
                if report:
                    self.warn(
                        f"`{_cond_text(cond)}` on {self.cls(entity.ifc_class)} can't be expressed in IDS; "
                        "it was left out of the applicability, so more elements are checked"
                    )
                continue
            if translated[0] == "ptype":
                ptype = translated[1]
            elif translated[1] not in facets:
                facets.append(translated[1])
        entity_facet = Facet("entity", self.cls(entity.ifc_class), value=ptype)
        return [entity_facet, *partofs, *facets], exact

    # -- walking --

    def program(self, program: ast.Program, label: str) -> None:
        for stmt in program.statements:
            self.origin = Origin(label, stmt.line, stmt.text)
            self.rule_pattern(stmt.expr)
            self.expr(stmt.expr, "optional")
        self.origin = None

    def expr(self, node, usage: str) -> None:
        if isinstance(node, ast.Query):
            self.query(node, usage)
        elif isinstance(node, ast.Call):
            self.expr(node.arg, "required" if node.func == "FIRST" else usage)
        elif isinstance(node, (ast.BinOp, ast.Compare)):
            self.expr(node.left, "optional")
            self.expr(node.right, "optional")
        elif isinstance(node, ast.Neg):
            self.expr(node.operand, "optional")

    def query(self, query: ast.Query, usage: str) -> None:
        chain = query.chain
        partofs_by_level = [[Facet("partof", self.cls(e.ifc_class)) for e in chain[:i]] for i in range(len(chain))]
        for i, ent in enumerate(chain):
            self.filter_requirements(ent, partofs_by_level[i])

        projected = [p for p in query.projection or () if not _is_ptype(p)]
        if not projected and usage != "required":
            return  # the selection itself needs nothing beyond its filter requirements
        for ent in chain[:-1]:
            if ent.condition is not None:
                self.warn(
                    f"the filter on {self.cls(ent.ifc_class)} (left of `>`) can't be expressed in an IDS partOf "
                    "facet; the specification applies to every "
                    f"{self.cls(chain[-1].ifc_class)} inside any {self.cls(ent.ifc_class)}"
                )
        applicability, _ = self.applicability(chain[-1], partofs_by_level[-1])
        for path in projected:
            self.add(applicability, self.requirement(path), usage)
        if usage == "required" and not projected:
            self.add(applicability, None, "required")

    def filter_requirements(self, entity: ast.Entity, partofs: list[Facet]) -> None:
        """Each path read by conjunct i is required where the other conjuncts hold."""
        for i, cond in enumerate(_conjuncts(entity.condition)):
            paths = _paths_read(cond)
            if not paths:
                continue
            applicability, _ = self.applicability(entity, partofs, skip=i, report=False)
            # Drop facets that test the very path being required.
            applicability = [
                f for f in applicability if not (f.kind in ("attribute", "property") and _same_path(f, paths))
            ]
            for path in paths:
                self.add(applicability, self.requirement(path))

    def rule_pattern(self, expr) -> None:
        """Statement-level patterns that map to specification cardinality."""
        if not isinstance(expr, ast.Compare):
            return
        count, number, op = _count_comparison(expr)
        if count is None or count.arg.projection is not None:
            return
        query = count.arg
        last = query.chain[-1]
        partofs = [Facet("partof", self.cls(e.ifc_class)) for e in query.chain[:-1]]
        ancestors_filtered = any(e.condition is not None for e in query.chain[:-1])

        if (op, number) == ("=", 0):
            conjuncts = _conjuncts(last.condition)
            missing = [c for c in conjuncts if isinstance(c, ast.Not) and isinstance(c.item, ast.Exists)]
            if missing:
                # COUNT(Q[c and not exists(P)]) = 0: every element matching c must have P.
                rest = [c for c in conjuncts if c not in missing]
                reduced = ast.Entity(last.ifc_class, ast.And(tuple(rest)) if rest else None)
                applicability, _ = self.applicability(reduced, partofs)
                for cond in missing:
                    self.add(applicability, self.requirement(cond.item.path))
                return
            applicability, exact = self.applicability(last, partofs, report=False)
            if exact and not ancestors_filtered:
                self.add(applicability, None, "prohibited")
            else:
                self.warn("this COUNT(...) = 0 rule can't be expressed exactly in IDS, so no prohibition was generated")
        elif (op, number) in ((">", 0), (">=", 1), ("!=", 0)):
            applicability, _ = self.applicability(last, partofs, report=False)
            self.add(applicability, None, "required")


def _same_path(facet: Facet, paths: list[ast.Path]) -> bool:
    return any(facet.name == p.name and facet.pset == p.pset for p in paths)


def _count_comparison(expr: ast.Compare):
    """Match ``COUNT(query) op number`` (either side). Returns (call, number, op) or (None, None, None)."""
    flipped = {"<": ">", "<=": ">=", ">": "<", ">=": "<=", "=": "=", "!=": "!="}
    for call, other, op in ((expr.left, expr.right, expr.op), (expr.right, expr.left, flipped.get(expr.op))):
        if (
            isinstance(call, ast.Call)
            and call.func == "COUNT"
            and isinstance(call.arg, ast.Query)
            and isinstance(other, ast.Literal)
            and other.kind == "number"
        ):
            return call, other.value, op
    return None, None, None


def _literal_kinds(programs: list[ast.Program]) -> dict[str, set[str]]:
    """For each property path, the kinds of literal it is compared with anywhere (used for dataType hints)."""
    kinds: dict[str, set[str]] = {}

    def visit_cond(cond):
        if isinstance(cond, ast.Comparison) and not cond.path.is_attribute:
            kinds.setdefault(str(cond.path), set()).add(cond.literal.kind)
        elif isinstance(cond, ast.InList) and not cond.path.is_attribute:
            kinds.setdefault(str(cond.path), set()).update(lit.kind for lit in cond.literals)
        elif isinstance(cond, ast.Not):
            visit_cond(cond.item)
        elif isinstance(cond, (ast.And, ast.Or)):
            for item in cond.items:
                visit_cond(item)

    def visit(node):
        if isinstance(node, ast.Query):
            for ent in node.chain:
                if ent.condition is not None:
                    visit_cond(ent.condition)
        elif isinstance(node, ast.Call):
            visit(node.arg)
        elif isinstance(node, (ast.BinOp, ast.Compare)):
            visit(node.left)
            visit(node.right)
        elif isinstance(node, ast.Neg):
            visit(node.operand)

    for program in programs:
        for stmt in program.statements:
            visit(stmt.expr)
    return kinds


# ---- grouping and conversion to ifctester ----------------------------------------------------------------


def _group(needs: list[Need]):
    """Group needs by applicability. Prohibitions get their own specifications."""
    groups: dict[tuple, dict] = {}
    for need in needs:
        key = (need.applicability, need.usage == "prohibited")
        group = groups.setdefault(key, {"usage": "optional", "requirements": [], "origins": []})
        if need.usage == "prohibited" or (need.usage == "required" and group["usage"] == "optional"):
            group["usage"] = need.usage
        if need.requirement is not None and not any(
            (r.kind, r.pset, r.name) == (need.requirement.kind, need.requirement.pset, need.requirement.name)
            for r in group["requirements"]
        ):
            group["requirements"].append(need.requirement)
        if need.origin is not None and need.origin not in group["origins"]:
            group["origins"].append(need.origin)
    return [(key[0], g) for key, g in groups.items()]


def _ids_value(value: Value | None):
    if value is None:
        return None
    numeric = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in _values_of(value))
    base = "double" if numeric else "string"
    if value.kind == "exact":
        v = value.items[0]
        if isinstance(v, bool):
            return "TRUE" if v else "FALSE"
        return str(v) if isinstance(v, str) else v
    if value.kind == "enum":
        return ifc_ids.Restriction(options={"enumeration": [str(v) if base == "string" else v for v in value.items]}, base=base)
    return ifc_ids.Restriction(options=dict(value.items), base="double")


def _values_of(value: Value):
    return [v for _, v in value.items] if value.kind == "bounds" else list(value.items)


def _class_name(schema_name: str, cls: str):
    names = concrete_classes(schema_name, cls)
    if len(names) == 1:
        return names[0]
    return ifc_ids.Restriction(options={"enumeration": list(names)})


def _to_ifctester(facet: Facet, schema_name: str):
    if facet.kind == "entity":
        return ifc_ids.Entity(name=_class_name(schema_name, facet.name), predefinedType=_ids_value(facet.value))
    if facet.kind == "partof":
        return ifc_ids.PartOf(name=_class_name(schema_name, facet.name))
    if facet.kind == "attribute":
        return ifc_ids.Attribute(name=facet.name, value=_ids_value(facet.value))
    return ifc_ids.Property(
        propertySet=facet.pset, baseName=facet.name, value=_ids_value(facet.value), dataType=facet.data_type
    )


def _spec_name(applicability: tuple[Facet, ...]) -> str:
    entity, *rest = applicability
    return entity.label() + (" " + ", ".join(f.label() for f in rest) if rest else "")


# ---- public API ---------------------------------------------------------------------------------------------


def _load(sources: Source | Iterable[Source], schema_name: str | None) -> tuple[list[tuple[str, ast.Program]], str]:
    from . import parse  # local import: ifcquery/__init__ imports this module

    if isinstance(sources, (str, Path, ast.Program)):
        sources = [sources]
    items = list(sources)
    if schema_name is None:
        schema_name = next((s.schema for s in items if isinstance(s, ast.Program)), "IFC4")
    loaded = []
    for src in items:
        if isinstance(src, ast.Program):
            if src.schema.upper() != schema_name.upper():
                raise QuerySchemaError(f"program was checked against {src.schema}, not {schema_name}")
            loaded.append(("", src))
        elif isinstance(src, Path):
            loaded.append((src.name, parse(src.read_text(encoding="utf-8"), schema_name)))
        else:
            loaded.append(("", parse(src, schema_name)))
    return loaded, schema_name


def generate_ids(
    sources: Source | Iterable[Source],
    schema: str | None = None,
    title: str = "Requirements derived from IFCQuery queries",
    author: str | None = None,
    description: str | None = None,
    data_types: dict[str, str | None] | None = None,
) -> IdsResult:
    """Build an IDS describing the data the queries need.

    sources:    query text (str), a query file (pathlib.Path), a parsed Program, or an
                iterable of these. Each one is parsed separately, so let-variables stay local.
    schema:     IFC schema to check against (default: the Programs' schema, else "IFC4").
    data_types: dataType per property path, e.g. {"PTMU_Licenciamento.SuperficieTotal": "IFCAREAMEASURE"}.
                None omits the dataType. Overrides the values taken from buildingSMART templates.
    author:     IDS author; must be an e-mail address according to the IDS XSD.
    """
    loaded, schema_name = _load(sources, schema)
    version = ids_version(schema_name)
    data_types = {k: (v.upper() if v else None) for k, v in (data_types or {}).items()}

    collector = _Collector(schema_name, data_types, _literal_kinds([p for _, p in loaded]))
    for label, program in loaded:
        collector.program(program, label)

    result = ifc_ids.Ids(title=title, author=author, description=description)
    for applicability, group in _group(collector.needs):
        spec = ifc_ids.Specification(
            name=_spec_name(applicability),
            ifcVersion=[version],
            description="Needed by:\n" + "\n".join(str(o) for o in group["origins"]),
        )
        spec.set_usage(group["usage"])
        spec.applicability = [_to_ifctester(f, schema_name) for f in applicability]
        spec.requirements = [_to_ifctester(f, schema_name) for f in group["requirements"]]
        result.specifications.append(spec)
    return IdsResult(result, collector.warnings, collector.needs)
