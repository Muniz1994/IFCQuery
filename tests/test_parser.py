"""Grammar and AST shape, with no IFC schema involved."""

import pytest

from ifcquery import QuerySyntaxError
from ifcquery import ast as A
from ifcquery.parser import parse_syntax


def one(text):
    stmts = parse_syntax(text)
    assert len(stmts) == 1
    return stmts[0].expr


def cond(text):
    """The filter condition of ``IfcSpace[text]``."""
    return one(f"IfcSpace[{text}]").chain[0].condition


# ---- literals ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "src, kind, value",
    [
        ('"IMPLANTACAO"', "string", "IMPLANTACAO"),
        ('"Comércio e Serviços"', "string", "Comércio e Serviços"),
        (r'"say \"hi\""', "string", 'say "hi"'),
        ("100", "number", 100),
        ("0.6", "number", 0.6),
        ("-2.5", "number", -2.5),
        ("1e3", "number", 1000.0),
        ("true", "boolean", True),
        ("FALSE", "boolean", False),
        ("USERDEFINED", "enum", "USERDEFINED"),
        ("GFA", "enum", "GFA"),
    ],
)
def test_filter_literals(src, kind, value):
    c = cond(f"X = {src}")
    assert c.literal.kind == kind
    assert c.literal.value == value


def test_lowercase_bare_word_is_not_a_literal():
    with pytest.raises(QuerySyntaxError, match="double quotes"):
        parse_syntax("IfcSpace[Name = gfa]")


def test_mixed_case_enum_rejected():
    with pytest.raises(QuerySyntaxError):
        parse_syntax("IfcSpace[PredefinedType = GFAa]")


# ---- identifiers and keywords -------------------------------------------------------


def test_unicode_identifiers():
    c = cond('PTMU.Afetação = "x"')
    assert c.path == A.Path("Afetação", "PTMU")


def test_quoted_identifiers():
    q = one('IfcSpace -> "Identity Data"."Assembly Code"')
    assert q.projection == (A.Path("Assembly Code", "Identity Data"),)


@pytest.mark.parametrize("text", ["a = 1 AND b = 2", "a = 1 and b = 2", "a = 1 And b = 2"])
def test_keywords_case_insensitive(text):
    assert isinstance(cond(text), A.And)


@pytest.mark.parametrize("func", ["COUNT", "count", "Count"])
def test_function_names_case_insensitive(func):
    assert one(f"{func}(IfcSpace)").func == "COUNT"


def test_keyword_prefix_is_a_name():
    # `android` must not lex as `and` + `roid`; `country` not as `count` + `ry`.
    c = cond('android = "x" and country = 1')
    assert [i.path.name for i in c.items] == ["android", "country"]


def test_ifc_class_case_insensitive_and_prefix():
    assert one("IFCSPACE").chain[0].ifc_class == "IFCSPACE"
    assert one("ifcWall").chain[0].ifc_class == "ifcWall"


# ---- conditions ---------------------------------------------------------------------


def test_precedence_not_and_or():
    c = cond("not a = 1 and b = 2 or c = 3")
    assert isinstance(c, A.Or)
    left, right = c.items
    assert isinstance(left, A.And)
    assert isinstance(left.items[0], A.Not)
    assert isinstance(right, A.Comparison)


def test_parentheses_group():
    c = cond("a = 1 and (b = 2 or c = 3)")
    assert isinstance(c, A.And)
    assert isinstance(c.items[1], A.Or)


@pytest.mark.parametrize("op", ["=", "!=", "<", "<=", ">", ">=", "~="])
def test_comparison_operators(op):
    assert cond(f"Pset.X {op} 1").op == op


def test_in_and_exists():
    c = cond('P.A in ("Comércio", "Serviços") and not exists(P.A)')
    assert isinstance(c.items[0], A.InList)
    assert [lit.value for lit in c.items[0].literals] == ["Comércio", "Serviços"]
    assert c.items[1] == A.Not(A.Exists(A.Path("A", "P")))


def test_greater_than_inside_filter():
    c = cond("Qto.Area > 100")
    assert c.op == ">"


