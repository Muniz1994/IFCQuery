"""Command line for IDS generation: ``python -m ifcquery.idscli rules.ifq -o rules.ids``.

Also installed as the ``ifcquery-ids`` console script. Warnings go to stderr.
Exit code 0 on success, 2 on query or file errors.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .errors import IfcQueryError
from .idsgen import generate_ids


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="ifcquery-ids", description="Generate an IDS file from IFCQuery query files."
    )
    ap.add_argument("files", nargs="+", help="query files (.ifq)")
    ap.add_argument("-o", "--output", help="output .ids file (default: print to stdout)")
    ap.add_argument("--schema", default="IFC4", help="IFC schema: IFC2X3, IFC4 or IFC4X3_ADD2 (default IFC4)")
    ap.add_argument("--title", default="Requirements derived from IFCQuery queries")
    ap.add_argument("--author", help="author e-mail address")
    ap.add_argument(
        "--data-type",
        action="append",
        default=[],
        metavar="PSET.PROP=TYPE",
        help="set a property's dataType, e.g. PTMU_Licenciamento.SuperficieTotal=IFCAREAMEASURE",
    )
    args = ap.parse_args(argv)

    data_types = {}
    for item in args.data_type:
        key, sep, value = item.partition("=")
        if not sep:
            ap.error(f"--data-type expects PSET.PROP=TYPE, got {item!r}")
        data_types[key] = value or None

    try:
        result = generate_ids(
            [Path(f) for f in args.files], schema=args.schema, title=args.title, author=args.author, data_types=data_types
        )
    except (IfcQueryError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    for w in result.warnings:
        print(f"warning: {w}", file=sys.stderr)
    if args.output:
        result.to_xml(args.output)
        print(f"wrote {args.output} ({len(result.ids.specifications)} specifications)", file=sys.stderr)
    else:
        sys.stdout.write(result.to_string())
    return 0



if __name__ == "__main__":
    sys.exit(main())
