"""Text -> AST.

``parse_syntax`` only checks the grammar. ``ifcquery.parse`` (in
``__init__``) also runs the schema/type checker, and is the function most
callers want.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources

from lark import Lark, Token, Transformer, v_args
from lark.exceptions import UnexpectedCharacters, UnexpectedEOF, UnexpectedInput, UnexpectedToken, VisitError

from . import ast
from .errors import IfcQueryError, QuerySyntaxError


class _NewlineFilter:
    """Lark postlexer: newlines end statements, except inside () or [].

    It also drops newlines at the start of the text and collapses repeated
    ones, so the grammar only ever sees a single _NL between two statements.
    """

    always_accept = ("_NL",)

    def process(self, stream):
        depth = 0
        emitted = False
        last_was_nl = False
        for tok in stream:
            if tok.type == "_NL":
                if depth > 0 or not emitted or last_was_nl:
                    continue
                last_was_nl = True
                yield tok
                continue
            if tok.type in ("LPAR", "LSQB"):
                depth += 1
            elif tok.type in ("RPAR", "RSQB"):
                depth = max(0, depth - 1)
            emitted = True
            last_was_nl = False
            yield tok


@lru_cache(maxsize=1)
def _lark() -> Lark:
    grammar = resources.files("ifcquery").joinpath("grammar.lark").read_text(encoding="utf-8")
    return Lark(
        grammar,
        parser="lalr",
        lexer="contextual",
        postlex=_NewlineFilter(),
        propagate_positions=True,
        maybe_placeholders=False,
    )


def _unescape(token: str) -> str:
    """Strip the quotes of a STRING token and resolve \\" and \\\\ escapes."""
    body = token[1:-1]
    out = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            out.append({"n": "\n", "t": "\t"}.get(nxt, nxt))
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _pos(meta_or_token):
    return dict(line=getattr(meta_or_token, "line", 0) or 0, column=getattr(meta_or_token, "column", 0) or 0)


def _number(text: str) -> int | float:
    try:
        return int(text)
    except ValueError:
        return float(text)


@v_args(meta=True)
class _ToAst(Transformer):
    def __init__(self, source: str):
        super().__init__()
        self.source = source

    def _text(self, meta) -> str:
        if getattr(meta, "empty", True):
            return ""
        return self.source[meta.start_pos : meta.end_pos]

    # statements
    def start(self, meta, children):
        return tuple(children)

    def let_stmt(self, meta, children):
        _let, name, _eq, expr = children
        return ast.Let(str(name), expr, text=self._text(meta), **_pos(meta))

    def expr_stmt(self, meta, children):
        return ast.ExprStatement(children[0], text=self._text(meta), **_pos(meta))

    # expressions
    def compare(self, meta, children):
        left, op, right = children
        return ast.Compare(op, left, right, **_pos(meta))

    def compop(self, meta, children):
        return str(children[0])

    def binop(self, meta, children):
        left, op, right = children
        return ast.BinOp(str(op), left, right, **_pos(meta))

    def neg(self, meta, children):
        operand = children[-1]
        if isinstance(operand, ast.Literal) and operand.kind == "number":
            return ast.Literal("number", -operand.value, **_pos(meta))
        return ast.Neg(operand, **_pos(meta))

    def number(self, meta, children):
        return ast.Literal("number", _number(str(children[0])), **_pos(meta))

    def neg_number(self, meta, children):
        return ast.Literal("number", -_number(str(children[-1])), **_pos(meta))

    def string(self, meta, children):
        return ast.Literal("string", _unescape(str(children[0])), **_pos(meta))

    def boolean(self, meta, children):
        return ast.Literal("boolean", str(children[0]).lower() == "true", **_pos(meta))

    def enum(self, meta, children):
        return ast.Literal("enum", str(children[0]), **_pos(meta))

    def var(self, meta, children):
        return ast.Var(str(children[0]), **_pos(meta))

    def call(self, meta, children):
        func, arg = children
        return ast.Call(str(func).upper(), arg, **_pos(meta))

    # queries
    def query(self, meta, children):
        chain = children[0]
        projection, records = None, False
        if len(children) > 1:
            kind, paths = children[-1]
            projection, records = paths, kind == "multi"
        return ast.Query(chain, projection, records, **_pos(meta))

    def selection(self, meta, children):
        return tuple(c for c in children if isinstance(c, ast.Entity))

    def entity(self, meta, children):
        cls = str(children[0])
        condition = children[1] if len(children) > 1 else None
        return ast.Entity(cls, condition, **_pos(meta))

    def single_projection(self, meta, children):
        return ("single", (children[0],))

    def multi_projection(self, meta, children):
        return ("multi", tuple(children))

    # conditions
    def or_cond(self, meta, children):
        return ast.Or(tuple(children), **_pos(meta))

    def and_cond(self, meta, children):
        return ast.And(tuple(children), **_pos(meta))

    def negation(self, meta, children):
        return ast.Not(children[0], **_pos(meta))

    def comparison(self, meta, children):
        path, op, literal = children
        return ast.Comparison(op, path, literal, **_pos(meta))

    def in_list(self, meta, children):
        return ast.InList(children[0], tuple(children[1:]), **_pos(meta))

    def exists(self, meta, children):
        return ast.Exists(children[0], **_pos(meta))

    def path(self, meta, children):
        names = [_unescape(str(t)) if t.type == "STRING" else str(t) for t in children]
        if len(names) == 1:
            return ast.Path(names[0], None, **_pos(meta))
        return ast.Path(names[1], names[0], **_pos(meta))


