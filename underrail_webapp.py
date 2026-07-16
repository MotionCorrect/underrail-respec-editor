r"""
Local visual Underrail respec web app.

Run:
    cd C:\Git\underrail_edit
    python underrail_webapp.py

Open:
    http://127.0.0.1:8765

Safety model:
    * reads either a save folder or a global.dat
    * writes only to a newly cloned save folder via /api/create-respec
    * never edits the source save folder in place
    * validates point neutrality, legal caps, and known feat prerequisites

This app intentionally edits only the 7 attributes and 24 skills already verified
by underrail_savetool.py. Feats and unspent-point storage are not modified.
"""

from __future__ import annotations
import gzip
import json
import os
import shutil
import sys
import time
import traceback
from datetime import datetime

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from underrail_savetool import ATTRS, SKILLS, Save

DEFAULT_PORT = 8765
DEFAULT_SAVES_DIR = Path.home() / "Documents" / "My Games" / "Underrail" / "Saves"
ROOT = Path(__file__).resolve().parent
FEAT_IDS_PATH = ROOT / "feat_ids.json"
FEAT_RULES_PATH = ROOT / "feat_rules.json"
TOOLTIPS_PATH = ROOT / "wiki_tooltips.json"

# Visible in the supplied screenshots. Feat storage itself is not mapped, so the
# app lets the user select/adjust this list manually before validation.
SCREENSHOT_FEATS = {
    "jetski": [
        "Fast Metabolism",
        "Marksman",
        "Pack Rathound",
        "Versatility",
        "Disassemble",
        "Expanded Psi Capacitance",
        "Concussive Shots",
        "Hunter",
        "Psi Empathy",
    ],
    "assault": [
        "Fast Metabolism",
        "Marksman",
        "Pack Rathound",
        "Disassemble",
        "Expanded Psi Capacitance",
        "Psi Empathy",
    ],
}

# Small ruleset for feats in the screenshots. Confidence is intentionally exposed
# because this is validation aid, not save-derived feat editing.
DEFAULT_FEAT_RULES: Dict[str, Dict[str, Any]] = {
    "Fast Metabolism": {"attributes": {"Constitution": 6}, "skills": {}, "confidence": "wiki"},
    "Marksman": {"attributes": {"Dexterity": 5}, "skills": {"Crossbows": 15}, "confidence": "wiki"},
    "Pack Rathound": {"attributes": {}, "skills": {}, "confidence": "wiki/no prerequisites"},
    "Versatility": {"attributes": {"Intelligence": 5}, "skills": {}, "confidence": "wiki"},
    "Disassemble": {"attributes": {"Intelligence": 7}, "skills": {}, "any_skill_groups": [{"skills": ["Electronics", "Mechanics"], "min": 20}], "confidence": "wiki"},
    "Expanded Psi Capacitance": {"attributes": {"Intelligence": 5}, "skills": {}, "any_skill_groups": [{"skills": ["Thought Control", "Psychokinesis", "Metathermics", "Temporal Manipulation"], "min": 25}], "other_feats": ["Psi Empathy"], "confidence": "wiki"},
    "Concussive Shots": {"attributes": {}, "skills": {"Crossbows": 30}, "confidence": "wiki"},
    "Hunter": {"attributes": {}, "skills": {}, "confidence": "wiki/special feat/no level-up prerequisites"},
    "Psi Empathy": {"attributes": {}, "skills": {}, "confidence": "no prerequisite known"},
}


def load_feat_rules() -> Dict[str, Dict[str, Any]]:
    if FEAT_RULES_PATH.is_file():
        with FEAT_RULES_PATH.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    return DEFAULT_FEAT_RULES


def load_feat_ids() -> Dict[str, str]:
    if FEAT_IDS_PATH.is_file():
        with FEAT_IDS_PATH.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    return {name: name.lower().replace(" ", "") for name in FEAT_RULES}


def load_tooltips() -> Dict[str, Dict[str, str]]:
    if TOOLTIPS_PATH.is_file():
        with TOOLTIPS_PATH.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    return {"attributes": {}, "skills": {}, "feats": {}}


FEAT_RULES = load_feat_rules()
FEAT_IDS = load_feat_ids()
TOOLTIPS = load_tooltips()
ID_TO_FEAT_NAME = {v: k for k, v in FEAT_IDS.items()}


def _target_dat(path: Path) -> Path:
    return path / "global.dat" if path.is_dir() else path


def _path_hint(path: Path) -> str:
    s = path.name.lower()
    parent = path.parent.name.lower()
    return f"{parent} {s}"


def detect_feats_for_path(path: Path) -> List[str]:
    hint = _path_hint(_target_dat(path))
    if "jetski" in hint:
        return list(SCREENSHOT_FEATS["jetski"])
    if "assault" in hint:
        return list(SCREENSHOT_FEATS["assault"])
    return []


@dataclass
class FeatRecord:
    offset: int
    length: int
    feat_id: str
    display_name: str


def unpack_dat(path: Path) -> Tuple[bytes, bytearray]:
    dat = _target_dat(path)
    blob = dat.read_bytes()
    if len(blob) <= 24 or blob[24:26] != b"\x1f\x8b":
        raise ValueError(f"Not a packed Underrail global.dat: {dat}")
    return blob[:24], bytearray(gzip.decompress(blob[24:]))


