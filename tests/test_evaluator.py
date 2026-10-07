"""Evaluation against the sample model (see examples/build_sample_models.py for its content)."""

import pytest

import ifcopenshell.api.pset

import ifcquery
from ifcquery import ElementList, QueryEvaluationError, RecordList, ValueList
from ifcquery.evaluator import compare, fold

from build_sample_models import build_licensing_model


def names(elements):
    return sorted(e.Name for e in elements)


# ---- selection ---------------------------------------------------------------------------


def test_selector_returns_elements(q):
    spaces = q("IfcSpace")
    assert isinstance(spaces, ElementList)
    assert len(spaces) == 9


def test_selector_includes_subtypes(q):
    assert names(q("IfcWall")) == ["Parede 1", "Parede 2"]
    assert names(q("IfcWallStandardCase")) == ["Parede 2"]
    assert len(q("IfcBuildingElement")) == 2


def test_selector_case_insensitive(q):
    assert len(q("IFCSPACE")) == 9


# ---- filters --------------------------------------------------------------------------------


def test_filter_attribute(q):
    assert names(q('IfcSpace[Name = "Fração A"]')) == ["Fração A"]


def test_string_equality_is_case_sensitive(q):
    assert q('IfcSpace[PTMU_Licenciamento.Afetacao = "comércio"]') == []


def test_not_equal(q):
    # Spaces without Afetacao are excluded: comparisons with a missing value are false.
    assert names(q('IfcSpace[PTMU_Licenciamento.Afetacao != "Comércio"]')) == ["Armazém 1", "Armazém 2", "Fração B"]


def test_numeric_comparisons(q):
    # GFA values: 500, 120, 80, 300, 150, 90, 200, 60 (Átrio has none)
    gfa = "Qto_SpaceBaseQuantities.GrossFloorArea"
    assert len(q(f"IfcSpace[{gfa} >= 120]")) == 5
    assert len(q(f"IfcSpace[{gfa} > 120]")) == 4
    assert len(q(f"IfcSpace[{gfa} < 90]")) == 2  # 80, 60
    assert len(q(f"IfcSpace[{gfa} <= 90]")) == 3  # 80, 60, 90
    assert len(q(f"IfcSpace[{gfa} = 500]")) == 1
    assert len(q(f"IfcSpace[{gfa} != 500]")) == 7  # Átrio has no quantity


def test_approx_equal(q):
    assert names(q('IfcSpace[PTMU_Licenciamento.Afetacao ~= "logistica"]')) == ["Armazém 1", "Armazém 2"]
    assert names(q('IfcSpace[PTMU_Licenciamento.Afetacao ~= "LOGÍSTICA"]')) == ["Armazém 1", "Armazém 2"]


def test_in_list(q):
    result = q('IfcSpace[PTMU_Licenciamento.Afetacao in ("Comércio", "Serviços")]')
    assert names(result) == ["Fração A", "Fração B", "Fração C", "Fração E"]


def test_exists(q):
    assert names(q("IfcSpace[not exists(PTMU_Licenciamento.Afetacao)]")) == ["Fração D", "Implantação", "Átrio"]
    assert len(q("IfcSpace[exists(Qto_SpaceBaseQuantities.GrossFloorArea)]")) == 8
    assert len(q("IfcSpace[exists(ObjectType)]")) == 5


def test_boolean_logic(q):
    r = q('IfcSpace[PredefinedType = GFA or (PredefinedType = "FRACAO" and not exists(PTMU_Licenciamento.Afetacao))]')
    assert names(r) == ["Armazém 1", "Armazém 2", "Fração D"]


def test_property_inherited_from_type(q):
    # Fração E has no pset of its own; its IfcSpaceType carries Afetacao.
    assert "Fração E" in names(q('IfcSpace[PTMU_Licenciamento.Afetacao = "Comércio"]'))


def test_occurrence_property_overrides_type():
    m = build_licensing_model("m")
    s08 = next(s for s in m.by_type("IfcSpace") if s.Name == "Fração E")
    pset = ifcopenshell.api.pset.add_pset(m, product=s08, name="PTMU_Licenciamento")
    ifcopenshell.api.pset.edit_pset(m, pset=pset, properties={"Afetacao": "Serviços"})
    r = ifcquery.run('IfcSpace[Name = "Fração E"] -> PTMU_Licenciamento.Afetacao', m)
    assert r[0].value == ["Serviços"]


# ---- PredefinedType -------------------------------------------------------------------------


def test_predefined_type_enum(q):
    assert names(q("IfcSpace[PredefinedType = GFA]")) == ["Armazém 1", "Armazém 2"]
    assert len(q("IfcSpace[PredefinedType = USERDEFINED]")) == 6  # 5 occurrences + Fração E via its type


def test_predefined_type_string_means_user_defined(q):
    a = q('IfcSpace[PredefinedType = USERDEFINED and ObjectType = "IMPLANTACAO"]')
    b = q('IfcSpace[PredefinedType = "IMPLANTACAO"]')
    assert names(a) == names(b) == ["Implantação"]


def test_predefined_type_string_does_not_match_enum(q):
    assert q('IfcSpace[PredefinedType = "GFA"]') == []


