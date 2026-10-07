import json

from conftest import EXAMPLES

from ifcquery.cli import main


def test_single_query(sample_path, capsys):
    code = main([str(sample_path), 'COUNT(IfcSpace[PredefinedType = "FRACAO"])'])
    out = capsys.readouterr().out
    assert code == 0
    assert "=> 5" in out


def test_rules_file(sample_path, capsys):
    code = main([str(sample_path), "-f", str(EXAMPLES / "queries" / "rules.ifq")])
    out = capsys.readouterr().out
    assert "PASS" in out and "FAIL" in out
    assert code == 1  # the data-quality rule fails on the sample model


def test_json_output(sample_path, capsys):
    code = main([str(sample_path), "--json", 'let t = FIRST(IfcSite -> PTMU_Licenciamento.SuperficieTotal)\nt > 1000'])
    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert data[0]["kind"] == "binding" and data[0]["value"] == 2000.0
    assert data[1]["kind"] == "rule" and data[1]["passed"] is True


def test_query_error_exit_code(sample_path, capsys):
    code = main([str(sample_path), "SUM(IfcSpace)"])
    assert code == 2
    assert "SUM expects a value list" in capsys.readouterr().err


def test_missing_model(tmp_path, capsys):
    assert main([str(tmp_path / "nope.ifc"), "IfcSpace"]) == 2


def test_every_example_query_file_runs(sample_path, capsys):
    for path in sorted((EXAMPLES / "queries").glob("*.ifq")):
        assert main([str(sample_path), "-f", str(path)]) in (0, 1), path