def pack_dat(header: bytes, payload: bytes) -> bytes:
    return header + gzip.compress(bytes(payload))


def find_feat_records_in_payload(payload: bytes) -> List[FeatRecord]:
    records: List[FeatRecord] = []
    seen = set()
    for display, feat_id in sorted(FEAT_IDS.items(), key=lambda kv: len(kv[1]), reverse=True):
        raw = feat_id.encode("ascii")
        start = 0
        while True:
            pos = payload.find(raw, start)
            if pos < 0:
                break
            # Feat dictionary entries look like:
            #   0a 0a 06 <record-id:int32> <len:byte> <feat-id-ascii> <terminator/ref...>
            # This avoids matching item/action strings such as "Disassemble Item".
            if pos >= 8 and payload[pos - 1] == len(raw) and payload[pos - 6] == 0x06 and payload[pos - 8:pos - 6] == b"\x0a\x0a":
                key = (pos, len(raw))
                if key not in seen:
                    records.append(FeatRecord(pos, len(raw), feat_id, display))
                    seen.add(key)
            start = pos + 1
    records.sort(key=lambda r: r.offset)
    return records


def read_feat_records(path: str | Path) -> List[Dict[str, Any]]:
    _, payload = unpack_dat(Path(path))
    return [r.__dict__ for r in find_feat_records_in_payload(payload)]


