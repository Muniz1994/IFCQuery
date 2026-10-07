# Integrating IFCQuery into another project

This page covers adding IFCQuery to your project, the full public API, and handling errors and results. For the language itself, see [../DSL.md](../DSL.md).

## 1. Adding the dependency

IFCQuery is a standard Python package (`src/` layout, `pyproject.toml`), so any of these works:

| Situation | Command |
|---|---|
| Git submodule (pinned to a commit, easy to patch) | `git submodule add <repo-url> vendor/IFCQuery` then `pip install -e vendor/IFCQuery` |
| Install from git | `pip install "ifcquery @ git+<repo-url>"` (append `@<tag-or-sha>` to pin) |
| `requirements.txt` | `ifcquery @ git+<repo-url>@<sha>` |
| `pyproject.toml` | `dependencies = ["ifcquery @ git+<repo-url>@<sha>"]` |

After a fresh clone of the parent project, run `git submodule update --init` before `pip install -e vendor/IFCQuery`.

Runtime dependencies: `lark>=1.2` and `ifcopenshell>=0.8`. Python 3.10 or newer.

## 2. API reference

Everything is importable from the top-level package: `import ifcquery`.

### `ifcquery.parse(text: str, schema: str = "IFC4") -> Program`

Parses `text` and checks it against an IFC schema. Schema names are the IfcOpenShell identifiers: `"IFC2X3"`, `"IFC4"`, `"IFC4X3_ADD2"`, and so on. These problems are caught here, before any model is opened:

- syntax errors → `QuerySyntaxError`
- unknown IFC class, unknown attribute, invalid enumeration value → `QuerySchemaError`
- type errors such as `SUM(IfcSpace)`, an undefined variable, or a variable bound twice → `QueryTypeError`

A `Program` doesn't change after creation. You can parse it once and evaluate it against many models that use the same schema.

### `ifcquery.evaluate(program: Program, model: ifcopenshell.file) -> list[Result]`

Runs the program and returns one `Result` per statement, in order. It raises `QueryEvaluationError` in these cases:

- An aggregate meets a non-numeric value, e.g. `SUM` over names.
- Arithmetic or an ordering comparison gets text.
- The program uses a class that the model's schema doesn't have.

### `ifcquery.run(text: str, model: ifcopenshell.file | str | PathLike) -> list[Result]`

Convenience wrapper. It opens the model if given a path, parses with the model's own schema, and evaluates.

### `ifcquery.schema_of(model) -> str`

Returns the schema identifier of an open model, e.g. `"IFC4"`. Use it to parse with the correct schema: `ifcquery.parse(text, ifcquery.schema_of(model))`.

### `Result`

A dataclass with these fields:

| Field | Type | Meaning |
|---|---|---|
| `statement` | `str` | Source text of the statement |
| `line` | `int` | 1-based line where the statement starts |
| `kind` | `str` | See the table below |
| `value` | any | The statement's value |
| `passed` | `bool \| None` | Rules only: `True`, `False`, or `None` when inconclusive |
| `name` | `str \| None` | Variable name for `let` statements |

`Result.to_dict()` returns a JSON-serialisable dict. In it, IFC entities become `{"id", "type", "GlobalId", "Name"}`.

| `kind` | Produced by | `value` |
|---|---|---|
| `"elements"` | `IfcSpace[...]`, `A > B` | `ElementList` (a `list`) of `ifcopenshell.entity_instance` |
| `"values"` | `... -> Path` | `ValueList` (a `list`), one entry per element, `None` where missing |
| `"records"` | `... -> (P1, P2)` | `RecordList` (a `list`) of dicts keyed by path text, e.g. `"Qto_SpaceBaseQuantities.NetFloorArea"` |
| `"scalar"` | aggregates, arithmetic, literals | number, string, `None`, or (for `FIRST` of elements) an entity |
| `"rule"` | a top-level comparison | `True` / `False` / `None`; same as `passed` |
| `"binding"` | `let name = ...` | the bound value, of any of the kinds above |

### Errors

```
IfcQueryError            base class; has .message, .line, .column (1-based, may be None)
├── QuerySyntaxError     grammar violation
├── QuerySchemaError     unknown class / attribute / enum value / schema
├── QueryTypeError       static type error
└── QueryEvaluationError runtime problem against a specific model
```

`str(error)` already includes the position: `line 1, column 27: GFAA is not a valid IfcSpace.PredefinedType; ... Did you mean GFA?`.

## 3. Typical integration patterns

### Rule checking service

```python
import ifcopenshell
import ifcquery

RULES = open("rules.ifq", encoding="utf-8").read()

def check_model(path: str) -> dict:
    model = ifcopenshell.open(path)
    try:
        program = ifcquery.parse(RULES, ifcquery.schema_of(model))
        results = ifcquery.evaluate(program, model)
    except ifcquery.IfcQueryError as e:
        return {"ok": False, "error": str(e), "line": e.line, "column": e.column}
    rules = [r for r in results if r.kind == "rule"]
    return {
        "ok": all(r.passed is True for r in rules),
        "rules": [r.to_dict() for r in rules],
    }
```

### Validating user input before running it (e.g. in an editor or form)

```python
try:
    ifcquery.parse(user_text, schema="IFC4")
except ifcquery.IfcQueryError as e:
    show_error(e.line, e.column, e.message)
```

### Working with the returned elements

Element lists hold real `ifcopenshell.entity_instance` objects, so you can keep using IfcOpenShell on them:

```python
import ifcopenshell.util.element as eu

spaces = ifcquery.run('IfcSpace[PredefinedType = "FRACAO"]', model)[0].value
for space in spaces:
    print(space.GlobalId, eu.get_container(space).Name)
```

## 4. Semantics worth knowing

- **Missing values are `None`.** In a filter, any comparison with a missing value is false, including `!=`. Use `exists(...)` / `not exists(...)` to test for presence. In a top-level rule, a missing operand makes the rule inconclusive (`passed is None`). Division by zero also gives `None`.
- **Property lookup** uses the occurrence's value first and falls back to the type object's.
- **Quantities** (anything in an `IfcElementQuantity`, usually a `Qto_` set) are converted to SI units (m, m², m³, kg, s) using the model's unit assignment, or the quantity's own unit if it has one. Ordinary property-set values are returned as stored.
- **`PredefinedType`** falls back to the type object when the occurrence's value is empty or `NOTDEFINED`. Comparing it with a *string* means "this user-defined type", matching `ObjectType` (on the occurrence) or `ElementType` (on the type).
- **Containment `A > B`** follows `IfcRelAggregates` and `IfcRelContainedInSpatialStructure` at any depth. The `A` elements themselves are not part of the result.
- **Multi-valued properties** (lists, enumerations with several values) match a comparison when any of their items matches.

## 5. Command line

```
python -m ifcquery MODEL.ifc "QUERY"
python -m ifcquery MODEL.ifc -f rules.ifq [--json]
```

Installing the package also adds an `ifcquery` console script. Exit codes: `0` means all rules passed, `1` means a rule failed or was inconclusive, `2` means an error.
