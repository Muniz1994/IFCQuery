"""Command line: ``python -m ifcquery MODEL.ifc "QUERY"`` or ``python -m ifcquery MODEL.ifc -f rules.ifq``.

Exit codes: 0 when everything ran and every rule passed, 1 when a rule
failed or was inconclusive, 2 for query or model errors.
"""

from __future__ import annotations

import argparse
import json
import sys

import ifcopenshell

from . import IfcQueryError, evaluate, parse, schema_of
from .evaluator import Result, to_json


def _format_value(value) -> str:
    data = to_json(value)
    if isinstance(data, dict) and "type" in data and "id" in data:
        return f"#{data['id']} {data['type']} {data['Name']!r}"
    if isinstance(data, list):
        if not data:
            return "[]"
        return "\n" + "\n".join(f"  {_format_value(v)}" for v in value)
    return repr(data)


def _format(result: Result) -> str:
    lines = result.statement.splitlines() or [""]
    head = f"[line {result.line}] {lines[0]}" + (" ..." if len(lines) > 1 else "")
    if result.kind == "rule":
        status = {True: "PASS", False: "FAIL", None: "INCONCLUSIVE"}[result.passed]
        return f"{head}\n  => {status}"
    shown = _format_value(result.value)
    sep = "" if shown.startswith("\n") else " "
    if result.kind == "binding":
        return f"{head}\n  {result.name} ={sep}{shown}"
    return f"{head}\n  =>{sep}{shown}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ifcquery", description="Run IFCQuery statements against an IFC model.")
    ap.add_argument("model", help="path to an .ifc file")
    ap.add_argument("query", nargs="?", help="query text (or use -f)")
    ap.add_argument("-f", "--file", help="read the query from a file")
    ap.add_argument("--json", action="store_true", help="print results as JSON")
    args = ap.parse_args(argv)

    if (args.query is None) == (args.file is None):
        ap.error("give either a query or -f FILE")
    text = args.query
    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            text = fh.read()

    try:
        model = ifcopenshell.open(args.model)
    except Exception as e:  # IfcOpenShell raises several exception types
        print(f"error: cannot open {args.model}: {e}", file=sys.stderr)
        return 2
    try:
        results = evaluate(parse(text, schema_of(model)), model)
    except IfcQueryError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.json:
        json.dump([r.to_dict() for r in results], sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        print("\n".join(_format(r) for r in results))
    rules = [r for r in results if r.kind == "rule"]
    return 0 if all(r.passed is True for r in rules) else 1