_FRIENDLY = {
    "NAME": "a name",
    "STRING": "a quoted string",
    "NUMBER": "a number",
    "ENUM": "an enumeration value (bare UPPERCASE word)",
    "TRUE": "true",
    "FALSE": "false",
    "IFCCLASS": "an IFC class name",
    "FUNC": "a function (COUNT, SUM, AVG, MIN, MAX, FIRST)",
    "LET": "'let'",
    "ARROW": "'->'",
    "CONTAINS": "'>' followed by an IFC class",
    "LPAR": "'('",
    "RPAR": "')'",
    "LSQB": "'['",
    "RSQB": "']'",
    "COMMA": "','",
    "DOT": "'.'",
    "EQ": "'='",
    "NE": "'!='",
    "LT": "'<'",
    "LE": "'<='",
    "GT": "'>'",
    "GE": "'>='",
    "APPROX": "'~='",
    "PLUS": "'+'",
    "MINUS": "'-'",
    "STAR": "'*'",
    "SLASH": "'/'",
    "_AND": "'and'",
    "_OR": "'or'",
    "_NOT": "'not'",
    "_IN": "'in'",
    "_EXISTS": "'exists'",
    "_NL": "end of line",
    "$END": "end of input",
}


def _expected(names) -> str:
    items = sorted({_FRIENDLY.get(n, n) for n in names if not n.startswith("__")})
    return ", ".join(items)


def _syntax_error(e: UnexpectedInput, source: str) -> QuerySyntaxError:
    if isinstance(e, UnexpectedCharacters):
        snippet = source[e.pos_in_stream : e.pos_in_stream + 20].split("\n")[0]
        msg = f"unexpected text {snippet!r}"
        if e.allowed:
            msg += f"; expected {_expected(e.allowed)}"
        if "ENUM" in (e.allowed or ()) and snippet[:1].isalpha():
            msg += ". Strings must be in double quotes; enumeration values are UPPERCASE"
        return QuerySyntaxError(msg, e.line, e.column)
    if isinstance(e, UnexpectedEOF):
        return QuerySyntaxError(f"unexpected end of input; expected {_expected(e.expected)}", e.line, e.column)
    if isinstance(e, UnexpectedToken):
        tok = e.token
        shown = "end of input" if tok.type == "$END" else "end of line" if tok.type == "_NL" else repr(str(tok))
        line, column = (e.line, e.column) if e.line not in (None, -1) else (None, None)
        msg = f"unexpected {shown}; expected {_expected(e.expected)}"
        if "ENUM" in e.expected and tok.type == "NAME":
            msg += ". Strings must be in double quotes; enumeration values are UPPERCASE"
        return QuerySyntaxError(msg, line, column)
    return QuerySyntaxError(str(e), getattr(e, "line", None), getattr(e, "column", None))


def parse_syntax(text: str) -> tuple[ast.Statement, ...]:
    """Parse ``text`` into statements without consulting any IFC schema."""
    try:
        tree = _lark().parse(text)
    except UnexpectedInput as e:
        raise _syntax_error(e, text) from None
    try:
        return _ToAst(text).transform(tree)
    except VisitError as e:
        if isinstance(e.orig_exc, IfcQueryError):
            raise e.orig_exc from None
        raise