def test_predefined_type_from_type_object(q):
    # Fração E: occurrence NOTDEFINED, type USERDEFINED with ElementType FRACAO.
    assert "Fração E" in names(q('IfcSpace[PredefinedType = "FRACAO"]'))
    assert "Fração E" not in names(q('IfcSpace[ObjectType = "FRACAO"]'))


def test_predefined_type_not_equal_string(q):
    r = q('IfcSpace[PredefinedType != "FRACAO"]')
    assert names(r) == ["Armazém 1", "Armazém 2", "Implantação", "Átrio"]


def test_predefined_type_projection(q):
    r = q('IfcSpace[Description in ("S01", "S04", "S08", "S09")] -> PredefinedType')
    assert sorted(r) == ["FRACAO", "GFA", "IMPLANTACAO", "INTERNAL"]


# ---- containment ----------------------------------------------------------------------------


def test_containment_aggregation(q):
    r = q('IfcBuildingStorey[Name = "Piso 0"] > IfcSpace[PredefinedType = "FRACAO"]')
    assert names(r) == ["Fração A", "Fração B", "Fração E"]  # both buildings have a "Piso 0"


def test_containment_any_depth(q):
    assert len(q('IfcBuilding[Name = "Bloco B"] > IfcSpace')) == 1
    assert len(q("IfcSite > IfcSpace")) == 9


def test_containment_chain(q):
    r = q('IfcBuilding[Name = "Bloco A"] > IfcBuildingStorey > IfcSpace[ObjectType = "FRACAO"]')
    assert names(r) == ["Fração A", "Fração B", "Fração C", "Fração D"]


def test_containment_spatial_containment(q):
    assert names(q('IfcBuildingStorey[Name = "Piso 1"] > IfcWall')) == ["Parede 2"]
    assert names(q('IfcBuilding[Name = "Bloco A"] > IfcWall')) == ["Parede 1", "Parede 2"]


def test_containment_excludes_roots(q):
    assert q("IfcSpace > IfcSpace") == []


# ---- projection -----------------------------------------------------------------------------


def test_projection_one_entry_per_element(q):
    r = q("IfcSpace -> PTMU_Licenciamento.Afetacao")
    assert isinstance(r, ValueList)
    assert len(r) == 9
    assert r.count(None) == 3


def test_projection_records(q):
    r = q('IfcSpace[Name = "Fração A"] -> (Name, PTMU_Licenciamento.Afetacao, Qto_SpaceBaseQuantities.NetFloorArea)')
    assert isinstance(r, RecordList)
    assert r == [
        {"Name": "Fração A", "PTMU_Licenciamento.Afetacao": "Comércio", "Qto_SpaceBaseQuantities.NetFloorArea": 100.0}
    ]


def test_site_area(q):
    assert q("IfcSite -> PTMU_Licenciamento.SuperficieTotal") == [2000.0]


# ---- units ---------------------------------------------------------------------------------------


def test_quantities_converted_to_si(q, model_mm):
    gfa = "SUM(IfcSpace -> Qto_SpaceBaseQuantities.GrossFloorArea)"
    assert q(gfa) == pytest.approx(1500.0)
    assert q(gfa, model_mm) == pytest.approx(1500.0)
    lengths = "IfcWall -> Qto_WallBaseQuantities.Length"
    assert sorted(q(lengths, model_mm)) == pytest.approx([3.0, 5.0])


def test_unit_conversion_in_filters(q, model_mm):
    assert len(q("IfcSpace[Qto_SpaceBaseQuantities.GrossFloorArea >= 300]", model_mm)) == 2


# ---- aggregates -------------------------------------------------------------------------------


def test_count(q):
    assert q("COUNT(IfcSpace)") == 9
    assert q("COUNT(IfcSpace -> PTMU_Licenciamento.Afetacao)") == 6  # non-null values only
    assert q("COUNT(IfcSpace -> (Name, PTMU_Licenciamento.Afetacao))") == 9


def test_sum_avg_min_max(q):
    p = "IfcSpace[PredefinedType = GFA] -> Qto_SpaceBaseQuantities.GrossFloorArea"
    assert q(f"SUM({p})") == 500
    assert q(f"AVG({p})") == 250
    assert q(f"MIN({p})") == 200
    assert q(f"MAX({p})") == 300


def test_aggregates_ignore_nulls(q):
    assert q("AVG(IfcSpace -> Qto_SpaceBaseQuantities.GrossFloorArea)") == pytest.approx(1500 / 8)


def test_empty_aggregates(q):
    empty = 'IfcSpace[Name = "nothing"] -> Qto_SpaceBaseQuantities.GrossFloorArea'
    assert q(f"SUM({empty})") == 0
    for f in ("AVG", "MIN", "MAX", "FIRST"):
        assert q(f"{f}({empty})") is None
    assert q('COUNT(IfcSpace[Name = "nothing"])') == 0


def test_first(q):
    assert q("FIRST(IfcSite -> PTMU_Licenciamento.SuperficieTotal)") == 2000.0
    assert q("FIRST(IfcSite)").is_a("IfcSite")
    # First non-null entry.
    assert q('FIRST(IfcSpace[Name in ("Átrio", "Fração A")] -> PTMU_Licenciamento.Afetacao)') == "Comércio"