def apply_feat_replacements_to_dat(dat_path: Path, replacements: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    header, payload = unpack_dat(dat_path)
    changes = []
    for repl in sorted(replacements or [], key=lambda r: int(r["offset"]), reverse=True):
        offset = int(repl["offset"])
        old_id = str(repl["old_id"]).strip().lower().replace(" ", "")
        new_id = str(repl["new_id"]).strip().lower().replace(" ", "")
        if not new_id or not new_id.isascii() or not new_id.replace("_", "").isalnum():
            raise ValueError(f"Bad feat id '{new_id}'. Use ascii letters/numbers/underscore only.")
        old_raw = old_id.encode("ascii")
        new_raw = new_id.encode("ascii")
        if len(new_raw) > 255:
            raise ValueError("Feat id is too long for the one-byte string length field.")
        if payload[offset:offset + len(old_raw)] != old_raw or payload[offset - 1] != len(old_raw):
            raise ValueError(f"Feat record mismatch at offset {offset}; refusing to guess.")
        payload[offset - 1] = len(new_raw)
        payload[offset:offset + len(old_raw)] = new_raw
        changes.append({"offset": offset, "old_id": old_id, "new_id": new_id})
    dat_path.write_bytes(pack_dat(header, payload))
    return list(reversed(changes))


def display_names_from_feat_records(records: List[Dict[str, Any]]) -> List[str]:
    out = []
    for rec in records:
        out.append(rec.get("display_name") or ID_TO_FEAT_NAME.get(rec.get("feat_id", ""), rec.get("feat_id", "")))
    return out


def infer_level_for_path(path: Path) -> Optional[int]:
    hint = _path_hint(_target_dat(path))
    if "jetski" in hint:
        return 12
    if "assault" in hint:
        return 6
    return None


def inferred_attribute_budget(level: Optional[int]) -> Optional[int]:
    # Underrail grants one base ability point at levels 4, 8, 12, ...
    return None if not level else 40 + (int(level) // 4)


def inferred_skill_budget(level: Optional[int]) -> Optional[int]:
    # Screenshots verify level 6 => 320 spent/0 remaining and level 12 => 520
    # spent/40 remaining, matching 120 initial + 40 per later level.
    return None if not level else 120 + 40 * (int(level) - 1)


def analyze_target(path: str | Path, level: Optional[int] = None) -> Dict[str, Any]:
    path = Path(path)
    sv = Save(path)
    attrs = {}
    for name in ATTRS:
        base, modified = sv.get_attr(name)
        attrs[name] = {"base": base, "modified": modified, "bonus": modified - base}
    skills = {}
    for name in SKILLS:
        allocated, effective = sv.get_skill(name)
        skills[name] = {"allocated": allocated, "effective": effective, "bonus": effective - allocated}
    inferred_level = level or infer_level_for_path(path)
    attr_total = sum(v["base"] for v in attrs.values())
    skill_total = sum(v["allocated"] for v in skills.values())
    attr_budget = inferred_attribute_budget(inferred_level) or attr_total
    skill_budget = inferred_skill_budget(inferred_level) or skill_total
    feat_records = read_feat_records(sv.path)
    detected_feats = display_names_from_feat_records(feat_records) or detect_feats_for_path(path)
    return {
        "path": str(sv.path),
        "save_folder": str(sv.path.parent),
        "inferred_level": inferred_level,
        "attributes": attrs,
        "skills": skills,
        "totals": {
            "attribute_base": attr_total,
            "skill_allocated": skill_total,
        },
        "budgets": {
            "attribute_budget": attr_budget,
            "attribute_remaining": attr_budget - attr_total,
            "skill_budget": skill_budget,
            "skill_remaining": skill_budget - skill_total,
        },
        "detected_feats": detected_feats,
        "feat_records": feat_records,
        "all_known_feats": sorted(FEAT_RULES),
        "all_feat_ids": FEAT_IDS,
        "tooltips": TOOLTIPS,
        "notes": [
            "The save stores current allocated attributes/skills here, but unspent attribute/skill point offsets are not mapped.",
            "This UI preserves the loaded totals by default. If the character has unused points, enter a higher target budget to spend them without editing the unspent counters.",
            "Feat list is not read from the save; screenshot-known feats are preselected for provided reference saves and can be adjusted manually.",
        ],
    }


def _issue(kind: str, message: str, severity: str = "error", **extra: Any) -> Dict[str, Any]:
    out = {"type": kind, "severity": severity, "message": message}
    out.update(extra)
    return out


def _coerce_int_map(values: Dict[str, Any], valid_names: Iterable[str], label: str) -> Tuple[Dict[str, int], List[Dict[str, Any]]]:
    valid = set(valid_names)
    out: Dict[str, int] = {}
    issues = []
    for name, value in values.items():
        if name not in valid:
            issues.append(_issue("unknown_field", f"Unknown {label}: {name}"))
            continue
        try:
            out[name] = int(value)
        except (TypeError, ValueError):
            issues.append(_issue("bad_value", f"{label} {name} must be an integer."))
    return out, issues


def validate_respec(
    current: Dict[str, Any],
    proposed_attrs: Dict[str, Any],
    proposed_skills: Dict[str, Any],
    feats: Iterable[str],
    level: Optional[int] = None,
    attr_budget: Optional[int] = None,
    skill_budget: Optional[int] = None,
    allow_budget_increase: bool = False,
    ignore_budget: bool = False,
) -> Dict[str, Any]:
    attrs, attr_issues = _coerce_int_map(proposed_attrs, ATTRS, "attribute")
    skills, skill_issues = _coerce_int_map(proposed_skills, SKILLS, "skill")
    issues = attr_issues + skill_issues

    for name in ATTRS:
        attrs.setdefault(name, int(current["attributes"][name]["base"]))
    for name in SKILLS:
        skills.setdefault(name, int(current["skills"][name]["allocated"]))

    current_attr_total = int(current["totals"]["attribute_base"])
    current_skill_total = int(current["totals"]["skill_allocated"])
    target_attr_budget = current_attr_total if attr_budget is None else int(attr_budget)
    target_skill_budget = current_skill_total if skill_budget is None else int(skill_budget)
    attr_total = sum(attrs.values())
    skill_total = sum(skills.values())

    if not ignore_budget and target_attr_budget < current_attr_total and not allow_budget_increase:
        issues.append(_issue("attribute_budget", f"Target attribute budget {target_attr_budget} is below loaded total {current_attr_total}."))
    if not ignore_budget and target_skill_budget < current_skill_total and not allow_budget_increase:
        issues.append(_issue("skill_budget", f"Target skill budget {target_skill_budget} is below loaded total {current_skill_total}."))

    if not ignore_budget and attr_total > target_attr_budget:
        remaining = target_attr_budget - attr_total
        issues.append(_issue("attribute_budget", f"Attribute total is {attr_total}; target budget is {target_attr_budget}; over budget by {-remaining}."))
    if not ignore_budget and skill_total > target_skill_budget:
        remaining = target_skill_budget - skill_total
        issues.append(_issue("skill_budget", f"Skill total is {skill_total}; target budget is {target_skill_budget}; over budget by {-remaining}."))

    for name, value in attrs.items():
        if value < 1 or value > 20:
            issues.append(_issue("attribute_range", f"{name}={value} is outside the safe 1..20 range."))

    if level is not None:
        cap = 5 * int(level) + 10
        for name, value in skills.items():
            if value < 0:
                issues.append(_issue("skill_range", f"{name}={value} is below 0."))
            elif value > cap:
                issues.append(_issue("skill_cap", f"{name}={value} exceeds the level {level} cap {cap}.", skill=name, cap=cap))
    else:
        for name, value in skills.items():
            if value < 0 or value > 400:
                issues.append(_issue("skill_range", f"{name}={value} is outside the broad safe 0..400 range."))

    feat_reports = []
    selected_feats = set(feats or [])
    for feat in selected_feats:
        rule = FEAT_RULES.get(feat)
        if not rule:
            issues.append(_issue("unknown_feat", f"No prerequisite rule is known for feat '{feat}'.", "warning", feat=feat))
            feat_reports.append({"name": feat, "status": "unknown", "problems": ["No rule known"]})
            continue
        problems = []
        for attr, req in rule.get("attributes", {}).items():
            actual = attrs.get(attr, 0)
            if actual < req:
                problems.append(f"requires {attr} >= {req}; proposed {actual}")
        for skill, req in rule.get("skills", {}).items():
            actual = skills.get(skill, 0)
            if actual < req:
                problems.append(f"requires {skill} >= {req}; proposed {actual}")
        for group in rule.get("any_skill_groups", []):
            names = group.get("skills", [])
            req = int(group.get("min", 0))
            best = max((skills.get(name, 0) for name in names), default=0)
            if best < req:
                problems.append(f"requires one of {', '.join(names)} >= {req}; best proposed {best}")
        for required_feat in rule.get("other_feats", []):
            if required_feat not in selected_feats:
                problems.append(f"requires feat {required_feat} to remain selected")
        if rule.get("level_min") is not None and level is not None and int(level) < int(rule["level_min"]):
            problems.append(f"requires level >= {rule['level_min']}; proposed level {level}")
        if problems:
            for p in problems:
                issues.append(_issue("feat_prerequisite", f"{feat}: {p}", feat=feat))
            status = "broken"
        else:
            status = "ok"
        feat_reports.append({"name": feat, "status": status, "confidence": rule.get("confidence", "unknown"), "problems": problems})

    hard_errors = [i for i in issues if i.get("severity") != "warning"]
    return {
        "valid": not hard_errors,
        "issues": issues,
        "feat_reports": feat_reports,
        "totals": {
            "current_attribute_base": current_attr_total,
            "proposed_attribute_base": attr_total,
            "target_attribute_budget": target_attr_budget,
            "attribute_remaining": target_attr_budget - attr_total,
            "current_skill_allocated": current_skill_total,
            "proposed_skill_allocated": skill_total,
            "target_skill_budget": target_skill_budget,
            "skill_remaining": target_skill_budget - skill_total,
        },
    }


def create_respec_copy(
    source_folder: str | Path,
    new_name: str,
    attrs: Optional[Dict[str, Any]] = None,
    skills: Optional[Dict[str, Any]] = None,
    level: Optional[int] = None,
    feats: Optional[List[str]] = None,
    attr_budget: Optional[int] = None,
    skill_budget: Optional[int] = None,
    allow_invalid: bool = False,
    ignore_budget: bool = False,
    feat_replacements: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    source_folder = Path(source_folder)
    if not source_folder.is_dir():
        raise ValueError(f"Source must be a save folder, got {source_folder}")
    if not (source_folder / "global.dat").is_file():
        raise ValueError(f"Source save folder has no global.dat: {source_folder}")
    if any(ch in new_name for ch in "\\/:*?\"<>|") or not new_name.strip():
        raise ValueError("New save name contains invalid path characters.")

    current = analyze_target(source_folder)
    proposed_attrs = {k: v["base"] for k, v in current["attributes"].items()}
    proposed_skills = {k: v["allocated"] for k, v in current["skills"].items()}
    proposed_attrs.update(attrs or {})
    proposed_skills.update(skills or {})
    validation = validate_respec(current, proposed_attrs, proposed_skills, feats or [], level, attr_budget, skill_budget, ignore_budget=ignore_budget)
    if not validation["valid"] and not allow_invalid:
        raise ValueError("Validation failed: " + "; ".join(i["message"] for i in validation["issues"] if i.get("severity") != "warning"))

    destination = source_folder.parent / new_name
    if destination.exists():
        raise ValueError(f"Destination already exists: {destination}")
    shutil.copytree(source_folder, destination)

    sv = Save(destination)
    for name, value in (attrs or {}).items():
        sv.set_attr(name, int(value))
    for name, value in (skills or {}).items():
        sv.set_skill(name, int(value), level=level)
    backup = sv.write()
    feat_changes = apply_feat_replacements_to_dat(destination / "global.dat", feat_replacements or [])
    return {
        "destination": str(destination),
        "global_dat": str(destination / "global.dat"),
        "backup": str(backup),
        "backup_created": Path(backup).is_file(),
        "feat_changes": feat_changes,
        "validation": validation,
        "after": analyze_target(destination),
    }


def save_folder_mtime(folder: Path) -> float:
    """Return a useful save-folder modified time.

    Windows folder mtimes can be stale for copied saves, so prefer the newest
    top-level file in the save folder and fall back to the folder mtime.
    """
    newest = folder.stat().st_mtime
    for item in folder.iterdir():
        try:
            if item.is_file():
                newest = max(newest, item.stat().st_mtime)
        except OSError:
            continue
    return newest


def list_save_folders(root: str | Path = DEFAULT_SAVES_DIR, sort: str = "alpha") -> List[Dict[str, Any]]:
    root = Path(root)
    if not root.is_dir():
        return []
    out = []
    for child in root.iterdir():
        if child.is_dir() and (child / "global.dat").is_file():
            mtime = save_folder_mtime(child)
            out.append({
                "name": child.name,
                "path": str(child),
                "modified_ts": mtime,
                "modified": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"),
            })
    if sort in {"modified", "modified_desc", "mtime"}:
        out.sort(key=lambda x: (-x["modified_ts"], x["name"].lower()))
    elif sort in {"modified_asc", "oldest"}:
        out.sort(key=lambda x: (x["modified_ts"], x["name"].lower()))
    else:
        out.sort(key=lambda x: x["name"].lower())
    return out


INDEX_HTML = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Underrail Visual Respec Editor</title>
<style>
:root{--bg:#080706;--panel:#141211;--panel2:#201d22;--orange:#c66a00;--orange2:#ff9a1f;--text:#f2a13a;--muted:#a76b2c;--bad:#ff5252;--ok:#78d36a;--warn:#ffd166;}
*{box-sizing:border-box} body{margin:0;background:radial-gradient(circle at 30% 0,#1d1710,#070605 55%);color:var(--text);font:15px/1.35 system-ui,Segoe UI,Arial,sans-serif} button,input,select{font:inherit} .app{max-width:1360px;margin:0 auto;padding:16px}.title{border:2px solid var(--orange);border-radius:8px;padding:14px 18px;background:#0d0b0a;box-shadow:0 0 18px #000 inset}.grid{display:grid;grid-template-columns:360px 1fr;gap:14px;margin-top:14px}.panel{border:2px solid var(--orange);border-radius:8px;background:linear-gradient(#18151a,#0d0c0c);padding:14px;box-shadow:0 0 0 2px #000 inset}.tabs{display:flex;gap:8px;margin-bottom:12px}.tab{border:2px solid var(--orange);background:#160f09;color:var(--text);padding:8px 16px;border-radius:6px;cursor:pointer}.tab.active{background:#b76100;color:#fff}.row{display:flex;align-items:center;gap:8px;margin:6px 0}.row label{min-width:92px;color:#ffc072}.path{width:100%;background:#080808;color:#eee;border:1px solid var(--orange);border-radius:4px;padding:7px}.btn{background:#b76100;color:#fff;border:1px solid #ffb04a;border-radius:5px;padding:7px 10px;cursor:pointer}.btn:disabled{opacity:.45;cursor:not-allowed}.sectionTitle{color:#ffbd69;margin:10px 0 6px;font-weight:700}.statGrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(255px,1fr));gap:8px}.stat{display:grid;grid-template-columns:1fr 34px 54px 34px 54px;align-items:center;gap:6px;border:1px solid #8a4a00;border-radius:7px;background:#25222a;padding:7px}.stat.changed{outline:2px solid var(--orange2)}.stat .name{color:#ffbe70;font-weight:650}.stat button{height:30px;background:#2b1705;color:#ffbb68;border:1px solid var(--orange);border-radius:4px;cursor:pointer}.stat input{width:54px;text-align:center;background:#080808;color:#fff;border:1px solid #9f5b10;border-radius:4px;padding:5px}.eff{color:#9ad3ff;font-size:12px;text-align:right}.meter{display:flex;justify-content:space-between;border:1px solid #7b4300;background:#0b0b0b;border-radius:6px;padding:8px;margin:8px 0}.good{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}.featBox{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:5px;max-height:220px;overflow:auto}.feat{border:1px solid #684100;border-radius:5px;padding:6px;background:#111}.issues{max-height:230px;overflow:auto}.issue{border-left:4px solid var(--bad);padding:5px 8px;margin:4px 0;background:#1d0e0e}.issue.warning{border-color:var(--warn);background:#211b0d}.small{font-size:12px;color:#c08b55}.footer{margin-top:10px;color:#b57d3d}.skillColumns{columns:2 280px;column-gap:12px}.skillColumns .stat{break-inside:avoid;margin-bottom:8px}.pill{display:inline-block;border:1px solid var(--orange);border-radius:999px;padding:2px 8px;margin-left:5px;color:#ffd199}.hidden{display:none}.toast{white-space:pre-wrap;background:#050505;color:#eee;border:1px solid #555;border-radius:6px;padding:10px;margin-top:10px;max-height:220px;overflow:auto}
</style>
</head>
<body><div class="app">
  <div class="title"><h1>Underrail Visual Respec Editor</h1><div class="small">Local-only UI around the verified global.dat attribute/skill editor. Clone-first; source saves are not modified.</div></div>
  <div class="grid">
    <div class="panel">
      <div class="sectionTitle">1. Load save</div>
      <div class="row"><label>Save path</label><input id="path" class="path" placeholder="C:\\Users\\<USER>\\Documents\\My Games\\Underrail\\Saves\\SaveName or global.dat"></div>
      <div class="row"><button class="btn" onclick="loadSave()">Load values</button><button class="btn" onclick="listSaves()">List saves</button></div>
      <div class="row"><label>Sort saves</label><select id="saveSort" class="path" onchange="listSaves()"><option value="modified">Newest first</option><option value="alpha">A → Z</option><option value="modified_asc">Oldest first</option></select></div>
      <select id="saveList" class="path hidden" onchange="document.getElementById('path').value=this.value"></select>
      <div class="row"><label>Level</label><input id="level" class="path" type="number" value="12" min="1" max="50"></div>
      <div class="sectionTitle">2. Budgets / unused points</div>
      <div class="small">Loaded total is the safest default. If this character has unused points and you want to spend them, increase the target budget manually; the app does not edit unknown unspent-point counters.</div>
      <div class="row"><label>Attr budget</label><input id="attrBudget" class="path" type="number"></div>
      <div class="row"><label>Skill budget</label><input id="skillBudget" class="path" type="number"></div>
      <label class="feat" title="Only skips overspending/remaining-point budget checks; prerequisites and safe ranges still apply."><input id="cheatBudget" type="checkbox" onchange="renderAll()"> Ignore point budget</label>
      <div id="budgetSummary"></div>
      <div class="sectionTitle">3. Feats to edit/protect</div>
      <div class="small">Loaded feat records are editable below. The app uses the community NUL/SOH string-replacement method on the cloned save only. Use raw ids if a feat is not in the dropdown.</div>
      <div id="featEditor"></div>
      <div class="small">Checked feats are used for prerequisite validation:</div>
      <div id="feats" class="featBox"></div>
      <div class="sectionTitle">4. Create cloned save</div>
      <div class="row"><label>New name</label><input id="newName" class="path" placeholder="JetSki-Respec"></div>
      <div class="row"><button id="writeBtn" class="btn" onclick="createRespec()" disabled>Create cloned respec save</button></div>
      <div id="toast" class="toast hidden"></div>
    </div>
    <div class="panel">
      <div class="tabs"><button id="tabAttr" class="tab active" onclick="showTab('attr')">Base</button><button id="tabSkills" class="tab" onclick="showTab('skills')">Skills</button><button id="tabReview" class="tab" onclick="showTab('review')">Validation</button></div>
      <div id="viewAttr"><div class="meter"><b>Attributes</b><span id="attrMeter"></span></div><div id="attrs" class="statGrid"></div></div>
      <div id="viewSkills" class="hidden"><div class="meter"><b>Skills</b><span id="skillMeter"></span></div><div id="skills" class="skillColumns"></div></div>
      <div id="viewReview" class="hidden"><div class="sectionTitle">Validation</div><div id="validation"></div><div class="sectionTitle">Patch preview</div><div id="preview" class="small"></div></div>
    </div>
  </div>
  <div class="footer">Tip: plus/minus preserves gear/synergy deltas by writing base/allocated and shifted modified/effective values, matching the verified CLI behavior.</div>
</div>
<script>
let state=null, proposedAttrs={}, proposedSkills={};
const ATTRS = ["Strength","Dexterity","Agility","Constitution","Perception","Will","Intelligence"];
const SKILLS = ["Guns","Heavy Guns","Throwing","Crossbows","Melee","Dodge","Evasion","Stealth","Hacking","Lockpicking","Pickpocketing","Traps","Mechanics","Electronics","Chemistry","Biology","Tailoring","Thought Control","Psychokinesis","Metathermics","Temporal Manipulation","Persuasion","Intimidation","Mercantile"];
async function api(path, body=null){const r=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined}); const j=await r.json(); if(!r.ok||j.error) throw new Error(j.error||r.statusText); return j;}
function toast(x){const el=document.getElementById('toast');el.textContent=typeof x==='string'?x:JSON.stringify(x,null,2);el.classList.remove('hidden')}
async function listSaves(){try{const sort=document.getElementById('saveSort')?.value||'modified';const j=await api('/api/list-saves?sort='+encodeURIComponent(sort));const sel=document.getElementById('saveList');sel.innerHTML='<option value="">Choose detected save...</option>'+j.saves.map(s=>`<option value="${esc(s.path)}">${esc(s.name)} — ${esc(s.modified||'')}</option>`).join('');sel.classList.remove('hidden');toast('Listed '+j.saves.length+' saves sorted by '+(sort==='alpha'?'name':sort==='modified_asc'?'oldest modified':'newest modified'));}catch(e){toast(e.message)}}
async function loadSave(){try{state=await api('/api/analyze',{path:document.getElementById('path').value,level:parseInt(document.getElementById('level').value||'0',10)||null}); proposedAttrs={}; proposedSkills={}; for(const a of ATTRS) proposedAttrs[a]=state.attributes[a].base; for(const s of SKILLS) proposedSkills[s]=state.skills[s].allocated; if(state.inferred_level) document.getElementById('level').value=state.inferred_level; document.getElementById('attrBudget').value=state.budgets.attribute_budget; document.getElementById('skillBudget').value=state.budgets.skill_budget; if(!document.getElementById('newName').value){const folder=state.save_folder.split(/[\\/]/).pop(); document.getElementById('newName').value=folder+'-Respec'} renderAll(); toast('Loaded '+state.path+'\nRemaining from loaded/inferred budget: attributes '+state.budgets.attribute_remaining+', skills '+state.budgets.skill_remaining+'\nScreenshot-known feats preselected when available.')}catch(e){toast(e.message)}}
function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function tip(kind,name){return ((state&&state.tooltips&&state.tooltips[kind]&&state.tooltips[kind][name])||'')}
function statRow(kind,name,current,bonus){const value=(kind==='attr'?proposedAttrs:proposedSkills)[name]; const changed=value!==current; const tk=kind==='attr'?'attributes':'skills'; return `<div class="stat ${changed?'changed':''}" title="${esc(tip(tk,name))}"><div class="name">${esc(name)}</div><button onclick="bump('${kind}','${esc(name)}',-1)">−</button><input type="number" value="${value}" onchange="setVal('${kind}','${esc(name)}',this.value)"><button onclick="bump('${kind}','${esc(name)}',1)">+</button><div class="eff">${bonus?`eff ${value+bonus}`:''}</div></div>`}
function bump(kind,name,d){setVal(kind,name,(kind==='attr'?proposedAttrs:proposedSkills)[name]+d)}
function setVal(kind,name,v){v=parseInt(v,10); if(Number.isNaN(v)) return; if(kind==='attr') proposedAttrs[name]=Math.max(1,v); else proposedSkills[name]=Math.max(0,v); renderAll();}
function selectedFeats(){return Array.from(document.querySelectorAll('.feat-validate:checked')).map(x=>x.value)}
function featDisplayForId(id){const pairs=Object.entries(state.all_feat_ids||{}); const hit=pairs.find(([name,val])=>val===id); return hit?hit[0]:id}
function renderFeatEditor(){const opts=Object.entries(state.all_feat_ids||{}).sort((a,b)=>a[0].localeCompare(b[0])).map(([name,id])=>`<option value="${esc(id)}" title="${esc(tip('feats',name))}">${esc(name)} (${esc(id)})</option>`).join(''); document.getElementById('featEditor').innerHTML=(state.feat_records||[]).map((r,i)=>`<div class="row" title="${esc(tip('feats',r.display_name||''))}"><label>${esc(r.display_name||r.feat_id)}</label><select class="path featNew" data-offset="${r.offset}" data-old="${esc(r.feat_id)}" onchange="syncFeatRaw(${i});renderAll()"><option value="${esc(r.feat_id)}">keep: ${esc(r.feat_id)}</option>${opts}</select></div><div class="row"><label>raw id</label><input class="path featRaw" value="${esc(r.feat_id)}" data-offset="${r.offset}" data-old="${esc(r.feat_id)}" oninput="renderAll()"></div>`).join('')||'<div class="small warn">No editable feat records detected from known feat ids.</div>'}
function syncFeatRaw(i){const sel=document.querySelectorAll('.featNew')[i]; const raw=document.querySelectorAll('.featRaw')[i]; if(sel&&raw) raw.value=sel.value}
function featReplacements(){return Array.from(document.querySelectorAll('.featRaw')).map(x=>({offset:parseInt(x.dataset.offset,10),old_id:x.dataset.old,new_id:x.value.trim().toLowerCase().replace(/\s+/g,'')})).filter(x=>x.new_id&&x.new_id!==x.old_id)}
function proposedFeatNames(){const current=(state.feat_records||[]).map(r=>r.display_name||r.feat_id); for(const r of featReplacements()){const idx=(state.feat_records||[]).findIndex(fr=>fr.offset===r.offset); if(idx>=0) current[idx]=featDisplayForId(r.new_id)} return current}
function renderFeats(){const existing=Array.from(document.querySelectorAll('.feat-validate')); const all=Array.from(new Set([...(state.all_known_feats||[]),...proposedFeatNames()])); const selected=new Set(existing.length?existing.filter(x=>x.checked).map(x=>x.value):(proposedFeatNames().length?proposedFeatNames():(state.detected_feats||[]))); document.getElementById('feats').innerHTML=all.map(f=>`<label class="feat" title="${esc(tip('feats',f))}"><input class="feat-validate" type="checkbox" value="${esc(f)}" ${selected.has(f)?'checked':''} onchange="renderAll()"> ${esc(f)}</label>`).join('')}
function totals(){const at=Object.values(proposedAttrs).reduce((a,b)=>a+b,0), st=Object.values(proposedSkills).reduce((a,b)=>a+b,0); const ab=parseInt(document.getElementById('attrBudget').value||state.totals.attribute_base,10), sb=parseInt(document.getElementById('skillBudget').value||state.totals.skill_allocated,10); return {at,st,ab,sb}}
function renderAll(){if(!state)return; document.getElementById('attrs').innerHTML=ATTRS.map(a=>statRow('attr',a,state.attributes[a].base,state.attributes[a].bonus)).join(''); document.getElementById('skills').innerHTML=SKILLS.map(s=>statRow('skill',s,state.skills[s].allocated,state.skills[s].bonus)).join(''); if(!document.getElementById('featEditor').children.length) renderFeatEditor(); renderFeats(); validate();}
async function validate(){if(!state)return; const t=totals(); const cheat=document.getElementById('cheatBudget').checked; document.getElementById('attrMeter').innerHTML=`<span class="${cheat||t.ab-t.at>=0?'good':'bad'}">${t.at}/${t.ab} remaining ${t.ab-t.at}${cheat?' (ignored)':''}</span>`; document.getElementById('skillMeter').innerHTML=`<span class="${cheat||t.sb-t.st>=0?'good':'bad'}">${t.st}/${t.sb} remaining ${t.sb-t.st}${cheat?' (ignored)':''}</span>`; document.getElementById('budgetSummary').innerHTML=`<div class="meter"><span>Attr remaining</span><b class="${cheat||t.ab-t.at>=0?'good':'bad'}">${t.ab-t.at}${cheat?' ignored':''}</b></div><div class="meter"><span>Skill remaining</span><b class="${cheat||t.sb-t.st>=0?'good':'bad'}">${t.sb-t.st}${cheat?' ignored':''}</b></div>`; try{const j=await api('/api/validate',{current:state,attributes:proposedAttrs,skills:proposedSkills,feats:selectedFeats(),level:parseInt(document.getElementById('level').value||'0',10)||null,attr_budget:t.ab,skill_budget:t.sb,ignore_budget:cheat}); renderValidation(j); document.getElementById('writeBtn').disabled=!j.valid;}catch(e){document.getElementById('validation').textContent=e.message;document.getElementById('writeBtn').disabled=true}}
function renderValidation(j){let html=`<div class="${j.valid?'good':'bad'}"><b>${j.valid?'Valid':'Blocked'}</b></div>`; html+='<div class="issues">'+(j.issues.length?j.issues.map(i=>`<div class="issue ${i.severity==='warning'?'warning':''}">${esc(i.message)}</div>`).join(''):'<div class="good">No blocking issues.</div>')+'</div>'; html+='<div class="sectionTitle">Feat report</div>'+j.feat_reports.map(f=>`<div class="${f.status==='ok'?'good':f.status==='broken'?'bad':'warn'}">${esc(f.name)}: ${esc(f.status)} <span class="small">${esc(f.confidence||'')}</span></div>`).join(''); document.getElementById('validation').innerHTML=html; document.getElementById('preview').innerHTML=`Changed attributes: ${diffs(proposedAttrs,state.attributes,'base').join(', ')||'none'}<br>Changed skills: ${diffs(proposedSkills,state.skills,'allocated').join(', ')||'none'}`}
function diffs(prop,cur,key){return Object.keys(prop).filter(k=>prop[k]!==cur[k][key]).map(k=>`${esc(k)} ${cur[k][key]}→${prop[k]}`)}
async function createRespec(){try{const t=totals(); const changedAttrs={}; for(const k of ATTRS) if(proposedAttrs[k]!==state.attributes[k].base) changedAttrs[k]=proposedAttrs[k]; const changedSkills={}; for(const k of SKILLS) if(proposedSkills[k]!==state.skills[k].allocated) changedSkills[k]=proposedSkills[k]; const j=await api('/api/create-respec',{source_folder:state.save_folder,new_name:document.getElementById('newName').value,attributes:changedAttrs,skills:changedSkills,feats:selectedFeats(),feat_replacements:featReplacements(),level:parseInt(document.getElementById('level').value||'0',10)||null,attr_budget:t.ab,skill_budget:t.sb,ignore_budget:document.getElementById('cheatBudget').checked}); toast('Created cloned save:\n'+j.destination+'\n\nBackup inside clone:\n'+j.backup+'\n\nFeat changes: '+JSON.stringify(j.feat_changes))}catch(e){toast(e.message)}}
function showTab(which){for(const x of ['Attr','Skills','Review']){document.getElementById('view'+x).classList.add('hidden');document.getElementById('tab'+x).classList.remove('active')} const map={attr:'Attr',skills:'Skills',review:'Review'}; document.getElementById('view'+map[which]).classList.remove('hidden');document.getElementById('tab'+map[which]).classList.add('active')}
document.getElementById('attrBudget').addEventListener('input',renderAll);document.getElementById('skillBudget').addEventListener('input',renderAll);document.getElementById('level').addEventListener('input',renderAll);
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: Any, content_type: str = "application/json") -> None:
        if isinstance(body, (dict, list)):
            raw = json.dumps(body, indent=2).encode("utf-8")
        elif isinstance(body, str):
            raw = body.encode("utf-8")
        else:
            raw = bytes(body)
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            if path == "/" or path == "/index.html":
                self._send(200, INDEX_HTML, "text/html")
            elif path == "/api/list-saves":
                sort = (query.get("sort") or ["alpha"])[0]
                self._send(200, {"saves": list_save_folders(sort=sort), "sort": sort})
            elif path == "/api/health":
                self._send(200, {"ok": True})
            else:
                self._send(404, {"error": "Not found"})
        except Exception as exc:  # pragma: no cover - server safety net
            self._send(500, {"error": str(exc), "trace": traceback.format_exc()})

    def do_POST(self) -> None:  # noqa: N802
        try:
            path = urlparse(self.path).path
            body = self._json_body()
            if path == "/api/analyze":
                self._send(200, analyze_target(body.get("path", ""), body.get("level")))
            elif path == "/api/validate":
                self._send(200, validate_respec(
                    body["current"], body.get("attributes", {}), body.get("skills", {}), body.get("feats", []),
                    body.get("level"), body.get("attr_budget"), body.get("skill_budget"), ignore_budget=bool(body.get("ignore_budget", False)),
                ))
            elif path == "/api/create-respec":
                self._send(200, create_respec_copy(
                    body["source_folder"], body["new_name"], body.get("attributes", {}), body.get("skills", {}),
                    body.get("level"), body.get("feats", []), body.get("attr_budget"), body.get("skill_budget"),
                    bool(body.get("allow_invalid", False)), bool(body.get("ignore_budget", False)), body.get("feat_replacements", []),
                ))
            else:
                self._send(404, {"error": "Not found"})
        except SystemExit as exc:
            self._send(400, {"error": str(exc)})
        except Exception as exc:
            self._send(400, {"error": str(exc)})

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[underrail-webapp] " + fmt % args + "\n")


def main(argv: Optional[List[str]] = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    port = int(argv[0]) if argv else DEFAULT_PORT
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Underrail Visual Respec Editor running at http://127.0.0.1:{port}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    main()
