"""IDS generation: derivation rules, XML validity, and round trips against the sample models."""

from pathlib import Path

import ifcopenshell
import pytest
from ifctester import ids as ifc_ids

import ifcquery
from ifcquery import QuerySchemaError, generate_ids
from ifcquery.idscli import main as ids_main
from ifcquery.idsgen import concrete_classes, template_data_type

from build_sample_models import build_licensing_model
from conftest import EXAMPLES


def summary(result):
    """{spec name: (usage, [requirement labels])} for compact assertions."""
    out = {}
    for spec in result.ids.specifications:
        usage = spec.get_usage()
        reqs = []
        for r in spec.requirements:
            if isinstance(r, ifc_ids.Property):
                reqs.append(f"{r.propertySet}.{r.baseName}" + (f":{r.dataType}" if r.dataType else ""))
            else:
                reqs.append(r.name)
        out[spec.name] = (usage, reqs)
    return out


def validate(result, model, tmp_path):
    """Write, re-read with XSD validation, validate the model. Returns {spec name: spec}."""
    path = tmp_path / "out.ids"
    result.to_xml(path)
    doc = ifc_ids.open(str(path), validate=True)
    doc.validate(model)
    return {s.name: s for s in doc.specifications}


def failing(spec):
    return sorted(f["element"].Name for r in spec.requirements for f in r.failures)


# ---- projection and filter requirements ----------------------------------------------------------------


def test_projection_required_on_selected_elements():
    r = generate_ids("IfcSpace[PredefinedType = GFA] -> Qto_SpaceBaseQuantities.GrossFloorArea")
    assert summary(r) == {
        "IfcSpace[PredefinedType = GFA]": ("optional", ["Qto_SpaceBaseQuantities.GrossFloorArea:IFCAREAMEASURE"])
    }


def test_filter_paths_required_where_other_conjuncts_hold():
    r = generate_ids(
        'SUM(IfcSpace[PredefinedType = GFA and PTMU_Licenciamento.Afetacao = "Logística"]'
        " -> Qto_SpaceBaseQuantities.GrossFloorArea)"
    )
    assert summary(r) == {
        "IfcSpace[PredefinedType = GFA]": ("optional", ["PTMU_Licenciamento.Afetacao:IFCLABEL"]),
        'IfcSpace[PredefinedType = GFA] PTMU_Licenciamento.Afetacao = "Logística"': (
            "optional",
            ["Qto_SpaceBaseQuantities.GrossFloorArea:IFCAREAMEASURE"],
        ),
    }


def test_attribute_paths():
    r = generate_ids('IfcSpace[ObjectType = "FRACAO"] -> Name')
    assert summary(r) == {
        "IfcSpace": ("optional", ["ObjectType"]),
        'IfcSpace ObjectType = "FRACAO"': ("optional", ["Name"]),
    }


def test_exists_is_selection_not_requirement():
    r = generate_ids("IfcSpace[exists(P.A)] -> P.B")
    assert summary(r) == {"IfcSpace P.A exists": ("optional", ["P.B"])}


def test_predefined_type_is_never_a_requirement():
    r = generate_ids('COUNT(IfcSpace[PredefinedType = "FRACAO"])\nIfcSpace -> PredefinedType')
    assert summary(r) == {}


def test_or_and_not_conjuncts():
    r = generate_ids('IfcSpace[PredefinedType = "FRACAO" and (P.A = "x" or not P.B = 1)] -> Name')
    s = summary(r)
    # Paths in the `or` are required where the other conjunct holds; the projection lands in the
    # same specification because the lossy `or` is left out of its applicability.
    assert s == {'IfcSpace[PredefinedType = "FRACAO"]': ("optional", ["P.A:IFCLABEL", "P.B", "Name"])}
    assert any("can't be expressed in IDS" in w for w in r.warnings)


@pytest.mark.parametrize("cond", ['P.A != "x"', 'P.A ~= "x"', "not exists(P.A)"])
def test_lossy_conditions_broaden_and_warn(cond):
    r = generate_ids(f"IfcSpace[{cond}] -> Name")
    assert summary(r)["IfcSpace"][1][-1] == "Name"
    assert len(r.warnings) == 1 and "line 1" in r.warnings[0]


def test_in_list_and_bounds():
    r = generate_ids('IfcSpace[P.A in ("a", "b") and Qto_SpaceBaseQuantities.GrossFloorArea >= 100] -> Name')
    spec = r.ids.specifications[-1]
    prop_a, area = spec.applicability[1], spec.applicability[2]
    assert prop_a.value.options == {"enumeration": ["a", "b"]}
    assert area.value.options == {"minInclusive": 100}
    assert area.dataType == "IFCAREAMEASURE"


