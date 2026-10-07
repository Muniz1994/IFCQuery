"""AST node definitions.

The parser turns Lark's parse tree into these frozen dataclasses. Every node
carries ``line`` and ``column`` (1-based) for error reporting; they are
excluded from equality so trees can be compared in tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

_pos = dict(default=0, compare=False, repr=False)


# --- paths and literals -------------------------------------------------------


@dataclass(frozen=True)
class Path:
    """``Name`` (direct attribute, pset is None) or ``Pset.Property``."""

    name: str
    pset: str | None = None
    line: int = field(**_pos)
    column: int = field(**_pos)

    @property
    def is_attribute(self) -> bool:
        return self.pset is None

    def __str__(self) -> str:
        return self.name if self.pset is None else f"{self.pset}.{self.name}"


@dataclass(frozen=True)
class Literal:
    """``kind`` is one of "string", "number", "boolean", "enum"."""

    kind: str
    value: str | float | int | bool
    line: int = field(**_pos)
    column: int = field(**_pos)


# --- filter conditions ----------------------------------------------------------


@dataclass(frozen=True)
class Comparison:
    """``path op literal`` inside a filter. op is one of = != < <= > >= ~=."""

    op: str
    path: Path
    literal: Literal
    line: int = field(**_pos)
    column: int = field(**_pos)


@dataclass(frozen=True)
class InList:
    path: Path
    literals: tuple[Literal, ...]
    line: int = field(**_pos)
    column: int = field(**_pos)


@dataclass(frozen=True)
class Exists:
    path: Path
    line: int = field(**_pos)
    column: int = field(**_pos)


@dataclass(frozen=True)
class And:
    items: tuple["Condition", ...]
    line: int = field(**_pos)
    column: int = field(**_pos)


@dataclass(frozen=True)
class Or:
    items: tuple["Condition", ...]
    line: int = field(**_pos)
    column: int = field(**_pos)


@dataclass(frozen=True)
class Not:
    item: "Condition"
    line: int = field(**_pos)
    column: int = field(**_pos)


Condition = Union[Comparison, InList, Exists, And, Or, Not]


# --- queries ----------------------------------------------------------------------


@dataclass(frozen=True)
class Entity:
    """``IfcClass`` with an optional ``[condition]`` filter."""

    ifc_class: str
    condition: Condition | None = None
    line: int = field(**_pos)
    column: int = field(**_pos)


@dataclass(frozen=True)
class Query:
    """``A > B > C -> projection``.

    ``chain`` holds the entities left to right; the result elements match the
    last one. ``projection`` is None (element list), a 1-tuple (value list
    when ``records`` is False), or several paths (record list, ``records`` True).
    """

    chain: tuple[Entity, ...]
    projection: tuple[Path, ...] | None = None
    records: bool = False
    line: int = field(**_pos)
    column: int = field(**_pos)


# --- expressions -----------------------------------------------------------------


@dataclass(frozen=True)
class Var:
    name: str
    line: int = field(**_pos)
    column: int = field(**_pos)


@dataclass(frozen=True)
class Call:
    """Aggregate call. ``func`` is upper-cased: COUNT SUM AVG MIN MAX FIRST."""

    func: str
    arg: "Expr"
    line: int = field(**_pos)
    column: int = field(**_pos)


@dataclass(frozen=True)
class BinOp:
    """Arithmetic: op is one of + - * /."""

    op: str
    left: "Expr"
    right: "Expr"
    line: int = field(**_pos)
    column: int = field(**_pos)


@dataclass(frozen=True)
class Neg:
    operand: "Expr"
    line: int = field(**_pos)
    column: int = field(**_pos)


@dataclass(frozen=True)
class Compare:
    """Top-level comparison between two expressions (a rule check)."""

    op: str
    left: "Expr"
    right: "Expr"
    line: int = field(**_pos)
    column: int = field(**_pos)


Expr = Union[Literal, Var, Call, BinOp, Neg, Compare, Query]


# --- statements --------------------------------------------------------------------


@dataclass(frozen=True)
class Let:
    name: str
    expr: Expr
    text: str = field(default="", compare=False)
    line: int = field(**_pos)
    column: int = field(**_pos)


@dataclass(frozen=True)
class ExprStatement:
    expr: Expr
    text: str = field(default="", compare=False)
    line: int = field(**_pos)
    column: int = field(**_pos)


Statement = Union[Let, ExprStatement]


@dataclass(frozen=True)
class Program:
    """A parsed and checked program.

    ``schema`` is the IFC schema it was checked against. ``types`` holds each
    statement's static type ("element list", "value list", "record list",
    "scalar", "boolean"), in the same order as ``statements``.
    """

    statements: tuple[Statement, ...]
    source: str = field(default="", compare=False, repr=False)
    schema: str = field(default="IFC4", compare=False)
    types: tuple[str, ...] = field(default=(), compare=False)
