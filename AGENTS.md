# AGENTS.md — IFCQuery quick reference for LLM agents

IFCQuery is a Python package that parses a small query language for IFC models (with Lark) and evaluates it (with IfcOpenShell). Full spec: `DSL.md`. Integration guide: `docs/integration.md`. Code map: `docs/architecture.md`.

## Use it

```python
import ifcquery
results = ifcquery.run(query_text, "model.ifc")      # or an open ifcopenshell.file
program = ifcquery.parse(query_text, schema="IFC4")  # validate without a model
results = ifcquery.evaluate(program, model)
```

Each `Result` has `.kind`, `.value`, `.passed`, `.name`, `.line`, `.statement` and `.to_dict()`.

| kind | value |
|---|---|
| `elements` | list of `ifcopenshell.entity_instance` |
| `values` | list, one entry per element, `None` if missing |
| `records` | list of dicts keyed by path text |
| `scalar` | number / string / None |
| `rule` | True / False / None. `passed` holds the same value. None means inconclusive |
| `binding` | value of a `let`. `name` holds the variable |

All errors subclass `ifcquery.IfcQueryError` and carry `.line` and `.column`. The subclasses are `QuerySyntaxError`, `QuerySchemaError`, `QueryTypeError` and `QueryEvaluationError`.

CLI: `python -m ifcquery MODEL.ifc "QUERY"` or `-f FILE.ifq`, optionally with `--json`. Exit code 0 means all rules passed, 1 means a rule failed or was inconclusive, 2 means an error.

## Write queries

```
IfcSpace                                   // all spaces (subtypes included)
IfcSpace[Name = "Sala 1"]                  // filter on a direct attribute
IfcSpace[Pset_X.Prop >= 10]                // filter on a property: PropertySet.Property
IfcSpace[PredefinedType = GFA]             // bare UPPERCASE = enumeration, checked against the schema
IfcSpace[PredefinedType = "FRACAO"]        // string = USERDEFINED with ObjectType/ElementType "FRACAO"
IfcSpace[P.A in ("x", "y") and not exists(P.B) or P.C ~= "logistica"]
IfcBuildingStorey[Name = "Piso 0"] > IfcSpace          // containment, any depth
IfcSpace -> Qto_SpaceBaseQuantities.NetFloorArea       // projection to values (SI units for quantities)
IfcSpace -> (Name, P.A)                                // projection to records
COUNT(x)  SUM(x)  AVG(x)  MIN(x)  MAX(x)  FIRST(x)
let a = SUM(IfcSpace -> Qto_SpaceBaseQuantities.GrossFloorArea)
let b = FIRST(IfcSite -> PTMU_Licenciamento.SuperficieTotal)
a / b <= 0.6                               // rule check
"Identity Data"."Assembly Code"            // quote names with spaces
// comment   (# is NOT a comment)
```

Operators: `= != < <= > >= ~=` (`~=` ignores case and accents), plus `in (...)` and `exists(path)`. Precedence is `not`, then `and`, then `or`. Arithmetic is `+ - * /`.

## Rules that trip people up

1. Strings are always double-quoted. A bare word in value position must be an UPPERCASE enumeration value valid for that attribute, otherwise it's a parse error.
2. Any identifier starting with `Ifc` (any case) is a class name where an expression is expected, so it can't be a `let` variable name.
3. A non-dotted path must be a real schema attribute of the class (case-sensitive: `Name`, not `name`). Properties always need `PsetName.PropName`.
4. `SUM/AVG/MIN/MAX` need a value list. Use `SUM(IfcSpace -> Qto.X)`, not `SUM(IfcSpace)`. `COUNT` takes elements or values (it counts non-null values).
5. In a filter, a missing value makes every comparison false, including `!=`. Use `exists()`.
6. `>` means containment only when an IFC class follows. Otherwise it is greater-than.
7. One statement per line. A statement continues onto the next line when it is inside `()`/`[]`, or when that line starts with a binary operator such as `->`, `>`, `and`, or `+`. A line starting with `-` begins a new statement.
8. `let` names can't be rebound, and the names `count`, `sum`, `avg`, `min`, `max`, `first`, `let`, `and`, `or`, `not`, `in`, `exists`, `true` and `false` are reserved (in any case).
9. Ordering comparisons (`<`, `>`, ...) need numbers. Comparing text raises an error at parse time (filters) or at run time (rules).

## Work on the code

- Setup: `python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"` (or `.venv/bin/pip` on Linux and macOS). Run the tests with `.venv/Scripts/python -m pytest`.
- Pipeline: `grammar.lark` → `parser.py` (Lark tree → `ast.py` dataclasses) → `checker.py` (schema and types) → `evaluator.py` + `ifc_access.py`.
- When you change the language: update `DSL.md` too. `tests/test_spec_examples.py` parses every untagged code block in it.
- Sample models: `python examples/build_sample_models.py` regenerates `examples/models/*.ifc`. Its docstring lists the model content that the test expectations rely on.
