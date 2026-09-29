"""NTA 関係法令 → article-level gold (jlawcite.pipeline.resolve_gold)."""
from collections import Counter

from jlawcite.pipeline.resolve_gold import parse_refs, resolve_case


def arts(lines, comma_titles=()):
    return [(law, path) for law, path, _ in parse_refs(lines, comma_titles)]


def test_every_article_in_a_list():
    # the old resolver kept only 第11条
    assert arts(["所得税法第11条第2項、第153条第3項"]) == [("所得税法", "11"), ("所得税法", "153")]


def test_seirei_list_stays_on_seirei():
    assert arts(["法人税法施行令第54条、第134条"]) == [("法人税法施行令", "54"), ("法人税法施行令", "134")]


def test_fullwidth_eda():
    assert arts(["法人税法第22条の２"]) == [("法人税法", "22-2")]
    assert arts(["施行令第82条の3の2"]) == [("施行令", "82-3-2")]


def test_law_carries_to_next_line_and_sub_only_segments():
    assert arts(["所得税法第2条第1項", "第3条", "第5項"]) == [("所得税法", "2"), ("所得税法", "3")]


def test_law_name_alone_then_articles():
    assert arts(["消費税法", "第30条"]) == [("消費税法", "30")]


def test_parenthesized_law_number_dropped():
    assert arts(["所得税法(昭和40年法律第33号)第9条"]) == [("所得税法", "9")]


def test_comma_inside_law_name():
    name = "災害被害者に対する租税の減免、徴収猶予等に関する法律"
    assert arts([f"{name}第2条"], [name]) == [(name, "2")]


def _case(*lines):
    return {"id": "x", "zeimu": "z", "url": "u", "title": "t", "shokai": "q", "kaito": "a",
            "kankeihrei": list(lines)}


def test_resolve_case_buckets():
    index = ({"所得税法": "340AC0000000033"}, {}, {}, {"340AC0000000033_a9"}, [])
    stats = Counter()
    r = resolve_case(_case("所得税法第9条、第999条", "所得税基本通達36-1第1条",
                           "所得税法附則第5条", "謎の法律第1条"), index, stats, Counter())
    assert r["gold_articles"] == ["340AC0000000033_a9"]
    assert r["external_refs"] == ["所得税基本通達36-1第1条"]
    assert r["out_of_scope_refs"] == ["所得税法附則第5条"]
    assert r["unresolved"] == ["第999条", "謎の法律第1条"]
    assert stats["cases_with_gold"] == 1