def test_sum_of_text_is_evaluation_error(q):
    with pytest.raises(QueryEvaluationError, match="SUM needs numeric values"):
        q("SUM(IfcSpace -> Name)")


# ---- expressions, bindings, rules -----------------------------------------------------------


def test_arithmetic(q):
    assert q("1 + 2 * 3") == 7
    assert q("(1 + 2) * 3") == 9
    assert q("-(4 - 6) / 4") == 0.5


def test_division_by_zero_is_null(q):
    assert q("1 / 0") is None


def test_rule_result(model):
    results = ifcquery.run(
        "let implantacao = SUM(IfcSpace[PredefinedType = \"IMPLANTACAO\"] -> Qto_SpaceBaseQuantities.GrossFloorArea)\n"
        "let terreno     = FIRST(IfcSite -> PTMU_Licenciamento.SuperficieTotal)\n"
        "implantacao / terreno <= 0.6",
        model,
    )
    assert [r.kind for r in results] == ["binding", "binding", "rule"]
    assert results[0].name == "implantacao" and results[0].value == 500
    assert results[1].value == 2000
    assert results[2].passed is True and results[2].value is True
    assert results[2].line == 3


def test_failing_rule(model):
    r = ifcquery.run(
        'COUNT(IfcSpace[PredefinedType = "FRACAO" and not exists(PTMU_Licenciamento.Afetacao)]) = 0', model
    )[0]
    assert r.kind == "rule" and r.passed is False


def test_rule_with_null_is_inconclusive(model):
    r = ifcquery.run("FIRST(IfcSite -> Missing.Prop) > 10", model)[0]
    assert r.kind == "rule" and r.passed is None


def test_rule_string_comparison(model):
    assert ifcquery.run('FIRST(IfcSite -> Name) = "Terreno"', model)[0].passed is True
    assert ifcquery.run('FIRST(IfcSite -> Name) ~= "terreno"', model)[0].passed is True


def test_ordering_on_text_is_evaluation_error(model):
    with pytest.raises(QueryEvaluationError):
        ifcquery.run("FIRST(IfcSite -> Name) > 3", model)


def test_bound_element_list(model):
    r = ifcquery.run("let fr = IfcSpace[PredefinedType = \"FRACAO\"]\nCOUNT(fr)", model)
    assert r[1].value == 5


def test_result_to_dict(model):
    r = ifcquery.run('IfcSite\nIfcSpace[Name = "Fração A"] -> (Name)', model)
    d = r[0].to_dict()
    assert d["kind"] == "elements"
    assert d["value"][0]["type"] == "IfcSite" and d["value"][0]["Name"] == "Terreno"
    assert r[1].to_dict()["value"] == [{"Name": "Fração A"}]


# ---- other property kinds ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def typed_props_model():
    m = build_licensing_model("m")
    site = m.by_type("IfcSite")[0]
    pset = ifcopenshell.api.pset.add_pset(m, product=site, name="Pset_Test")
    ifcopenshell.api.pset.edit_pset(m, pset=pset, properties={"Flag": True, "Count": 3, "Label": "abc"})
    return m


def test_boolean_property(typed_props_model):
    assert len(ifcquery.run("IfcSite[Pset_Test.Flag = true]", typed_props_model)[0].value) == 1
    assert ifcquery.run("IfcSite[Pset_Test.Flag = false]", typed_props_model)[0].value == []
    # A boolean is not the number 1.
    assert ifcquery.run("IfcSite[Pset_Test.Flag = 1]", typed_props_model)[0].value == []


def test_enum_literal_on_pset_compares_as_text(typed_props_model):
    m = typed_props_model
    site = m.by_type("IfcSite")[0]
    pset = ifcopenshell.api.pset.add_pset(m, product=site, name="Pset_Enum")
    ifcopenshell.api.pset.edit_pset(m, pset=pset, properties={"Status": "NEW"})
    assert len(ifcquery.run("IfcSite[Pset_Enum.Status = NEW]", m)[0].value) == 1


# ---- helpers ---------------------------------------------------------------------------------------


def test_fold():
    assert fold("Logística") == fold("LOGISTICA") == "logistica"
    assert fold("Comércio e Serviços") == "comercio e servicos"


@pytest.mark.parametrize(
    "value, op, other, expected",
    [
        (None, "=", 1, False),
        (None, "!=", 1, False),
        (1, "=", 1.0, True),
        ("1", "=", 1, False),
        (True, "=", 1, False),
        (5, ">", 3, True),
        ("5", ">", 3, False),
        (["a", "b"], "=", "b", True),
        (["a", "b"], "!=", "b", False),
    ],
)
def test_compare(value, op, other, expected):
    assert compare(value, op, other) is expected


def test_class_missing_from_model_schema(model):
    program = ifcquery.parse("IfcAlignment", "IFC4X3_ADD2")
    with pytest.raises(QueryEvaluationError, match="does not exist"):
        ifcquery.evaluate(program, model)
