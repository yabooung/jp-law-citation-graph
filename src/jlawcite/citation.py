"""Japanese statutory citation extractor.

Validated at 93% NTA parse rate (v1).

Covers:
  - Internal:    第N条 / 第N条の2 / 第N条第M項 / 第N条第M項第K号
  - External:    法令名（promulgation_year法律第Num号）第N条 — also bare 法令名第N条
  - Referential: 前条 / 次条 / 同条 / 同項 / 同号 / 本条 / 本項
  - Range:       第N条から第M条まで
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .numerals import NUMERAL_RE, kanji_to_int

# ---------- Patterns ----------
_NUM = NUMERAL_RE

# Shared article-locator tail: 第N条(のM)*(第N項)?(第N号(のM)*)?
# Named groups: art, eda, para, item, item_eda. Optional leading 附則 (suppl).
_LOCATOR = (
    rf"(?P<suppl>附則)?"
    rf"第(?P<art>{_NUM})条"
    rf"(?P<eda>(?:の{_NUM})*)"
    rf"(?:第(?P<para>{_NUM})項)?"
    rf"(?:第(?P<item>{_NUM})号(?P<item_eda>(?:の{_NUM})*))?"
)

INTERNAL_PAT = re.compile(_LOCATOR)

# 附則第N項 — paragraphs of an Article-less 附則 (synthetic article '0').
SUPPL_PARA_PAT = re.compile(
    rf"附則第(?P<para>{_NUM})項(?:第(?P<item>{_NUM})号(?P<item_eda>(?:の{_NUM})*))?"
)

LAW_NAME_PAT = (
    r"([一-鿿々ヶ぀-ゟァ-ヶー、]{1,40}?"
    # 則 covers 規則/細則 and defined short forms (雇保則); never 附則.
    r"(?:基本通達|条約|憲法|条例|法律|法|令|(?<!附)則|通達|告示|協定|議定書|規程|基準))"
)

PROM_PAT = (
    r"（"  # full-width left paren (
    r"(?:((?:明治|大正|昭和|平成|令和)[\d一二三四五六七八九十元]+年"
    r"[一-鿿・]{0,16}?(?:法律|政令|省令|府令|規則|条約|勅令|告示)第[\d一二三四五六七八九十百千]+号)"
    # optional abbreviation definition: （…号。以下「施行規則」という。）
    r"(?:[。、]\s*以下[^（）]{0,40}?という。?)?"
    r"|以下[^（）]{0,40}?という。?)"
    r"）"  # full-width right paren )
)

EXTERNAL_FULL_PAT = re.compile(
    rf"{LAW_NAME_PAT}\s*(?:{PROM_PAT})?\s*{_LOCATOR}"
)

# Short law tokens that LAW_NAME_PAT cannot capture on their own (it needs
# at least one character before the suffix): bare 法/令/規則 (the enabling
# act / order in a 施行令・施行規則), 同法 (last-named law), 新法/旧法
# (the law as amended / before amendment, in 附則). Must not be preceded by
# kanji/katakana, otherwise 「税法第」「政令第」 would match here.
NAKED_LAW_PAT = re.compile(
    # Katakana okurigana particles (此ノ場合ニ於テハ同法) are allowed before.
    r"(?<![一-鿿々〆ヵヶ])(?<![ァ-ヴー](?<![ニヲハガトノモヘテ]))"
    r"(?P<name>同法|同令|同規則|同省令|同府令|同条例"
    r"|新法|旧法|新令|旧令|新規則|旧規則"
    r"|施行令|施行規則|法|令|規則|省令)"
    + _LOCATOR
)

REFERENTIAL_PAT = re.compile(
    r"(前条|次条|同条|同項|同号|本条|本項|前項|次項|前号|次号|前各号|各号"
    r"|同法|同令|同規則|同条例"          # same-law context refs (v2.1)
    r"|新法|旧法|新令|旧令|新規則|旧規則"  # amendment context refs (v2.1)
    r"|本法|本令|本規則)"                  # this-law refs (v2.1)
)

# Text allowed between two article citations for the second to inherit the
# first one's law: 「会社法第八百三十三条第二項、第八百三十四条」,
# 「第百八十五条から第百八十七条まで」, 「第十条（責任準備金）及び第十一条」.
_PAREN2 = r"（[^（）]*(?:（[^（）]*(?:（[^（）]*）[^（）]*)*）[^（）]*)*）"
ENUM_GAP_PAT = re.compile(
    rf"^(?:{_PAREN2}|、|及び|並びに|又は|若しくは|から|まで|\s"
    rf"|第{_NUM}(?:項|号(?:の{_NUM})*|編|章|節|款|目)"   # 第十条第二項及び第三項、第十一条
    rf"|前段|後段|本文|ただし書|各号|の表)+"
    rf"(?:中「)?$"                                     # 銀行法第十条中「第十一条」
)

# Locator right after a referential token (同条第二項第三号 / 同項第二号).
REF_TAIL_PAT = re.compile(
    rf"(?:第(?P<para>{_NUM})項)?(?:第(?P<item>{_NUM})号(?P<item_eda>(?:の{_NUM})*))?"
)

RANGE_PAT = re.compile(
    rf"第({_NUM})条(?:から|乃至)第({_NUM})条まで"
)

ITEM_ONLY_PAT = re.compile(rf"第({_NUM})号")

# ---- v2 신규: 別表 / 様式 reference ---------------------------------------
# Examples: 「別表第1」「別表第二」「別表第1の2」「様式第3号」
ATTACHMENT_REF_PAT = re.compile(
    rf"(別表|様式|書式|別記|別図|附録|付録)"
    rf"(?:第({_NUM})(?:号)?(?:の({_NUM}))?(?:号)?"
    rf"|(?![第一-鿿]))"  # bare 別表 (sole annex) — but not 別表中 / 様式等 compounds
)

# Reference kind → attachment ID prefix (mirrors xml_parser._ATTACHMENT_KIND_PREFIX)
_ATTACHMENT_REF_PREFIX = {
    "別表": "", "様式": "style-", "書式": "format-", "別記": "note-",
    "別図": "fig-", "附録": "appdx-", "付録": "appdx-",
}

# ---- v2 신규: 위임 (DELEGATES_TO) -----------------------------------------
# 政令/省令/府令/規則/命令 등 하위법령 위임 표현을 본문에서 추출.
# 「政令で定める」「主務省令で定める」「内閣府令で定める」 등.
# 참고: 단어 자체만으로는 어느 법령으로 위임되는지 모르므로,
# 위임 의도는 표현으로 추출하고 실제 target은 source 法令 family에서 추정.
DELEGATION_PAT = re.compile(
    r"(政令|内閣府令|主務省令|省令|府令|規則|命令)で定める"
)

# ---- v2 신규: 개정 (AMENDS) -----------------------------------------------
# 부칙(SupplProvision) 본문에서 본법 조문을 수정하는 표현.
# 「第N条を次のように改める」「第N条を削る」「第N条の次に次の一条を加える」
AMEND_PAT = re.compile(
    rf"第({_NUM})条((?:の{_NUM})*)"
    rf"(?:第({_NUM})項)?"
    rf"を(?:次のように|削る|加える|改める)"
)


@dataclass
class AttachmentRef:
    """Reference to an Attachment (別表 / 様式)."""
    raw: str
    kind: str         # 別表 / 様式 / 別記 / 附録 / 目録
    annex_num: int    # leading number (e.g. 1 for 別表第1)
    annex_eda: int | None = None  # 別表第1の2의 '2'
    span: tuple[int, int] = (0, 0)

    @property
    def annex_id(self) -> str:
        if self.annex_eda is not None:
            return f"{self.annex_num}-{self.annex_eda}"
        return str(self.annex_num)

    @property
    def attachment_slug(self) -> str:
        """Slug matching the Attachment node id suffix (`{law_id}_at-{slug}`)."""
        return _ATTACHMENT_REF_PREFIX.get(self.kind, "") + self.annex_id


@dataclass
class DelegationRef:
    """Delegation marker (caller resolves target law)."""
    raw: str
    target_kind: str  # 政令 / 省令 / 府令 / 規則 / 命令
    span: tuple[int, int] = (0, 0)


@dataclass
class AmendRef:
    """Amendment of a main-law article from a SupplArticle."""
    raw: str
    article_num: int
    eda: list[int] = field(default_factory=list)
    paragraph: int | None = None
    span: tuple[int, int] = (0, 0)


# ---------- Data classes ----------
@dataclass
class IntRef:
    """Internal reference (within current article's law)."""
    raw: str
    article_num: int
    eda: list[int] = field(default_factory=list)
    paragraph: int | None = None
    item: int | None = None
    span: tuple[int, int] = (0, 0)
    suppl: bool = False               # 附則第N条 / 附則第N項
    item_eda: list[int] = field(default_factory=list)

    @property
    def article_path(self) -> str:
        if self.eda:
            return "-".join([str(self.article_num)] + [str(e) for e in self.eda])
        return str(self.article_num)

    @property
    def item_path(self) -> str | None:
        if self.item is None:
            return None
        return "-".join([str(self.item)] + [str(e) for e in self.item_eda])


@dataclass
class ExtRef:
    """External reference (other law)."""
    raw: str
    law_name_raw: str
    article_num: int
    eda: list[int] = field(default_factory=list)
    paragraph: int | None = None
    item: int | None = None
    promulgation: str | None = None
    span: tuple[int, int] = (0, 0)
    suppl: bool = False
    item_eda: list[int] = field(default_factory=list)
    naked: bool = False               # matched by NAKED_LAW_PAT (法/同法/新法 …)

    @property
    def article_path(self) -> str:
        if self.eda:
            return "-".join([str(self.article_num)] + [str(e) for e in self.eda])
        return str(self.article_num)

    @property
    def item_path(self) -> str | None:
        if self.item is None:
            return None
        return "-".join([str(self.item)] + [str(e) for e in self.item_eda])


@dataclass
class RefRef:
    """Referential (前条 / 次条 / 同条 etc.), with an optional trailing
    locator (同条第二項 → paragraph=2)."""
    raw: str
    kind: str
    span: tuple[int, int] = (0, 0)
    paragraph: int | None = None
    item: int | None = None
    item_eda: list[int] = field(default_factory=list)

    @property
    def item_path(self) -> str | None:
        if self.item is None:
            return None
        return "-".join([str(self.item)] + [str(e) for e in self.item_eda])


# ---------- Extractors ----------
def parse_eda(eda_str: str) -> list[int]:
    """'の2の3' → [2, 3]. Empty string → []."""
    if not eda_str:
        return []
    parts = re.findall(rf"の({_NUM})", eda_str)
    return [v for p in parts if (v := kanji_to_int(p)) is not None]


# Leading clutter that the law-name regex over-captures. Stripped post-match
# so EXTERNAL_FULL_PAT spans stay accurate (mask spans for internal extraction).
# v2.3 보강 (stopword 패턴): unresolved_external 15K sample 분석에서
# fragment_overgrab 16% + long_overgrab 21% = 37% over-grab 확인. 새 prefix 추가:
#   - 조사+naked: は、 / ただし、 / が / を / の / に
#   - amendment 부칙: の次に一条を加える改正規定、 / 改正規定、 / 同条を / これらの規定を / の改正
#   - context 부사: この場合において、 / なお / 例えば / 特に
_EXT_LAW_NAME_LEADING_NOISE = re.compile(
    r"^(?:"
    # NEW v2.4: long verb-clause prefix (실측 unresolved sample top patterns)
    r"掲げる者が|掲げる者に該当しなくなったとき(?:[、,]|若しくは)?|"
    r"使用者は[、,]?|事業者は[、,]?|発注者は[、,]?|"
    r"既に|現に|これを|これに|これから|"
    r"一項を加える改正規定[、,]?|二項を加える改正規定[、,]?|"
    r"同条の次に一条を加える改正規定[、,]?|"
    r"一条を加える改正規定[、,]?|"
    # NEW v2.5: 부칙 long pattern + clause
    r"この法律の施行の際現に|この法律の施行の際|"
    r"なおその効力を有するものとされる|するものとされた|"
    r"場合には[、,]?|場合に[、,]?|かかわらず[、,]?|"
    r"協会が|"
    # NEW v2.6: 第N条 anchored prefix + specific role+조사
    r"第[一二三四五六七八九十百千〇0-9]+条第[一二三四五六七八九十0-9]+項において準用する|"
    r"第[一二三四五六七八九十百千〇0-9]+条において準用する|"
    r"第[一二三四五六七八九十百千〇0-9]+条において|"
    r"船舶所有者は[、,]?|厚生労働大臣は[、,]?|"
    r"都道府県知事は[、,]?|市町村長は[、,]?|"
    # NEW v2.7: more clause prefix from v2.6 unresolved analysis
    r"第[一二三四五六七八九十百千〇0-9]+項の規定により[、,]?|"
    r"第[一二三四五六七八九十百千〇0-9]+号の規定により[、,]?|"
    r"に係る[、,]?|係る[、,]?|質問等及び|同条に|改める[、,]?|"
    r"における|に基づく|に対する|"
    r"ついて[、,]?|"
    r"経過措置期間適用月が[一二三四五六七八九十0-9]+月以外の月の場合にあっては[、,]?|"
    # NEW v2.9: 부칙 timing prefix
    r"施行日前にされた|施行日前に|"
    r"平成[一二三四五六七八九十0-9]+年[一二三四五六七八九十0-9]*月?改正前|"
    r"平成[一二三四五六七八九十0-9]+年改正法附則第[一二三四五六七八九十百千〇0-9]+条の規定による改正前の|"
    # NEW v2.9: 金融サービスの fragment (실측 39 case)
    r"金融サービスの|"
    # NEW v2.3: 부칙 amendment 패턴 (긴 것 먼저 — alternation leftmost-match)
    r"の次に一条を加える改正規定[、,]?|の次に[一二三四五六七八九十]+条を加える改正規定[、,]?|"
    r"を加える改正規定[、,]?|これらの規定を|"
    r"改正規定[、,]?|同条を|"
    # NEW v2.3: context 부사
    r"この場合において[、,]|なお[、,]?|例えば[、,]?|特に[、,]?|"
    # 기존 v2.1 패턴
    r"の改正規定[、,]?|において準用する|により準用する|"
    r"とする|とし|の規定により|の規定による|の規定[、,]?|"
    r"準用する|"
    r"又は|及び|並びに|若しくは|と|や|に|から|まで|"
    # NEW v2.3: 조사+naked prefix (KR 의 동사형/조사 패턴 포팅)
    r"は[、,]|ただし[、,]?|が|を|の|"
    r"による|により|について|に基づき|に従い|に応じて|に係る|"
    r"[、,。\s]+"
    r")+"
)

# Tokens that look like a law-name capture but are actually referential
# (handled by REFERENTIAL_PAT, not as external citation).
_REFERENTIAL_LAWNAME_TOKENS = {
    "同法", "同令", "同規則", "同条例",
    "新法", "旧法", "新令", "旧令", "新規則", "旧規則",
    "本法", "本令", "本規則",
    "前法", "次法",
    # "新+모법" forms surfacing as captured law name end with these — handled
    # downstream by prefix stripping in LawNameIndex.
}


# A captured name that is really a clause ending in a short law token:
# 「指定試験機関は、法」「削る改正規定、同法」「此ノ場合ニ於テハ同法」. No real
# law title ends in 、法 / は法, so this is safe without a name lookup.
# Katakana particles only before 同/新/旧 tokens — 「テスト法」 must stay a name.
_CLAUSE_TAIL_TOKEN = re.compile(
    r"(?:[、ぁ-んニヲハガトノモヘテ](?P<tok>同法|同令|同規則|同省令|新法|旧法|新令|旧令|新規則|旧規則)"
    # Bare tokens: only 法 — 「…に関する省令」「…を定める規則」 are real titles.
    r"|[、ぁ-ん](?P<bare>法))$")
# Over-captured prefix up to the last article locator: 「第十条の規定により所得税法」
_LEADING_LOCATOR = re.compile(rf".*第{_NUM}(?:条|項|号)(?:の{_NUM})*")


def _clean_law_name(raw: str) -> str:
    name = raw
    m = _LEADING_LOCATOR.match(name)
    if m:
        name = name[m.end():]
    return _EXT_LAW_NAME_LEADING_NOISE.sub("", name).strip()


def extract_external(text: str) -> tuple[list[ExtRef], list[tuple[int, int]]]:
    """Returns (refs, spans_consumed).

    EXTERNAL_FULL_PAT groups: 1=law_name, 2=prom (inside ()), then _LOCATOR
    named groups. A second pass (NAKED_LAW_PAT) picks up 法/同法/新法-style
    short tokens outside the first pass's spans; those refs have naked=True
    and law_name_raw set to the token.

    Cleans `law_name_raw` by stripping leading clutter (`の改正規定、`,
    `又は`, etc.) post-match. Drops captures whose law_name reduces to a
    pure referential token (`同法`, `新法`, …) — those are handled by
    extract_referential.
    """
    refs: list[ExtRef] = []
    spans: list[tuple[int, int]] = []
    for m in EXTERNAL_FULL_PAT.finditer(text):
        law_name = _clean_law_name(m.group(1))
        if not law_name or law_name in _REFERENTIAL_LAWNAME_TOKENS:
            # 同法第N条 etc. — picked up by the NAKED_LAW_PAT pass below.
            continue
        naked = False
        tail = _CLAUSE_TAIL_TOKEN.search(law_name)
        if tail:
            # 「前項の規定は、法」「削る改正規定、同法」 → the short token only
            law_name, naked = tail.group("tok") or tail.group("bare"), True
        ref = _ext_ref(m, law_name, m.group(2))
        if ref:
            # Span starts at the cleaned name, so over-captured clause text
            # (and any 前項 / 第N条 in it) stays visible to the other passes.
            ref.span = (m.end(1) - len(law_name), m.end())
            ref.raw = text[ref.span[0]:ref.span[1]]
            ref.naked = naked
            refs.append(ref)
            spans.append(ref.span)

    for m in NAKED_LAW_PAT.finditer(text):
        if any(s <= m.start() < e for s, e in spans):
            continue
        ref = _ext_ref(m, m.group("name"), None)
        if ref:
            ref.naked = True
            refs.append(ref)
            spans.append(ref.span)
    refs.sort(key=lambda r: r.span)
    spans.sort()
    return refs, spans


def _ext_ref(m: re.Match, law_name: str, prom: str | None) -> ExtRef | None:
    art_n = kanji_to_int(m.group("art"))
    if art_n is None:
        return None
    para, item = m.group("para"), m.group("item")
    return ExtRef(
        raw=m.group(0),
        law_name_raw=law_name,
        article_num=art_n,
        eda=parse_eda(m.group("eda")),
        paragraph=kanji_to_int(para) if para else None,
        item=kanji_to_int(item) if item else None,
        promulgation=prom,
        span=(m.start(), m.end()),
        suppl=bool(m.group("suppl")),
        item_eda=parse_eda(m.group("item_eda") or ""),
    )


def extract_internal(text: str, mask_spans: list[tuple[int, int]] | None = None) -> list[IntRef]:
    """Internal refs, excluding those within external spans."""
    mask_spans = mask_spans or []

    def in_mask(pos: int) -> bool:
        return any(s <= pos < e for s, e in mask_spans)

    refs: list[IntRef] = []
    for m in INTERNAL_PAT.finditer(text):
        if in_mask(m.start()):
            continue
        art = kanji_to_int(m.group("art"))
        if art is None:
            continue
        refs.append(IntRef(
            raw=m.group(0),
            article_num=art,
            eda=parse_eda(m.group("eda")),
            paragraph=kanji_to_int(m.group("para")) if m.group("para") else None,
            item=kanji_to_int(m.group("item")) if m.group("item") else None,
            span=(m.start(), m.end()),
            suppl=bool(m.group("suppl")),
            item_eda=parse_eda(m.group("item_eda") or ""),
        ))
    # 附則第N項 → synthetic suppl article '0'
    for m in SUPPL_PARA_PAT.finditer(text):
        if in_mask(m.start()):
            continue
        para = kanji_to_int(m.group("para"))
        if para is None:
            continue
        refs.append(IntRef(
            raw=m.group(0),
            article_num=0,
            paragraph=para,
            item=kanji_to_int(m.group("item")) if m.group("item") else None,
            span=(m.start(), m.end()),
            suppl=True,
            item_eda=parse_eda(m.group("item_eda") or ""),
        ))
    refs.sort(key=lambda r: r.span)
    return refs


def extract_referential(text: str, mask_spans: list[tuple[int, int]] | None = None) -> list[RefRef]:
    mask_spans = mask_spans or []

    def in_mask(pos: int) -> bool:
        return any(s <= pos < e for s, e in mask_spans)

    out: list[RefRef] = []
    for m in REFERENTIAL_PAT.finditer(text):
        if in_mask(m.start()):
            continue
        ref = RefRef(raw=m.group(0), kind=m.group(1), span=(m.start(), m.end()))
        # Trailing locator: 同条第二項 / 前条第一項第三号 / 同項第二号
        t = REF_TAIL_PAT.match(text, m.end())
        if t and t.group(0):
            ref.paragraph = kanji_to_int(t.group("para")) if t.group("para") else None
            if t.group("item"):
                ref.item = kanji_to_int(t.group("item"))
                ref.item_eda = parse_eda(t.group("item_eda") or "")
            ref.raw = text[m.start():t.end()]
            ref.span = (m.start(), t.end())
        out.append(ref)
    return out


def extract_attachment_refs(
    text: str,
    mask_spans: list[tuple[int, int]] | None = None,
) -> list[AttachmentRef]:
    """別表/様式/別記 references → AttachmentRef list."""
    mask_spans = mask_spans or []

    def in_mask(pos: int) -> bool:
        return any(s <= pos < e for s, e in mask_spans)

    out: list[AttachmentRef] = []
    for m in ATTACHMENT_REF_PAT.finditer(text):
        if in_mask(m.start()):
            continue
        # Bare 別表 / 別記様式 → the law's sole un-numbered annex ('0')
        n = kanji_to_int(m.group(2)) if m.group(2) else 0
        if n is None:
            continue
        eda = kanji_to_int(m.group(3)) if m.group(3) else None
        out.append(AttachmentRef(
            raw=m.group(0),
            kind=m.group(1),
            annex_num=n,
            annex_eda=eda,
            span=(m.start(), m.end()),
        ))
    return out


def extract_delegations(
    text: str,
    mask_spans: list[tuple[int, int]] | None = None,
) -> list[DelegationRef]:
    """Find delegation markers ('政令で定める' 등). Caller resolves target law."""
    mask_spans = mask_spans or []

    def in_mask(pos: int) -> bool:
        return any(s <= pos < e for s, e in mask_spans)

    out: list[DelegationRef] = []
    for m in DELEGATION_PAT.finditer(text):
        if in_mask(m.start()):
            continue
        out.append(DelegationRef(
            raw=m.group(0),
            target_kind=m.group(1),
            span=(m.start(), m.end()),
        ))
    return out


def extract_amendments(text: str) -> list[AmendRef]:
    """Detect amendment refs in SupplArticle text ('第N条を…改める' 등)."""
    out: list[AmendRef] = []
    for m in AMEND_PAT.finditer(text):
        n = kanji_to_int(m.group(1))
        if n is None:
            continue
        out.append(AmendRef(
            raw=m.group(0),
            article_num=n,
            eda=parse_eda(m.group(2)),
            paragraph=kanji_to_int(m.group(3)) if m.group(3) else None,
            span=(m.start(), m.end()),
        ))
    return out


def extract_all(text: str) -> dict:
    """Convenience: extract all reference types from text."""
    ext, spans = extract_external(text)
    internal = extract_internal(text, mask_spans=spans)
    refer = extract_referential(text, mask_spans=spans)
    return {
        "external": ext,
        "internal": internal,
        "referential": refer,
    }
