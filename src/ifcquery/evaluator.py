"""Runs a checked Program against an IfcOpenShell model."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any

import ifcopenshell

from . import ast
from .checker import Type
from .errors import QueryEvaluationError
from .ifc_access import ModelAccess, is_number, predefined_type


class ElementList(list):
    """List of ifcopenshell entity instances."""


class ValueList(list):
    """One value (or None) per element."""


class RecordList(list):
    """One dict per element, keyed by path text (e.g. "Pset_X.Prop")."""


_KIND = {
    Type.ELEMENTS.value: "elements",
    Type.VALUES.value: "values",
    Type.RECORDS.value: "records",
    Type.SCALAR.value: "scalar",
    Type.BOOLEAN.value: "rule",
}


@dataclass
class Result:
    """The outcome of one statement.

    kind:
      "elements"  value is a list of ifcopenshell entity instances
      "values"    value is a list with one entry (or None) per element
      "records"   value is a list of dicts, one per element
      "scalar"    value is a number, string, bool or None
      "rule"      value and ``passed`` are True, False, or None (inconclusive: a null operand)
      "binding"   a ``let`` statement; ``name`` is the variable, ``value`` its value
    """

    statement: str
    line: int
    kind: str
    value: Any
    passed: bool | None = None
    name: str | None = None

    def to_dict(self) -> dict:
        """A JSON-serialisable form. Entity instances become {id, type, GlobalId, Name}."""
        return {
            "statement": self.statement,
            "line": self.line,
            "kind": self.kind,
            "name": self.name,
            "value": to_json(self.value),
            "passed": self.passed,
        }


def to_json(value: Any) -> Any:
    if isinstance(value, ifcopenshell.entity_instance):
        return {
            "id": value.id(),
            "type": value.is_a(),
            "GlobalId": getattr(value, "GlobalId", None),
            "Name": getattr(value, "Name", None),
        }
    if isinstance(value, dict):
        return {k: to_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json(v) for v in value]
    return value


# ---- comparison helpers ------------------------------------------------------------------


def fold(text: str) -> str:
    """Case- and accent-insensitive form used by ~=."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _equal(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if is_number(a) and is_number(b):
        return a == b
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    return False


def compare(value: Any, op: str, other: Any) -> bool:
    """Filter comparison. Anything compared with a missing value (None) is False."""
    if value is None or other is None:
        return False
    if isinstance(value, (list, tuple)):  # multi-valued property: match any item
        if op == "!=":
            return not compare(value, "=", other)
        return any(compare(v, op, other) for v in value)
    if op == "=":
        return _equal(value, other)
    if op == "!=":
        return not _equal(value, other)
    if op == "~=":
        if isinstance(value, str) and isinstance(other, str):
            return fold(value) == fold(other)
        return _equal(value, other)
    if not (is_number(value) and is_number(other)):
        return False
    return {"<": value < other, "<=": value <= other, ">": value > other, ">=": value >= other}[op]


class _NotUserDefined:
    """Stands in for a non-USERDEFINED PredefinedType when compared with a string.

    It is present (so ``!=`` is true) but never equal to any string."""


# ---- evaluator -----------------------------------------------------------------------------


