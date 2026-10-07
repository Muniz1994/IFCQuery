# IFCQuery

A small query language for IFC (BIM) models, with a parser built on [Lark](https://github.com/lark-parser/lark) and an evaluator built on [IfcOpenShell](https://ifcopenshell.org).

```
let implantacao = SUM(IfcSpace[PredefinedType = "IMPLANTACAO"] -> Qto_SpaceBaseQuantities.GrossFloorArea)
let terreno     = FIRST(IfcSite -> PTMU_Licenciamento.SuperficieTotal)
implantacao / terreno <= 0.6
```

A query selects elements by IFC class (`IfcSpace`), narrows them with a filter (`[...]`), and can walk down the spatial hierarchy (`IfcBuildingStorey > IfcSpace`). It extracts values with `->`, reduces them with `COUNT`, `SUM`, `AVG`, `MIN`, `MAX` and `FIRST`, and combines results with `let` and arithmetic into pass/fail rule checks.

- **Language reference:** [DSL.md](DSL.md)
- **Using it from another project:** [docs/integration.md](docs/integration.md)
- **How the code is organised:** [docs/architecture.md](docs/architecture.md)
- **Compact guide for LLM agents:** [AGENTS.md](AGENTS.md)

## Install

Requires Python 3.10+. Dependencies are `lark` and `ifcopenshell`, both installed automatically.

**As a git submodule** (recommended while the project is young):

```bash
git submodule add https://github.com/Muniz1994/IFCQuery.git vendor/IFCQuery
pip install -e vendor/IFCQuery
```

**Straight from git:**

```bash
pip install "ifcquery @ git+https://github.com/Muniz1994/IFCQuery.git"
```

**For development:**

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"      # Windows: .venv\Scripts\pip
.venv/bin/pytest
```

## Quick start

```python
import ifcquery

results = ifcquery.run(
    """
    let abc     = SUM(IfcSpace[PredefinedType = GFA] -> Qto_SpaceBaseQuantities.GrossFloorArea)
    let terreno = FIRST(IfcSite -> PTMU_Licenciamento.SuperficieTotal)
    abc / terreno <= 1.2
    """,
    "examples/models/licensing_sample.ifc",
)

for r in results:
    print(r.line, r.kind, r.name, r.value, r.passed)
# 2 binding abc 500.0 None
# 3 binding terreno 2000.0 None
# 4 rule None True True
```

To parse once and run against many models:

```python
program = ifcquery.parse(text, schema="IFC4")   # raises on syntax, schema or type errors
for model in models:                            # ifcopenshell.file objects
    results = ifcquery.evaluate(program, model)
```

## Command line

```bash
python -m ifcquery examples/models/licensing_sample.ifc 'COUNT(IfcSpace[PredefinedType = "FRACAO"])'
python -m ifcquery examples/models/licensing_sample.ifc -f examples/queries/rules.ifq
python -m ifcquery examples/models/licensing_sample.ifc -f examples/queries/rules.ifq --json
```

Exit codes: `0` means every rule passed. `1` means a rule failed or was inconclusive. `2` means the query or the model has an error.

## Repository layout

```
DSL.md                       language specification
src/ifcquery/                the package (parser, checker, evaluator, CLI)
examples/models/*.ifc        sample IFC4 models (metres and millimetres)
examples/queries/*.ifq       runnable query files
examples/build_sample_models.py  regenerates the sample models
tests/                       pytest suite
docs/                        integration and architecture guides
AGENTS.md                    compact reference for LLM agents
```

## License

MIT, see [LICENSE](LICENSE).