def test_predefined_type_in_list():
    r = generate_ids("IfcSpace[PredefinedType in (GFA, INTERNAL)] -> Name")
    entity = r.ids.specifications[0].applicability[0]
    assert entity.predefinedType.options == {"enumeration": ["GFA", "INTERNAL"]}


# ---- classes and containment ---------------------------------------------------------------------------


def test_subtypes_become_an_enumeration():
    assert concrete_classes("IFC4", "IfcWall") == ("IFCWALL", "IFCWALLELEMENTEDCASE", "IFCWALLSTANDARDCASE")
    assert concrete_classes("IFC4", "IfcSpace") == ("IFCSPACE",)
    r = generate_ids("IfcWall -> Name")
    assert r.ids.specifications[0].applicability[0].name.options["enumeration"][0] == "IFCWALL"


def test_containment_chain_becomes_partof():
    r = generate_ids('IfcBuilding[Name = "Bloco A"] > IfcBuildingStorey > IfcSpace -> P.A')
    s = summary(r)
    assert s["IfcBuilding"] == ("optional", ["Name"])
    assert s["IfcSpace in IfcBuilding, in IfcBuildingStorey"] == ("optional", ["P.A"])
    assert any("left of `>`" in w for w in r.warnings)


# ---- rule patterns ----------------------------------------------------------------------------------------


def test_first_makes_specification_required():
    r = generate_ids("let t = FIRST(IfcSite -> PTMU_Licenciamento.SuperficieTotal)")
    assert summary(r) == {"IfcSite": ("required", ["PTMU_Licenciamento.SuperficieTotal"])}


def test_data_quality_pattern():
    r = generate_ids(
        'COUNT(IfcSpace[PredefinedType = "FRACAO" and not exists(PTMU_Licenciamento.Afetacao)]) = 0'
    )
    assert summary(r) == {'IfcSpace[PredefinedType = "FRACAO"]': ("optional", ["PTMU_Licenciamento.Afetacao"])}
    assert r.warnings == []


def test_count_zero_is_prohibited():
    r = generate_ids("COUNT(IfcSpace[PredefinedType = PARKING]) = 0")
    assert summary(r) == {"IfcSpace[PredefinedType = PARKING]": ("prohibited", [])}


def test_count_zero_lossy_is_skipped():
    r = generate_ids('COUNT(IfcSpace[Name ~= "x"]) = 0')
    assert all(usage != "prohibited" for usage, _ in summary(r).values())
    assert any("no prohibition" in w for w in r.warnings)


@pytest.mark.parametrize("rule", ["COUNT(IfcSite) > 0", "COUNT(IfcSite) >= 1", "0 < COUNT(IfcSite)"])
def test_count_positive_is_required(rule):
    assert summary(generate_ids(rule)) == {"IfcSite": ("required", [])}


# ---- data types, grouping, sources ------------------------------------------------------------------------


def test_template_data_types():
    assert template_data_type("IFC4", "Qto_SpaceBaseQuantities", "NetFloorArea") == "IFCAREAMEASURE"
    assert template_data_type("IFC4", "Qto_WallBaseQuantities", "Length") == "IFCLENGTHMEASURE"
    assert template_data_type("IFC4", "Pset_SpaceCommon", "IsExternal") == "IFCBOOLEAN"
    assert template_data_type("IFC4", "PTMU_Licenciamento", "Afetacao") is None


def test_literal_hints_and_overrides():
    text = 'IfcSpace[P.Text = "a"]\nIfcSpace[P.Flag = true]\nIfcSpace[P.Num > 3]'
    reqs = summary(generate_ids(text))["IfcSpace"][1]
    assert sorted(reqs) == ["P.Flag:IFCBOOLEAN", "P.Num", "P.Text:IFCLABEL"]
    reqs = summary(generate_ids(text, data_types={"P.Num": "IfcReal", "P.Text": None}))["IfcSpace"][1]
    assert sorted(reqs) == ["P.Flag:IFCBOOLEAN", "P.Num:IFCREAL", "P.Text"]


def test_grouping_and_dedup_across_sources():
    r = generate_ids(["IfcSpace -> P.A", "IfcSpace -> (P.A, P.B)\nlet x = COUNT(IfcSpace -> P.A)"])
    assert summary(r) == {"IfcSpace": ("optional", ["P.A", "P.B"])}
    description = r.ids.specifications[0].description
    assert description.count("line") == 3


def test_path_sources_are_labelled(tmp_path):
    f = tmp_path / "q.ifq"
    f.write_text("IfcSpace -> P.A", encoding="utf-8")
    r = generate_ids(f)
    assert "q.ifq:1" in r.ids.specifications[0].description


