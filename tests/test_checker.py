"""Parse-time checks against the IFC schema and static typing."""

import pytest

import ifcquery
from ifcquery import QuerySchemaError, QueryTypeError


def ok(text, schema="IFC4"):
    return ifcquery.parse(text, schema)


# ---- schema ---------------------------------------------------------------------------


def test_unknown_class_with_suggestion():
    with pytest.raises(QuerySchemaError, match="Did you mean IfcSpace") as info:
        ok("IfcSpcae")
    assert (info.value.line, info.value.column) == (1, 1)


def test_class_names_case_insensitive():
    ok("IFCSPACE")
    ok("ifcbuildingstorey > ifcspace")


def test_class_depends_on_schema():
    ok("IfcWallStandardCase", "IFC4")
    with pytest.raises(QuerySchemaError):
        ok("IfcAlignment", "IFC2X3")
    ok("IfcAlignment", "IFC4X3_ADD2")


def test_unknown_schema():
    with pytest.raises(QuerySchemaError, match="unknown IFC schema"):
        ok("IfcSpace", "IFC9")


def test_unknown_attribute():
    with pytest.raises(QuerySchemaError, match="no attribute 'Nmae'.*Did you mean Name"):
        ok('IfcSpace[Nmae = "x"]')


def test_unknown_attribute_in_projection():
    with pytest.raises(QuerySchemaError, match="IfcSpace has no attribute 'Area'"):
        ok("IfcSite > IfcSpace -> Area")


def test_pset_paths_are_not_validated():
    ok('IfcSpace[Anything.Goes = "x"] -> Whatever.Here')


def test_inherited_attribute():
    ok('IfcWallStandardCase[Name = "x" and GlobalId = "y"]')


def test_enum_typo_is_error():
    with pytest.raises(QuerySchemaError, match="GFAA is not a valid IfcSpace.PredefinedType.*Did you mean GFA"):
        ok("IfcSpace[PredefinedType = GFAA]")


def test_enum_checked_inside_in_list():
    with pytest.raises(QuerySchemaError):
        ok("IfcSpace[PredefinedType in (GFA, NOPE)]")


def test_enum_on_non_enum_attribute():
    with pytest.raises(QuerySchemaError, match="not an enumeration"):
        ok("IfcSpace[ObjectType = FRACAO]")


def test_enum_on_pset_property_allowed():
    ok("IfcSpace[Pset_X.Status = NEW]")


def test_enum_in_ifc2x3():
    # IfcSpace has no PredefinedType in IFC2X3.
    with pytest.raises(QuerySchemaError):
        ok("IfcSpace[PredefinedType = GFA]", "IFC2X3")
    ok("IfcWall[Name = \"x\"]", "IFC2X3")


def test_ordering_needs_number_literal():
    with pytest.raises(QueryTypeError, match="compares numbers"):
        ok('IfcSpace[Name > "a"]')


# ---- types -----------------------------------------------------------------------------


@pytest.mark.parametrize("func", ["SUM", "AVG", "MIN", "MAX"])
def test_numeric_aggregate_rejects_element_list(func):
    with pytest.raises(QueryTypeError, match=f"{func} expects a value list, got an element list"):
        ok(f"{func}(IfcSpace)")


def test_numeric_aggregate_rejects_records():
    with pytest.raises(QueryTypeError):
        ok("SUM(IfcSpace -> (Name, Q.A))")


def test_count_and_first_accept_lists():
    ok("COUNT(IfcSpace)")
    ok("COUNT(IfcSpace -> Name)")
    ok("FIRST(IfcSpace -> Name)")
    ok("FIRST(IfcSite)")


def test_aggregate_of_scalar_rejected():
    with pytest.raises(QueryTypeError, match="COUNT expects a list"):
        ok("COUNT(1)")


def test_arithmetic_on_list_rejected():
    with pytest.raises(QueryTypeError, match="needs scalar operands"):
        ok("(IfcSpace -> Q.A) * 2")


def test_compare_list_rejected():
    with pytest.raises(QueryTypeError, match="cannot compare"):
        ok("IfcSpace = 0")


def test_undefined_variable():
    with pytest.raises(QueryTypeError, match="undefined variable 'terreno'") as info:
        ok("let a = 1\na / terreno")
    assert info.value.line == 2


def test_rebinding_rejected():
    with pytest.raises(QueryTypeError, match="already defined"):
        ok("let a = 1\nlet a = 2")


def test_variable_types_propagate():
    ok("let spaces = IfcSpace\nCOUNT(spaces)")
    with pytest.raises(QueryTypeError):
        ok("let spaces = IfcSpace\nSUM(spaces)")


def test_program_records_types():
    p = ok("let a = 1\nIfcSpace\nIfcSpace -> Name\nIfcSpace -> (Name, Q.A)\na > 0")
    assert p.types == ("scalar", "element list", "value list", "record list", "boolean")
    assert p.schema == "IFC4"


def test_errors_share_base_class():
    with pytest.raises(ifcquery.IfcQueryError):
        ok("SUM(IfcSpace)")
