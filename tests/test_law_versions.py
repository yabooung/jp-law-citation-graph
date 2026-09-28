"""Tests for version discovery (current vs pending) in jlawcite.parser."""
from jlawcite.parser import find_law_xmls, list_law_versions, split_current_pending

CSV_HEADER = ("法令種別,法令番号,法令名,法令名読み,旧法令名,公布日,改正法令名,改正法令番号,"
              "改正法令公布日,施行日,施行日備考,法令ID,本文URL,未施行\n")


def _make_dump(tmp_path, dirs):
    for name in dirs:
        d = tmp_path / name
        d.mkdir()
        (d / f"{name}.xml").write_text("<Law/>", encoding="utf-8")
    rows = []
    for name in dirs:
        law_id, _, mst = name.partition("_")
        rows.append(f"法律,x,民法,,,,改正法{mst},令和八年法律第{mst[-2:]}号,,"
                    f"令和九年一月一日,政令で定める日,{law_id},"
                    f"https://laws.e-gov.go.jp/law/{law_id}/{mst},\n")
    csv_fp = tmp_path / "all_law_list.csv"
    csv_fp.write_text(CSV_HEADER + "".join(rows), encoding="utf-8-sig")
    return csv_fp


DIRS = [
    "129AC0000000089_20290623_508AC0000000045",
    "129AC0000000089_20260624_508AC0000000045",
    "129AC0000000089_20250401_506AC0000000033",
    "129AC0000000089_20270623_508AC0000000045",
    "999AC0000000001_20300101_512AC0000000001",   # not yet in force at all
]


def test_versions_sorted_by_enforcement_date(tmp_path):
    csv_fp = _make_dump(tmp_path, DIRS)
    vs = list_law_versions(tmp_path, csv_fp)["129AC0000000089"]
    assert [v.enforcement_date for v in vs] == ["20250401", "20260624", "20270623", "20290623"]
    assert vs[0].amend_law_name == "改正法20250401_506AC0000000033"
    assert vs[0].enforcement_note == "政令で定める日"


def test_split_picks_version_in_force(tmp_path):
    csv_fp = _make_dump(tmp_path, DIRS)
    vs = list_law_versions(tmp_path, csv_fp)["129AC0000000089"]
    current, pending, in_force = split_current_pending(vs, "20260928")
    assert in_force
    assert current.enforcement_date == "20260624"
    assert [v.enforcement_date for v in pending] == ["20270623", "20290623"]


def test_split_enforcement_day_is_in_force(tmp_path):
    csv_fp = _make_dump(tmp_path, DIRS)
    vs = list_law_versions(tmp_path, csv_fp)["129AC0000000089"]
    current, _, _ = split_current_pending(vs, "20270623")
    assert current.enforcement_date == "20270623"


def test_split_law_not_yet_in_force(tmp_path):
    csv_fp = _make_dump(tmp_path, DIRS)
    vs = list_law_versions(tmp_path, csv_fp)["999AC0000000001"]
    current, pending, in_force = split_current_pending(vs, "20260928")
    assert not in_force
    assert current.enforcement_date == "20300101"
    assert pending == []


def test_find_law_xmls_without_csv(tmp_path):
    _make_dump(tmp_path, DIRS)
    got = {p.parent.name for _, p in find_law_xmls(tmp_path, None, as_of="20260928")}
    assert got == {"129AC0000000089_20260624_508AC0000000045",
                   "999AC0000000001_20300101_512AC0000000001"}