class Evaluator:
    def __init__(self, model: ifcopenshell.file):
        self.access = ModelAccess(model)
        self.env: dict[str, Any] = {}

    def run(self, program: ast.Program) -> list[Result]:
        results = []
        types = program.types or (None,) * len(program.statements)
        for stmt, stmt_type in zip(program.statements, types):
            value = self.expr(stmt.expr)
            if isinstance(stmt, ast.Let):
                self.env[stmt.name] = value
                results.append(Result(stmt.text, stmt.line, "binding", value, name=stmt.name))
                continue
            kind = _KIND.get(stmt_type, "scalar")
            passed = value if kind == "rule" else None
            results.append(Result(stmt.text, stmt.line, kind, value, passed=passed))
        return results

    # ---- expressions ---------------------------------------------------------------------

    def expr(self, node: ast.Expr) -> Any:
        if isinstance(node, ast.Literal):
            return node.value
        if isinstance(node, ast.Var):
            return self.env[node.name]
        if isinstance(node, ast.Query):
            return self.query(node)
        if isinstance(node, ast.Call):
            return self.call(node)
        if isinstance(node, ast.Neg):
            v = self.expr(node.operand)
            if v is None:
                return None
            self._require_number(v, "unary '-'", node)
            return -v
        if isinstance(node, ast.BinOp):
            return self.arithmetic(node)
        if isinstance(node, ast.Compare):
            return self.rule_compare(node)
        raise TypeError(f"unknown node {node!r}")  # pragma: no cover

    def _require_number(self, value: Any, what: str, node) -> None:
        if not is_number(value):
            raise QueryEvaluationError(f"{what} needs numbers, got {value!r}", node.line, node.column)

    def arithmetic(self, node: ast.BinOp) -> Any:
        left, right = self.expr(node.left), self.expr(node.right)
        if left is None or right is None:
            return None
        self._require_number(left, f"operator {node.op!r}", node)
        self._require_number(right, f"operator {node.op!r}", node)
        if node.op == "+":
            return left + right
        if node.op == "-":
            return left - right
        if node.op == "*":
            return left * right
        return None if right == 0 else left / right

    def rule_compare(self, node: ast.Compare) -> bool | None:
        """Top-level comparison. A missing operand makes the result None (inconclusive)."""
        left, right = self.expr(node.left), self.expr(node.right)
        if left is None or right is None:
            return None
        if node.op in ("<", "<=", ">", ">="):
            self._require_number(left, f"operator {node.op!r}", node)
            self._require_number(right, f"operator {node.op!r}", node)
        return compare(left, node.op, right)

    def call(self, node: ast.Call) -> Any:
        arg = self.expr(node.arg)
        if node.func == "COUNT":
            if isinstance(arg, ValueList):
                return sum(1 for v in arg if v is not None)
            return len(arg)
        if node.func == "FIRST":
            return next((v for v in arg if v is not None), None)
        values = [v for v in arg if v is not None]
        for v in values:
            if not is_number(v):
                raise QueryEvaluationError(f"{node.func} needs numeric values, got {v!r}", node.line, node.column)
        if node.func == "SUM":
            return sum(values)
        if not values:
            return None
        if node.func == "AVG":
            return sum(values) / len(values)
        if node.func == "MIN":
            return min(values)
        if node.func == "MAX":
            return max(values)
        raise TypeError(f"unknown function {node.func}")  # pragma: no cover

    # ---- queries ---------------------------------------------------------------------------

    def query(self, node: ast.Query) -> ElementList | ValueList | RecordList:
        elements = self.select(node.chain)
        if node.projection is None:
            return elements
        if node.records:
            return RecordList({str(p): self.access.value(e, p) for p in node.projection} for e in elements)
        path = node.projection[0]
        return ValueList(self.access.value(e, path) for e in elements)

    def select(self, chain: tuple[ast.Entity, ...]) -> ElementList:
        current = self._filtered(chain[0], None)
        for ent in chain[1:]:
            current = self._filtered(ent, self.access.descendant_ids(current))
        return ElementList(current)

    def _filtered(self, ent: ast.Entity, within: set[int] | None) -> list:
        out = []
        for e in self.access.elements(ent.ifc_class):
            if within is not None and e.id() not in within:
                continue
            if ent.condition is None or self.matches(e, ent.condition):
                out.append(e)
        return out

    # ---- conditions --------------------------------------------------------------------------

    def matches(self, element, cond: ast.Condition) -> bool:
        if isinstance(cond, ast.And):
            return all(self.matches(element, c) for c in cond.items)
        if isinstance(cond, ast.Or):
            return any(self.matches(element, c) for c in cond.items)
        if isinstance(cond, ast.Not):
            return not self.matches(element, cond.item)
        if isinstance(cond, ast.Exists):
            if cond.path.is_attribute and cond.path.name == "PredefinedType":
                return predefined_type(element)[0] is not None
            return self.access.value(element, cond.path) is not None
        if isinstance(cond, ast.Comparison):
            return compare(self._operand(element, cond.path, cond.literal), cond.op, cond.literal.value)
        if isinstance(cond, ast.InList):
            return any(compare(self._operand(element, cond.path, lit), "=", lit.value) for lit in cond.literals)
        raise TypeError(f"unknown condition {cond!r}")  # pragma: no cover

    def _operand(self, element, path: ast.Path, literal: ast.Literal) -> Any:
        """The element-side value for a filter comparison against ``literal``."""
        if path.is_attribute and path.name == "PredefinedType":
            raw, user = predefined_type(element)
            if raw is None:
                return None
            if literal.kind == "string":
                # A string means "the user-defined type" (IDS convention).
                return user if raw == "USERDEFINED" else _NotUserDefined()
            return raw
        return self.access.value(element, path)


def evaluate(program: ast.Program, model: ifcopenshell.file) -> list[Result]:
    """Evaluate a parsed program against a model. Returns one Result per statement."""
    return Evaluator(model).run(program)
