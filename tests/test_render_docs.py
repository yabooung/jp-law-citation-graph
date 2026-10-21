"""tools/render_docs.py: the numbers in the docs match the committed data/."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("render_docs", ROOT / "tools" / "render_docs.py")
render_docs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render_docs)


def test_docs_match_committed_data():
    assert render_docs.main(["--check"]) == 0, "run: python tools/render_docs.py"


def test_marker_is_replaced_and_keeps_its_key():
    out = render_docs.render("x.md", "laws <!--v:laws-->1<!--/v--> on <!--v:snapshot-->old<!--/v-->",
                             {"laws": "8,981", "snapshot": "2026-10-19"})
    assert out == "laws <!--v:laws-->8,981<!--/v--> on <!--v:snapshot-->2026-10-19<!--/v-->"


def test_unknown_key_fails():
    with pytest.raises(KeyError):
        render_docs.render("x.md", "<!--v:nope-->1<!--/v-->", {})


def test_pattern_files_keep_surrounding_text():
    v = {"snapshot": "2026-10-19", "laws": "8,981", "nodes_m": "1.88M", "cites_m": "1.42M", "pairs": "70,772"}
    out = render_docs.render("CITATION.cff", (ROOT / "CITATION.cff").read_text(encoding="utf-8"), v)
    assert "Snapshot: e-Gov 2026-10-19." in out and "8,981 laws at article" in out
    assert "(1.88M nodes, 1.42M resolved citation edges; 70,772 distinct" in out
    with pytest.raises(ValueError):   # a pattern that no longer matches is an error, not a silent skip
        render_docs.render("CITATION.cff", "abstract without the numbers", v)


def test_half_up_rounding():
    assert render_docs._f(0.4975, 3) == "0.498"
    assert render_docs._f(0.108, 2) == "0.11"
