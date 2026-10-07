"""IFCQuery: a small query language for IFC models.

    import ifcquery
    results = ifcquery.run('COUNT(IfcSpace[PredefinedType = "FRACAO"])', "model.ifc")
    print(results[0].value)

See README.md and AGENTS.md for an overview, and DSL.md for the language.
"""

from __future__ import annotations

from os import PathLike
from typing import Union

import ifcopenshell

from .ast import Program
from .checker import check as _check
from .errors import (
    IfcQueryError,
    QueryEvaluationError,
    QuerySchemaError,
    QuerySyntaxError,
    QueryTypeError,
)
from .evaluator import ElementList, RecordList, Result, ValueList
from .evaluator import evaluate as _evaluate
from .idsgen import IdsResult, generate_ids
from .parser import parse_syntax

__version__ = "0.1.0"

__all__ = [
    "parse",
    "evaluate",
    "run",
    "schema_of",
    "generate_ids",
    "IdsResult",
    "Program",
    "Result",
    "ElementList",
    "ValueList",
    "RecordList",
    "IfcQueryError",
    "QuerySyntaxError",
    "QuerySchemaError",
    "QueryTypeError",
    "QueryEvaluationError",
]


def parse(text: str, schema: str = "IFC4") -> Program:
    """Parse and check ``text`` against an IFC schema ("IFC2X3", "IFC4", "IFC4X3_ADD2", ...).

    Raises QuerySyntaxError, QuerySchemaError or QueryTypeError, which all
    derive from IfcQueryError and carry ``line`` and ``column``.
    """
    statements = parse_syntax(text)
    types = _check(statements, schema)
    return Program(statements, source=text, schema=schema.upper(), types=tuple(t.value for t in types))


def evaluate(program: Program, model: ifcopenshell.file) -> list[Result]:
    """Run a parsed program on an open model. Returns one Result per statement."""
    return _evaluate(program, model)


def schema_of(model: ifcopenshell.file) -> str:
    """The schema identifier of an open model, e.g. "IFC4"."""
    return getattr(model, "schema_identifier", None) or model.schema


def run(text: str, model: Union[ifcopenshell.file, str, PathLike]) -> list[Result]:
    """Parse ``text`` with the model's schema, then evaluate it.

    ``model`` is an open ``ifcopenshell.file`` or a path to an .ifc file.
    """
    if not isinstance(model, ifcopenshell.file):
        model = ifcopenshell.open(str(model))
    return evaluate(parse(text, schema_of(model)), model)
