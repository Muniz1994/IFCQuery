"""Exception hierarchy. Every error raised by ifcquery derives from IfcQueryError."""

from __future__ import annotations


class IfcQueryError(Exception):
    """Base class. ``line`` and ``column`` are 1-based and may be None."""

    def __init__(self, message: str, line: int | None = None, column: int | None = None):
        self.message = message
        self.line = line
        self.column = column
        where = f"line {line}, column {column}: " if line is not None else ""
        super().__init__(f"{where}{message}")


class QuerySyntaxError(IfcQueryError):
    """The text does not follow the grammar."""


class QuerySchemaError(IfcQueryError):
    """Unknown IFC class, unknown attribute, or enumeration value not in the schema."""


class QueryTypeError(IfcQueryError):
    """An operator or function received a value of the wrong type (e.g. SUM of an element list)."""


class QueryEvaluationError(IfcQueryError):
    """A problem found only while running against a model (e.g. summing a text value)."""