def test_program_sources_and_schema():
    program = ifcquery.parse("IfcAlignment -> Name", "IFC4X3_ADD2")
    r = generate_ids(program)
    assert r.ids.specifications[0].ifcVersion == ["IFC4X3_ADD2"]
    with pytest.raises(QuerySchemaError):
        generate_ids(program, schema="IFC4")


def test_query_errors_propagate():
    with pytest.raises(ifcquery.QuerySchemaError):
        generate_ids("IfcSpace[PredefinedType = GFAA] -> Name")


# ---- XML and round trips ----------------------------------------------------------------------------------


def test_xml_is_valid_ids(tmp_path):
    r = generate_ids(
        [Path(EXAMPLES / "queries" / n) for n in ("rules.ifq", "dsl_examples.ifq", "listing.ifq")]
        + ["COUNT(IfcSpace[PredefinedType = PARKING]) = 0", "IfcSite[Pset_X.Flag = true] -> Name"]
    )
    path = tmp_path / "all.ids"
    r.to_xml(path)
    assert len(ifc_ids.open(str(path), validate=True).specifications) == len(r.ids.specifications)
    assert r.to_string().startswith("<ids")


def test_round_trip_rules(sample_path, tmp_path):
    r = generate_ids(EXAMPLES / "queries" / "rules.ifq")
    specs = validate(r, ifcopenshell.open(str(sample_path)), tmp_path)
    fracao = specs['IfcSpace[PredefinedType = "FRACAO"]']
    assert failing(fracao) == ["Fração D"]  # Fração E gets Afetacao from its type
    assert specs["IfcSite"].status is True
    assert specs['IfcSpace[PredefinedType = "IMPLANTACAO"]'].status is True
    assert specs["IfcSpace[PredefinedType = GFA]"].status is True


def test_round_trip_units(model_mm, tmp_path):
    # Bounds are written in SI; the mm model stores mm², so both sides must convert.
    r = generate_ids("IfcSpace[Qto_SpaceBaseQuantities.GrossFloorArea >= 300] -> P.Missing")
    spec = validate(r, model_mm, tmp_path)["IfcSpace Qto_SpaceBaseQuantities.GrossFloorArea >= 300"]
    assert sorted(e.Name for e in spec.applicable_entities) == ["Armazém 1", "Implantação"]


def test_round_trip_detects_missing_quantity(tmp_path):
    model = build_licensing_model("m")
    space = next(s for s in model.by_type("IfcSpace") if s.Name == "Armazém 2")
    for rel in list(space.IsDefinedBy):
        if rel.RelatingPropertyDefinition.is_a("IfcElementQuantity"):
            model.remove(rel)
    r = generate_ids("SUM(IfcSpace[PredefinedType = GFA] -> Qto_SpaceBaseQuantities.GrossFloorArea)")
    specs = validate(r, model, tmp_path)
    assert failing(specs["IfcSpace[PredefinedType = GFA]"]) == ["Armazém 2"]


def test_round_trip_prohibited(sample_path, tmp_path):
    model = ifcopenshell.open(str(sample_path))
    specs = validate(generate_ids("COUNT(IfcSpace[PredefinedType = INTERNAL]) = 0"), model, tmp_path)
    assert specs["IfcSpace[PredefinedType = INTERNAL]"].status is False  # Átrio exists
    specs = validate(generate_ids("COUNT(IfcSpace[PredefinedType = PARKING]) = 0"), model, tmp_path)
    assert specs["IfcSpace[PredefinedType = PARKING]"].status is True


# ---- command line ----------------------------------------------------------------------------------------------


def test_cli_writes_file(tmp_path, capsys):
    out = tmp_path / "rules.ids"
    code = ids_main([str(EXAMPLES / "queries" / "rules.ifq"), "-o", str(out), "--title", "Rules"])
    assert code == 0 and out.exists()
    assert "Rules" in out.read_text(encoding="utf-8")


def test_cli_stdout_and_data_type(capsys):
    code = ids_main(
        [str(EXAMPLES / "queries" / "rules.ifq"), "--data-type", "PTMU_Licenciamento.SuperficieTotal=IFCAREAMEASURE"]
    )
    assert code == 0
    assert 'dataType="IFCAREAMEASURE"' in capsys.readouterr().out


def test_cli_error(tmp_path, capsys):
    bad = tmp_path / "bad.ifq"
    bad.write_text("SUM(IfcSpace)", encoding="utf-8")
    assert ids_main([str(bad)]) == 2
    assert "SUM expects a value list" in capsys.readouterr().err
