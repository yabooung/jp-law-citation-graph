import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("regression_gate", ROOT / "tools" / "regression_gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

BASE_RESULTS = json.loads((ROOT / "eval/v2/nta_retrieval_results.json").read_text(encoding="utf-8"))
BASE_STATS = json.loads((ROOT / "data/release_stats.json").read_text(encoding="utf-8"))


def _run(tmp_path, results, stats):
    paths = {}
    for name, obj in [("nr", results), ("br", BASE_RESULTS), ("ns", stats), ("bs", BASE_STATS)]:
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps(obj), encoding="utf-8")
        paths[name] = str(p)
    return gate.main(["--new-results", paths["nr"], "--base-results", paths["br"],
                      "--new-stats", paths["ns"], "--base-stats", paths["bs"]])


def test_identical_snapshot_passes(tmp_path):
    assert _run(tmp_path, BASE_RESULTS, BASE_STATS) == 0


def test_normal_monthly_drift_passes(tmp_path):
    stats = json.loads(json.dumps(BASE_STATS))
    stats["laws"] -= 40                                   # ~0.4% fewer laws (repeals)
    stats["edges_by_rel"]["CITES"] = int(stats["edges_by_rel"]["CITES"] * 0.995)
    results = json.loads(json.dumps(BASE_RESULTS))
    results["methods"]["bm25+graph"]["recall@10"] -= 0.008
    assert _run(tmp_path, results, stats) == 0


def test_citation_loss_fails(tmp_path):
    stats = json.loads(json.dumps(BASE_STATS))
    stats["edges_by_rel"]["CITES"] = int(stats["edges_by_rel"]["CITES"] * 0.90)   # parser drops 10%
    assert _run(tmp_path, BASE_RESULTS, stats) == 1


def test_retrieval_regression_fails(tmp_path, capsys):
    results = json.loads(json.dumps(BASE_RESULTS))
    results["methods"]["bm25+graph"]["recall@10"] -= 0.05
    assert _run(tmp_path, results, BASE_STATS) == 1
    assert "recall@10 bm25+graph" in capsys.readouterr().out


def test_missing_field_fails_loudly(tmp_path):
    stats = json.loads(json.dumps(BASE_STATS))
    del stats["edges_by_rel"]["DELEGATES_TO"]
    assert _run(tmp_path, BASE_RESULTS, stats) == 1


def test_increases_never_fail(tmp_path):
    stats = json.loads(json.dumps(BASE_STATS))
    stats["edges_by_rel"]["CITES"] *= 2
    results = json.loads(json.dumps(BASE_RESULTS))
    results["methods"]["bm25+graph"]["recall@10"] += 0.1
    assert _run(tmp_path, results, stats) == 0
