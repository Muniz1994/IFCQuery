"""Static checks run at parse time, before any model is touched.

- IFC class names exist in the schema.
- Non-dotted paths are attributes of the class they're applied to.
- Bare enumeration literals are valid values of the attribute's enumeration.
- Expressions are well typed (e.g. SUM needs a value list).
- Variables are defined before use and bound only once.
"""

from __future__ import annotations

from enum import Enum

from . import ast, schema
from .errors import QuerySchemaError, QueryTypeError


class Type(str, Enum):
    ELEMENTS = "element list"
    VALUES = "value list"
    RECORDS = "record list"
    SCALAR = "scalar"
    BOOLEAN = "boolean"


LIST_TYPES = (Type.ELEMENTS, Type.VALUES, Type.RECORDS)
NUMERIC_AGGREGATES = ("SUM", "AVG", "MIN", "MAX")
ORDERING_OPS = ("<", "<=", ">", ">=")


def _a(t: Type) -> str:
    return ("an " if t.value[0] in "aeiou" else "a ") + t.value


class Checker:
    def __init__(self, schema_name: str):
        self.schema_name = schema_name
        schema.get_schema(schema_name)  # fail early on an unknown schema
        self.env: dict[str, Type] = {}

    # ---- statements ------------------------------------------------------------

    def check_statement(self, stmt: ast.Statement) -> Type:
        if isinstance(stmt, ast.Let):
            if stmt.name in self.env:
                raise QueryTypeError(f"variable {stmt.name!r} is already defined", stmt.line, stmt.column)
            t = self.expr(stmt.expr)
            self.env[stmt.name] = t
            return t
        return self.expr(stmt.expr)

    # ---- expressions -----------------------------------------------------------

    def expr(self, node: ast.Expr) -> Type:
        if isinstance(node, ast.Literal):
            return Type.BOOLEAN if node.kind == "boolean" else Type.SCALAR
        if isinstance(node, ast.Var):
            if node.name not in self.env:
                raise QueryTypeError(f"undefined variable {node.name!r}", node.line, node.column)
            return self.env[node.name]
        if isinstance(node, ast.Query):
            return self.query(node)
        if isinstance(node, ast.Call):
            return self.call(node)
        if isinstance(node, ast.BinOp):
            for side in (node.left, node.right):
                t = self.expr(side)
                if t is not Type.SCALAR:
                    raise QueryTypeError(
                        f"operator {node.op!r} needs scalar operands, got {_a(t)}"
                        + (" (use an aggregate such as SUM or FIRST)" if t in LIST_TYPES else ""),
                        node.line,
                        node.column,
                    )
            return Type.SCALAR
        if isinstance(node, ast.Neg):
            t = self.expr(node.operand)
            if t is not Type.SCALAR:
                raise QueryTypeError(f"unary '-' needs a scalar, got {_a(t)}", node.line, node.column)
            return Type.SCALAR
        if isinstance(node, ast.Compare):
            left, right = self.expr(node.left), self.expr(node.right)
            for t in (left, right):
                if t in LIST_TYPES:
                    raise QueryTypeError(
                        f"cannot compare {_a(t)}; reduce it first with COUNT, SUM, FIRST, ...",
                        node.line,
                        node.column,
                    )
            if node.op in ORDERING_OPS and Type.BOOLEAN in (left, right):
                raise QueryTypeError(f"operator {node.op!r} cannot compare booleans", node.line, node.column)
            return Type.BOOLEAN
        raise TypeError(f"unknown node {node!r}")  # pragma: no cover

    def call(self, node: ast.Call) -> Type:
        t = self.expr(node.arg)
        if node.func == "COUNT":
            if t not in LIST_TYPES:
                raise QueryTypeError(f"COUNT expects a list, got {_a(t)}", node.line, node.column)
        elif node.func in NUMERIC_AGGREGATES:
            if t is not Type.VALUES:
                hint = " (project a numeric value with ->, e.g. IfcSpace -> Qto_SpaceBaseQuantities.NetFloorArea)"
                raise QueryTypeError(
                    f"{node.func} expects a value list, got {_a(t)}" + (hint if t is Type.ELEMENTS else ""),
                    node.line,
                    node.column,
                )
        elif node.func == "FIRST":
            if t not in LIST_TYPES:
                raise QueryTypeError(f"FIRST expects a list, got {_a(t)}", node.line, node.column)
        return Type.SCALAR

    # ---- queries ----------------------------------------------------------------

    def query(self, node: ast.Query) -> Type:
        decl = None
        for ent in node.chain:
            decl = self.entity(ent)
        if node.projection is None:
            return Type.ELEMENTS
        for path in node.projection:
            self.path(path, decl, node.chain[-1].ifc_class)
        return Type.RECORDS if node.records else Type.VALUES

    def entity(self, ent: ast.Entity):
        decl = schema.entity(self.schema_name, ent.ifc_class)
        if decl is None:
            raise QuerySchemaError(
                f"unknown IFC class {ent.ifc_class!r} in schema {self.schema_name}."
                + schema.entity_suggestion(self.schema_name, ent.ifc_class),
                ent.line,
                ent.column,
            )
        if ent.condition is not None:
            self.condition(ent.condition, decl, decl.name())
        return decl

    def path(self, path: ast.Path, decl, cls: str):
        """Return the schema attribute for a direct attribute path, None for Pset.Property."""
        if not path.is_attribute:
            return None
        attr = schema.attribute(decl, path.name)
        if attr is None:
            raise QuerySchemaError(
                f"{cls} has no attribute {path.name!r}."
                + schema.suggest(path.name, schema.attribute_names(decl))
                + " Properties are written PropertySet.Property.",
                path.line,
                path.column,
            )
        return attr

    def condition(self, cond: ast.Condition, decl, cls: str) -> None:
        if isinstance(cond, (ast.And, ast.Or)):
            for item in cond.items:
                self.condition(item, decl, cls)
        elif isinstance(cond, ast.Not):
            self.condition(cond.item, decl, cls)
        elif isinstance(cond, ast.Exists):
            self.path(cond.path, decl, cls)
        elif isinstance(cond, ast.Comparison):
            attr = self.path(cond.path, decl, cls)
            if cond.op in ORDERING_OPS and cond.literal.kind != "number":
                raise QueryTypeError(
                    f"operator {cond.op!r} compares numbers, got {cond.literal.kind} {cond.literal.value!r}",
                    cond.literal.line,
                    cond.literal.column,
                )
            self.literal(cond.literal, attr, cond.path, cls)
        elif isinstance(cond, ast.InList):
            attr = self.path(cond.path, decl, cls)
            for lit in cond.literals:
                self.literal(lit, attr, cond.path, cls)
        else:  # pragma: no cover
            raise TypeError(f"unknown condition {cond!r}")

    def literal(self, lit: ast.Literal, attr, path: ast.Path, cls: str) -> None:
        if lit.kind != "enum" or attr is None:
            # Enumerations on property-set values can't be checked: psets are open.
            return
        items = schema.enum_items(attr)
        if items is None:
            raise QuerySchemaError(
                f"{cls}.{path.name} is not an enumeration; write the value as a quoted string",
                lit.line,
                lit.column,
            )
        if lit.value not in items:
            raise QuerySchemaError(
                f"{lit.value} is not a valid {cls}.{path.name}; expected one of {', '.join(items)}."
                + schema.suggest(str(lit.value), items),
                lit.line,
                lit.column,
            )


def check(statements: tuple[ast.Statement, ...], schema_name: str = "IFC4") -> tuple[Type, ...]:
    """Check statements; raise on the first problem. Returns each statement's type."""
    checker = Checker(schema_name)
    return tuple(checker.check_statement(stmt) for stmt in statements)
