"""Cluster / Commodity 术语归一（v3 Phase-18，领导：\"We need to consolidate the terminologies\"）。

周会 Excel 的 Commodity 列是自由文本：同一个东西写成 "SC" / "SC06" / "Stamping" / "SC Stamping"，
"Functional Plastics" / "FP" / "CH01" / "Funcional Plastics"……Dashboard 按 Cluster 统计时冒出几十个条目。

这里把原文映射到两层：
- cluster：提交页的三个固定 Cluster（Chemical / Metal / Electronics, EA and Pyro），与在线登记一致；
- commodity：规范的 Commodity 名（代码族 + 名称，如 "SC Stamping & Mechanical Metals"）。

认不出来的原文保持原样（cluster 与 commodity 都等于整理过空白的原文），known=False，导入预览里会列出来，
由领导补充词表；原文始终留在案例的 commodityRaw 里，词表改了可以重算。

词表来源：2025-09 至 2026-09 的 36 份周文件里出现过的 47 种写法，按代码前缀与关键词归类；
模板自带的 CLUSTER_OF（Seatbelt Webbing / Airbag Cushions & Fabric → Chemical 等）决定了 Textiles 归 Chemical。
VERSION 变了，服务启动时会按 commodityRaw 重算所有从 Excel 导入的案例（service._migrate_commodities）。
"""

from __future__ import annotations

import re

VERSION = 1

CHEMICAL = "Chemical"
METAL = "Metal"
ELECTRONICS = "Electronics, EA and Pyro"
CLUSTERS = [CHEMICAL, METAL, ELECTRONICS]

# 代码族 → (规范 Commodity 名, Cluster)。Cluster 为 None 的代码族认得出代码、不知道归哪个 Cluster（领导待补）。
CODE_FAMILIES: dict[str, tuple[str, str | None]] = {
    "CH": ("CH Chemical", CHEMICAL),
    "CH01": ("CH01 Functional Plastics", CHEMICAL),
    "FP": ("CH01 Functional Plastics", CHEMICAL),
    "SC": ("SC Stamping & Mechanical Metals", METAL),
    "FF": ("FF Forging, Forming & Tubes", METAL),
    "CA": ("CA Casting", METAL),
    "EL": ("EL Electronics", ELECTRONICS),
    "EA": ("EA Electromechanical", ELECTRONICS),
    "MI": ("MI", None),
    "SO": ("SO", None),
}

# 关键词（在整理过的大写原文里找）→ 代码族或独立 Commodity。顺序即优先级：先具体后笼统。
KEYWORDS: list[tuple[str, str]] = [
    ("PLASTIC", "CH01"),
    ("PYRO", "PYRO"),
    ("ELECTRONIC", "EL"),
    ("ELECTRO", "EA"),
    ("ELECTRIC", "EA"),
    ("MECHANICAL METAL", "SC"),
    ("STAMP", "SC"),
    ("POWDER METAL", "POWDER"),
    ("FORG", "FF"),
    ("FORMING", "FF"),
    ("WIRE", "FF"),
    ("TUBE", "FF"),
    ("CAST", "CA"),
    ("TEXT", "TEXTILES"),
    ("WEBBING", "TEXTILES"),
    ("FABRIC", "TEXTILES"),
    ("CHEMICAL", "CH"),
]

# 独立 Commodity（没有代码）：名 → Cluster
STANDALONE: dict[str, tuple[str, str]] = {
    "PYRO": ("Pyro", ELECTRONICS),
    "TEXTILES": ("Textiles", CHEMICAL),
    "POWDER": ("Powder Metal", METAL),
}

_CODE_RE = re.compile(r"^([A-Z]{2})\s?(\d{2,})?(?![A-Z])")


def normalize_text(raw: str | None) -> str:
    """整理空白与破折号；"SC 03" → "SC03"（代码和数字之间的空格去掉）。"""
    text = re.sub(r"[–—_]", " ", str(raw or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"^([A-Za-z]{2}) (\d)", r"\1\2", text)


def _family(upper: str) -> str | None:
    if m := _CODE_RE.match(upper):
        code, digits = m.group(1), m.group(2) or ""
        if code == "CH" and digits.startswith("01"):
            return "CH01"
        if code in CODE_FAMILIES:
            return code
    for needle, family in KEYWORDS:
        if needle in upper:
            return family
    return None


def classify(raw: str | None) -> dict:
    """原文 → {"cluster", "commodity", "known"}。"""
    text = normalize_text(raw)
    if not text:
        return {"cluster": "", "commodity": "", "known": False}
    upper = text.upper()
    if upper in {c.upper() for c in CLUSTERS}:  # 在线登记已经是 Cluster 本身
        cluster = next(c for c in CLUSTERS if c.upper() == upper)
        return {"cluster": cluster, "commodity": "", "known": True}
    family = _family(upper)
    if family in STANDALONE:
        name, cluster = STANDALONE[family]
        return {"cluster": cluster, "commodity": name, "known": True}
    if family in CODE_FAMILIES:
        name, cluster = CODE_FAMILIES[family]
        if cluster is None:  # 代码认得出、Cluster 未定：原样保留，等领导补词表
            return {"cluster": text, "commodity": text, "known": False}
        return {"cluster": cluster, "commodity": name, "known": True}
    return {"cluster": text, "commodity": text, "known": False}


def options() -> list[dict]:
    """编辑页 Commodity 下拉的规范清单（v3 Phase-37）：[{"cluster", "commodity"}]，按 CLUSTERS 分组、组内按词表顺序，
    每个名只出现一次（FP 与 CH01 同名）；Cluster 未定的代码族（MI、SO）不在清单里。"""
    named = [*CODE_FAMILIES.values(), *STANDALONE.values()]
    seen: set[str] = set()
    out: list[dict] = []
    for cluster in CLUSTERS:
        for name, of in named:
            if of == cluster and name not in seen:
                seen.add(name)
                out.append({"cluster": cluster, "commodity": name})
    return out


def cluster_of(commodity: str | None) -> str | None:
    """规范 Commodity 名 → 它的 Cluster；不在规范清单里返回 None。"""
    return next((o["cluster"] for o in options() if o["commodity"] == commodity), None)


def apply(case: dict, raw: str | None = None) -> dict:
    """把归一结果写到案例上（cluster / commodity / commodityRaw），返回归一结果。raw 缺省取案例已有的原文。"""
    source = raw if raw is not None else (case.get("commodityRaw") or case.get("cluster") or "")
    result = classify(source)
    case["cluster"] = result["cluster"]
    case["commodity"] = result["commodity"]
    case["commodityRaw"] = normalize_text(source)
    return result
