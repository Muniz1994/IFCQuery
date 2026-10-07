"""Every query example in DSL.md must parse and type-check.

This keeps the language spec and the implementation in sync: if DSL.md
gains an example the parser can't handle, this test fails.
"""

import re

import pytest

import ifcquery

from conftest import ROOT

BLOCK = re.compile(r"^```(\w*)\n(.*?)^```", re.S | re.M)


def spec_blocks():
    text = (ROOT / "DSL.md").read_text(encoding="utf-8")
    blocks = []
    for m in BLOCK.finditer(text):
        lang, body = m.group(1), m.group(2)
        if lang in ("", "ifcquery"):
            line = text[: m.start()].count("\n") + 1
            blocks.append(pytest.param(body, id=f"DSL.md:{line}"))
    return blocks


@pytest.mark.parametrize("source", spec_blocks())
def test_spec_example_parses(source):
    program = ifcquery.parse(source, "IFC4")
    assert program.statements


def test_spec_has_examples():
    assert len(spec_blocks()) >= 8