# ---- containment and projection ---------------------------------------------------------


def test_containment_chain():
    q = one('IfcBuilding[Name = "Bloco A"] > IfcBuildingStorey > IfcSpace[ObjectType = "FRACAO"]')
    assert [e.ifc_class for e in q.chain] == ["IfcBuilding", "IfcBuildingStorey", "IfcSpace"]


def test_gt_vs_containment_at_top_level():
    assert isinstance(one("COUNT(IfcSpace) > 3"), A.Compare)
    assert len(one("IfcSite > IfcSpace").chain) == 2
    assert len(one("IfcSite>IfcSpace").chain) == 2


def test_single_projection():
    q = one("IfcSpace -> Name")
    assert q.projection == (A.Path("Name"),) and not q.records


def test_multi_projection():
    q = one("IfcSpace -> (Name, P.A, Qto.NetFloorArea)")
    assert q.records
    assert [str(p) for p in q.projection] == ["Name", "P.A", "Qto.NetFloorArea"]


# ---- expressions and statements ----------------------------------------------------------


def test_arithmetic_precedence():
    e = one("1 + 2 * 3 - 4 / 2")
    # ((1 + (2*3)) - (4/2))
    assert e.op == "-"
    assert e.left.op == "+" and e.left.right.op == "*"
    assert e.right.op == "/"


def test_unary_minus():
    e = one("-a + 1")
    assert isinstance(e.left, A.Neg)


def test_let_and_rule():
    stmts = parse_syntax("let a = 1\nlet b = 2\na / b <= 0.6")
    assert [type(s).__name__ for s in stmts] == ["Let", "Let", "ExprStatement"]
    assert stmts[0].name == "a"
    assert isinstance(stmts[2].expr, A.Compare)
    assert stmts[2].text == "a / b <= 0.6"
    assert stmts[2].line == 3


def test_let_keyword_case_insensitive():
    assert parse_syntax("LET x = 1")[0].name == "x"


# ---- newlines and comments ------------------------------------------------------------------


def test_comments_and_blank_lines():
    src = "// heading\n\nlet a = 1 // trailing\n   \n// between\nlet b = 2\n\n// end\n"
    stmts = parse_syntax(src)
    assert [s.name for s in stmts] == ["a", "b"]


def test_hash_is_not_a_comment():
    with pytest.raises(QuerySyntaxError):
        parse_syntax("IfcSpace # no")


def test_newline_inside_brackets_and_parens():
    src = 'SUM(IfcSpace[a = 1\n  and b = 2]\n    -> Qto.GrossFloorArea)'
    assert isinstance(one(src), A.Call)


def test_newline_before_arrow_continues():
    src = 'IfcBuildingStorey[Name = "Piso 0"] > IfcSpace\n  -> (Name, P.A)'
    assert one(src).records


def test_newline_before_operator_continues():
    e = one("1\n  + 2\n  <= 3")
    assert isinstance(e, A.Compare)


def test_comment_line_before_continuation():
    e = one("IfcSpace\n  // pick names\n  -> Name")
    assert e.projection == (A.Path("Name"),)


def test_arrow_inside_comment_does_not_continue():
    stmts = parse_syntax("IfcSpace\n// -> Name\nIfcSite")
    assert len(stmts) == 2


def test_minus_on_next_line_starts_new_statement():
    stmts = parse_syntax("1\n-2")
    assert len(stmts) == 2


def test_empty_program():
    assert parse_syntax("") == ()
    assert parse_syntax("// only a comment\n\n") == ()


# ---- errors --------------------------------------------------------------------------------------


def test_syntax_error_position():
    with pytest.raises(QuerySyntaxError) as info:
        parse_syntax('let a = 1\nIfcSpace[Name = "x" and]')
    assert info.value.line == 2
    assert info.value.column == 24


def test_unclosed_paren():
    with pytest.raises(QuerySyntaxError, match="end of input"):
        parse_syntax("COUNT(IfcSpace")


def test_unknown_function_is_error():
    with pytest.raises(QuerySyntaxError):
        parse_syntax("MEDIAN(IfcSpace -> Name)")
