# Architecture

```
text ──► Lark (grammar.lark) ──► parse tree ──► _ToAst ──► AST (ast.py)
                                                              │
                         IFC schema (schema.py) ──► checker.py │  raises QuerySchemaError / QueryTypeError
                                                              ▼
                                                           Program
                                                              │
                     ifcopenshell.file ──► ifc_access.py ──► evaluator.py ──► list[Result]
```

Parsing and checking never touch a model. Evaluation never re-parses.

## Modules (`src/ifcquery/`)

| File | Responsibility |
|---|---|
| `grammar.lark` | The grammar. Mirrors the EBNF in DSL.md. Comments in the file explain the lexing tricks. |
| `parser.py` | Builds the Lark LALR parser (cached), the newline postlexer, the `_ToAst` transformer, and friendly syntax-error messages. Entry point: `parse_syntax(text)`. |
| `ast.py` | Frozen dataclasses for every node. Positions (`line`, `column`) are excluded from equality. |
| `schema.py` | IFC schema lookups through `ifcopenshell.ifcopenshell_wrapper`: entity by name (case-insensitive), attributes, enumeration items, "did you mean" suggestions. |
| `checker.py` | Static pass. Resolves classes, checks direct attributes and enum literals against the class, and infers a `Type` per expression (element list, value list, record list, scalar, boolean). |
| `ifc_access.py` | Everything that reads an IFC model: selection by class, attributes, `PredefinedType` resolution, pset values, quantity units, and containment descendants. |
| `evaluator.py` | Walks the AST against a model. Defines `Result` and the list wrappers `ElementList`, `ValueList` and `RecordList`, plus the comparison semantics (`compare`, `fold`). |
| `idsgen.py` | IDS generation (see [ids.md](ids.md)). It walks checked programs into `Need`/`Facet` dataclasses, groups them by applicability, and converts them to `ifctester.ids` objects. |
| `idscli.py` | `python -m ifcquery.idscli` / `ifcquery-ids`. |
| `errors.py` | Exception hierarchy. |
| `__init__.py` | Public API: `parse`, `evaluate`, `run`, `schema_of`. |
| `cli.py`, `__main__.py` | `python -m ifcquery`. |

## Parsing details

**Contextual lexer.** Lark's contextual lexer only tries the terminals the parser can accept in its current state. That is how the same bare word is read differently depending on position:

- in literal position (after `=` in a filter) it is `ENUM`
- in path position it is a `NAME`
- in expression position it is a `NAME` used as a variable

Keywords and function names are case-insensitive regex terminals ending in `\b` with a higher priority than `NAME`. So `count` is reserved, but `country` is a name.

**`>` versus containment.** `CONTAINS` is the regex `>(?=\s*ifc)` (case-insensitive) with a higher priority than `GT`. Inside a filter the right-hand side is a literal, never a class name, so `>` there is always greater-than.

**Newlines.** `_NL` ends a statement. Three mechanisms shape it:

1. `_NewlineFilter` (the postlexer) drops `_NL` inside `()` and `[]`, as well as `_NL` before the first statement.
2. `_CONTINUATION` is an ignored terminal. It matches line breaks followed by a line that starts with a binary operator (`->`, `>`, `<`, `=`, `!=`, `~=`, `+`, `*`, `/`, `and`, `or`), so that line continues the statement. `-` is deliberately excluded because it can start a new statement (unary minus).
3. `_TRAILING` swallows whitespace and comments at the end of the text.

Comment-only and blank lines are folded into a single `_NL`.

## Evaluation details

- Selection uses `model.by_type(cls, include_subtypes=True)`, then applies the filter.
- `A > B > C` evaluates left to right. Each step collects the IDs of all descendants of the current set via `IsDecomposedBy` and `ContainsElements`, then keeps the matching elements of the next class.
- Pset values come from `ifcopenshell.util.element.get_pset(..., should_inherit=True)`. For numeric values, the owning `IfcElementQuantity` is located to find the quantity kind and convert units (`ifcopenshell.util.unit.calculate_unit_scale(model, "AREAUNIT")` etc., cached per model).
- `let` values live in `Evaluator.env`. Statement kinds come from the checker's types stored in `Program.types`.

## Extending

**Add an aggregate function** (e.g. `MEDIAN`):

1. Add it to the `FUNC` regex in `grammar.lark`.
2. Add its type rule in `Checker.call` (`checker.py`).
3. Implement it in `Evaluator.call` (`evaluator.py`).
4. Document it in DSL.md and AGENTS.md, and add tests in `tests/test_checker.py` and `tests/test_evaluator.py`.

**Add a filter operator** (e.g. `like`):

1. Add a terminal and a branch in the `atom` rule (`grammar.lark`).
2. Add a transformer method and AST node (`parser.py`, `ast.py`).
3. Handle it in `Checker.condition` and `Evaluator.matches`.

**Support another relationship in containment** (e.g. `IfcRelNests`): extend `ModelAccess.descendant_ids` in `ifc_access.py`.

**Language changes and IDS generation:** a new condition or function may need a mapping in `idsgen.py`:
- conditions go in `_Collector.facet_for`, which returns None when the condition can't be expressed
- statement-level patterns go in `_Collector.rule_pattern`

**Change how values are read** (e.g. units for non-quantity properties): `ModelAccess.value` / `property_value` in `ifc_access.py` is the only place to change.

## Tests (`tests/`)

| File | Covers |
|---|---|
| `test_parser.py` | Grammar, AST shape, newlines and comments, error positions |
| `test_spec_examples.py` | Every untagged code block in DSL.md parses and type-checks |
| `test_checker.py` | Schema validation and static types |
| `test_evaluator.py` | Semantics against the sample model (metres and millimetres) |
| `test_cli.py` | Command line, including every file in `examples/queries/` |
| `test_idsgen.py` | IDS derivation rules, XSD validity, and round trips that validate the sample models with ifctester |

The sample model is built in memory by `examples/build_sample_models.py`, the same code that writes the committed `.ifc` files. Its docstring lists the model's content, which is what the expected values in the tests are based on.
