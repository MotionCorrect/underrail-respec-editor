"""Crawl Stygian Underrail wiki feat pages into local rule/id JSON.

This is intentionally stdlib-only. It uses MediaWiki categorymembers for
Category:Feats, then parses the rendered HTML requirements list for each page.
"""
from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Tuple

PACKAGE_ROOT = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_ROOT / "data"
API = "https://www.stygiansoftware.com/wiki/api.php"
ATTRS = {"Strength", "Dexterity", "Agility", "Constitution", "Perception", "Will", "Intelligence"}
SKILLS = {
    "Guns", "Heavy Guns", "Throwing", "Crossbows", "Melee", "Dodge", "Evasion", "Stealth",
    "Hacking", "Lockpicking", "Pickpocketing", "Traps", "Mechanics", "Electronics", "Chemistry",
    "Biology", "Tailoring", "Thought Control", "Psychokinesis", "Metathermics", "Temporal Manipulation",
    "Persuasion", "Intimidation", "Mercantile",
}
PSI_SKILLS = ["Thought Control", "Psychokinesis", "Metathermics", "Temporal Manipulation"]

# Overrides learned from verified save records / community abbreviations.
ID_OVERRIDES = {
    "Psi Empathy": "pe",
    "Marksman": "ds",  # verified in supplied JetSki save record; name shown by screenshot
    "Three-Pointer": "threepointer",
    "Burglar (feat)": "burglar",
    "Gunslinger (feat)": "gunslinger",
    "Hunter (feat)": "hunter",
}

REQ_NAME_FIXES = {
    "Dodge and Evasion": ["Dodge", "Evasion"],
    "Thought Control": ["Thought Control"],
    "Temporal Manipulation": ["Temporal Manipulation"],
}

ATTRIBUTE_PAGES = {
    "Strength": "Strength",
    "Dexterity": "Dexterity",
    "Agility": "Agility",
    "Constitution": "Constitution",
    "Perception": "Perception",
    "Will": "Will (Base Ability)",
    "Intelligence": "Intelligence",
}


def fetch_json(params: Dict[str, str]) -> Dict[str, Any]:
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "underrail-respec-local/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def category_members() -> List[str]:
    titles: List[str] = []
    params = {"action": "query", "list": "categorymembers", "cmtitle": "Category:Feats", "cmlimit": "500", "format": "json"}
    while True:
        data = fetch_json(params)
        titles.extend(m["title"] for m in data["query"]["categorymembers"] if m["ns"] == 0 and m["title"] != "Feats")
        cont = data.get("continue", {}).get("cmcontinue")
        if not cont:
            break
        params["cmcontinue"] = cont
    return sorted(set(titles))


def fetch_rendered_html(title: str) -> str:
    data = fetch_json({"action": "parse", "page": title, "prop": "text", "format": "json", "redirects": "1"})
    return data["parse"]["text"]["*"]


