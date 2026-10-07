# Generating an IDS from queries

A query only gives a trustworthy answer if the model contains the data it reads. Take this query:

```
SUM(IfcSpace[PredefinedType = GFA and PTMU_Licenciamento.Afetacao = "Logística"]
    -> Qto_SpaceBaseQuantities.GrossFloorArea)
```

It silently undercounts in two cases: a GFA space without `Afetacao` is skipped, and a logistics space without `GrossFloorArea` adds nothing. `ifcquery.generate_ids` turns a set of queries into a buildingSMART **IDS 1.0** file that states these needs. A model can then be checked for completeness, with any IDS tool, before the rules are trusted.

## Usage

```python
from pathlib import Path
import ifcquery

result = ifcquery.generate_ids(
    [Path("rules.ifq"), Path("listing.ifq")],     # query files, query text, or parsed Programs
    schema="IFC4",                               # IFC2X3, IFC4 or IFC4X3_ADD2
    title="Licensing requirements",
    data_types={"PTMU_Licenciamento.SuperficieTotal": "IFCAREAMEASURE"},  # optional
)
result.to_xml("rules.ids")      # validated against the IDS 1.0 XSD while writing
print(result.to_string())
for warning in result.warnings: # things IDS couldn't express exactly
    print(warning)
```

Each source is parsed separately, so `let` variables stay local to their file. Query errors raise the usual `IfcQueryError` subclasses.

`IdsResult` has these fields:

| Field | Contents |
|---|---|
| `ids` | an `ifctester.ids.Ids`; you can edit it further, or call `.validate(model)` on it |
| `warnings` | list of strings, each naming the source line |
| `needs` | the raw derivations, one per (applicability, requirement); useful for debugging |

Command line (also installed as `ifcquery-ids`):

```bash
python -m ifcquery.idscli examples/queries/rules.ifq examples/queries/dsl_examples.ifq \
    --title "Licensing requirements" -o requirements.ids \
    --data-type PTMU_Licenciamento.SuperficieTotal=IFCAREAMEASURE
```

Without `-o`, the XML goes to stdout. Warnings go to stderr. The exit code is 2 for query or file errors.

To check a model against the result, use ifctester (installed with ifcquery):

```python
import ifcopenshell
from ifctester import ids, reporter
doc = ids.open("requirements.ids", validate=True)
doc.validate(ifcopenshell.open("model.ifc"))
reporter.Console(doc).report()
```

## How queries become specifications

Every path a query reads becomes a requirement. Requirements are grouped into one IDS specification per distinct applicability.

| Query construct | IDS |
|---|---|
| `IfcSpace` | applicability `entity` IFCSPACE. A class with subtypes becomes an enumeration of all its concrete subtypes, because IDS entity facets match exact classes while `IfcWall` in a query includes `IfcWallStandardCase`. |
| `A > B > C` | applicability on C, plus `partOf` A and `partOf` B (no relation, meaning any relation at any depth) |
| `-> P` or `-> (P1, P2)` | each path **required** on the elements the filter selects |
| a path read in a filter conjunct | **required** where the *other* conjuncts hold, so the filter never skips an element because the value is missing |
| `PredefinedType = GFA`, `= "FRACAO"`, `in (...)` | `predefinedType` on the entity facet (IDS uses the same user-defined convention) |
| `Attr = v`, `Pset.P = v` | attribute or property facet with a value |
| `in (a, b)` | value restriction with an enumeration |
| `< <= > >=` | value restriction with bounds, in SI units (as IDS specifies) |
| `exists(P)` | facet without a value; P is the selection, so it is not also required |
| `FIRST(Q ...)` | specification **required**: at least one such element must exist |
| `COUNT(Q) > 0`, `>= 1` | specification **required** |
| `COUNT(Q) = 0` | specification **prohibited** (only when Q translates exactly) |
| `COUNT(Q[c and not exists(P)]) = 0` | P **required** on elements matching `c` |
| anything else | specification **optional**: the requirements apply only if such elements exist |

Example: with `examples/queries/rules.ifq` as input, the data-quality rule

```
COUNT(IfcSpace[PredefinedType = "FRACAO" and not exists(PTMU_Licenciamento.Afetacao)]) = 0
```

becomes "every IfcSpace with predefinedType FRACAO requires `PTMU_Licenciamento.Afetacao`". On the sample model, that specification fails for exactly "Fração D". "Fração E" passes, because it inherits the property from its type.

The output for the example queries is committed at [../examples/ids/licensing_rules.ids](../examples/ids/licensing_rules.ids).

## What IDS can't express

IDS applicability is a plain conjunction of facets with exact values or restrictions. Some conditions can't be translated, and these are handled as follows. Each case produces a warning.

| Condition | What happens |
|---|---|
| `!=`, `~=`, `not ...`, `... or ...` | left out of the applicability, so the specification applies to **more** elements than the query selects |
| a filter on the left of `>` (e.g. `IfcBuildingStorey[Name = "Piso 0"] > IfcSpace`) | `partOf` can't carry it, so it covers spaces in **any** storey. The storey's `Name` is still required on storeys. |
| `COUNT(Q) = 0` where Q isn't exactly translatable | no prohibition is generated, because a broader prohibition would be wrong |

Broadening is the safe direction for requirements. The IDS may ask for a little more data than strictly needed, but never less.

## Data types

`dataType` on property facets is filled in as follows. Earlier sources win.

1. The `data_types` argument (or `--data-type`). A value of `None` (or an empty string on the CLI) omits it.
2. buildingSMART's standard property and quantity templates. `Qto_SpaceBaseQuantities.GrossFloorArea` gives `IFCAREAMEASURE` and `Pset_SpaceCommon.IsExternal` gives `IFCBOOLEAN`. This is the only source used on *applicability* facets.
3. Literals in the queries (requirements only):
   - a property compared only with strings or enumeration words → `IFCLABEL`
   - a property compared only with `true`/`false` → `IFCBOOLEAN`
   - numbers are ambiguous (`IfcReal`, `IfcAreaMeasure`, ...), so no dataType is set

Note that a dataType makes a requirement stricter. For example, a custom property stored as `IfcText` fails an `IFCLABEL` requirement. Use `data_types` to set or drop a type when the hint doesn't fit your models.

## Where the code lives

`src/ifcquery/idsgen.py` (derivation and conversion) and `src/ifcquery/idscli.py` (command line). The derivation first produces plain `Need`/`Facet` dataclasses and only then converts them to ifctester objects, so the rules are easy to test (`tests/test_idsgen.py`).