def fetch_raw(title: str) -> str:
    url = "https://www.stygiansoftware.com/wiki/index.php?" + urllib.parse.urlencode({"title": title, "action": "raw"})
    req = urllib.request.Request(url, headers={"User-Agent": "underrail-respec-local/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def clean_html(fragment: str) -> str:
    fragment = re.sub(r"<sup.*?</sup>", " ", fragment, flags=re.S | re.I)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    fragment = html.unescape(fragment)
    fragment = re.sub(r"\s+", " ", fragment).strip()
    return fragment


def clean_wiki_text(text: str) -> str:
    text = re.sub(r"\{\{[^{}]*(?:\{\{[^{}]*\}\}[^{}]*)*\}\}", " ", text)
    text = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"'''?", "", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def extract_first_blockquote(page_html: str) -> str:
    m = re.search(r"<blockquote\b[^>]*>(.*?)</blockquote>", page_html, flags=re.S | re.I)
    return clean_html(m.group(1)) if m else ""


def extract_feat_description(raw: str) -> str:
    m = re.search(r"\|\s*description\s*=\s*(.*?)(?=\n\|\s*\w+\s*=|\n\}\})", raw, flags=re.S | re.I)
    return clean_wiki_text(m.group(1)) if m else ""


def extract_requirement_texts(page_html: str) -> List[str]:
    out: List[str] = []
    # Rendered feat infoboxes use a Requirements header followed by a ul.
    for m in re.finditer(r"Requirements</span>\s*<ul>(.*?)</ul>", page_html, flags=re.S | re.I):
        ul = m.group(1)
        for li in re.finditer(r"<li>(.*?)</li>", ul, flags=re.S | re.I):
            txt = clean_html(li.group(1))
            if txt and txt not in out:
                out.append(txt)
    return out


def canonical_title(title: str) -> str:
    if title.endswith(" (feat)"):
        return title[:-7]
    return title


def feat_id_for_title(title: str) -> str:
    display = canonical_title(title)
    if title in ID_OVERRIDES:
        return ID_OVERRIDES[title]
    if display in ID_OVERRIDES:
        return ID_OVERRIDES[display]
    return re.sub(r"[^a-z0-9]", "", display.lower())


def parse_numeric_requirement(text: str) -> Tuple[str, int] | None:
    m = re.search(r"(.+?)\s+(\d+)\s*$", text)
    if not m:
        return None
    return m.group(1).strip(), int(m.group(2))


def parse_requirements(reqs: List[str]) -> Dict[str, Any]:
    rule: Dict[str, Any] = {"attributes": {}, "skills": {}, "any_skill_groups": [], "other_feats": [], "level_min": None, "raw_requirements": reqs, "confidence": "wiki-crawled"}
    for raw in reqs:
        text = raw.replace("Base Ability:", "").replace("Skill:", "").strip()
        text = re.sub(r"^(Feat|Restricted Feat|Restricted feat|Restricted feats|Restricted Feats):?\s+", "", text).strip()
        if not text:
            continue
        if text.lower().startswith("level"):
            m = re.search(r"(\d+)", text)
            if m:
                rule["level_min"] = int(m.group(1))
            continue
        # Common special forms.
        if re.search(r"any psi skill\s+(\d+)", text, re.I):
            req = int(re.search(r"(\d+)", text).group(1))
            rule["any_skill_groups"].append({"skills": PSI_SKILLS, "min": req})
            continue
        # Shared numeric requirement over alternatives, e.g.
        # "Guns or Crossbows 10" or "Melee , Guns , Heavy Guns or Crossbows 75".
        shared = re.search(r"^(.+?)\s+(\d+)\s*$", text)
        if shared:
            names_text, req = shared.group(1), int(shared.group(2))
            names = [p.strip() for p in re.split(r"\s*(?:,|\bor\b)\s*", names_text) if p.strip()]
            if len(names) > 1 and all(n in SKILLS for n in names):
                rule["any_skill_groups"].append({"skills": names, "min": req})
                continue
        parsed = parse_numeric_requirement(text)
        if parsed:
            name, req = parsed
            # Sometimes wiki text says "Dodge and Evasion 40".
            if " and " in name:
                names = [p.strip() for p in name.split(" and ")]
                if all(n in SKILLS for n in names):
                    for n in names:
                        rule["skills"][n] = req
                    continue
            if name in ATTRS:
                rule["attributes"][name] = req
                continue
            if name in SKILLS:
                rule["skills"][name] = req
                continue
        # Bare feat prereq, e.g. Psi Empathy.
        if re.match(r"^[A-Z][A-Za-z' -]+$", text) and not any(ch.isdigit() for ch in text):
            rule["other_feats"].append(canonical_title(text))
            continue
    if rule["level_min"] is None:
        rule.pop("level_min")
    if not rule["any_skill_groups"]:
        rule.pop("any_skill_groups")
    if not rule["other_feats"]:
        rule.pop("other_feats")
    return rule


def main() -> None:
    titles = category_members()
    rules: Dict[str, Any] = {}
    ids: Dict[str, str] = {}
    tooltips: Dict[str, Dict[str, str]] = {"attributes": {}, "skills": {}, "feats": {}}
    failures = []
    for display, page_title in ATTRIBUTE_PAGES.items():
        try:
            tooltips["attributes"][display] = extract_first_blockquote(fetch_rendered_html(page_title))
        except Exception as e:
            failures.append({"title": page_title, "kind": "attribute-tooltip", "error": str(e)})
    for skill in sorted(SKILLS):
        try:
            tooltips["skills"][skill] = extract_first_blockquote(fetch_rendered_html(skill))
        except Exception as e:
            failures.append({"title": skill, "kind": "skill-tooltip", "error": str(e)})
    for i, title in enumerate(titles, 1):
        display = canonical_title(title)
        try:
            page = fetch_rendered_html(title)
            raw = fetch_raw(title)
            reqs = extract_requirement_texts(page)
            rules[display] = parse_requirements(reqs)
            ids[display] = feat_id_for_title(title)
            tooltips["feats"][display] = extract_feat_description(raw)
            print(f"{i:03d}/{len(titles)} {display}: {reqs}")
            time.sleep(0.05)
        except Exception as e:
            failures.append({"title": title, "error": str(e)})
            print(f"ERROR {title}: {e}")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "feat_rules.json").write_text(json.dumps(rules, indent=2, sort_keys=True), encoding="utf-8")
    (DATA_DIR / "feat_ids.json").write_text(json.dumps(ids, indent=2, sort_keys=True), encoding="utf-8")
    (DATA_DIR / "wiki_tooltips.json").write_text(json.dumps(tooltips, indent=2, sort_keys=True), encoding="utf-8")
    (DATA_DIR / "feat_crawl_report.json").write_text(json.dumps({"count": len(rules), "failures": failures}, indent=2), encoding="utf-8")
    print(f"Wrote {len(rules)} rules, {len(ids)} ids; failures={len(failures)}")


if __name__ == "__main__":
    main()
