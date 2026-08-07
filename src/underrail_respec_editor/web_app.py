r"""
Local visual Underrail respec web app.

Run:
    python -m underrail_respec_editor.web_app

Open:
    http://127.0.0.1:8765

Safety model:
    * reads either a save folder or a global.dat
    * writes only to a newly cloned save folder via /api/create-respec
    * never edits the source save folder in place
    * validates point neutrality, legal caps, and known feat prerequisites

This app intentionally edits only the 7 attributes and 24 skills already verified
by save_tool.py. Feats and unspent-point storage are not modified.
"""

from __future__ import annotations
import gzip
import json
import mimetypes
import os
import shutil
import struct
import sys
import threading
import time
import traceback
import webbrowser
from datetime import datetime

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .save_tool import ATTRS, SKILLS, Save
from . import inventory_tool, runtime_mods

DEFAULT_PORT = 8765
DEFAULT_SAVES_DIR = Path.home() / "Documents" / "My Games" / "Underrail" / "Saves"
PACKAGE_ROOT = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_ROOT / "data"
FEAT_IDS_PATH = DATA_DIR / "feat_ids.json"
FEAT_RULES_PATH = DATA_DIR / "feat_rules.json"
TOOLTIPS_PATH = DATA_DIR / "wiki_tooltips.json"
COMMUNITY_MODS_PATH = DATA_DIR / "community_mods.json"
GAME_RULES_PATH = DATA_DIR / "game_rules.json"
STATIC_PREFIX = "/_next/"


def bundled_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", PACKAGE_ROOT))


def frontend_out_dir() -> Optional[Path]:
    env_dir = os.environ.get("UNDERAIL_RESPEC_FRONTEND_DIR")
    candidates = []
    if env_dir:
        candidates.append(Path(env_dir))
    candidates.extend([
        bundled_root() / "underrail_respec_editor" / "frontend" / "out",
        PACKAGE_ROOT / "frontend" / "out",
        PACKAGE_ROOT.parents[1] / "frontend" / "out",
    ])
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return None


def static_file_for_url(path: str) -> Optional[Path]:
    root = frontend_out_dir()
    if root is None:
        return None
    rel = path.lstrip("/") or "index.html"
    if rel.endswith("/"):
        rel += "index.html"
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    if candidate.is_file():
        return candidate
    html_fallback = candidate.with_suffix(".html")
    if html_fallback.is_file():
        return html_fallback
    return None

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


def load_community_mods() -> Dict[str, Any]:
    if COMMUNITY_MODS_PATH.is_file():
        with COMMUNITY_MODS_PATH.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    return {"source": {}, "mods": [], "design_implications": []}


def load_game_rules() -> Dict[str, Any]:
    if GAME_RULES_PATH.is_file():
        with GAME_RULES_PATH.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    return {"source_references": {}, "leveling": {}, "skills": {}, "derived_stats": {}}


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def base_ability_modifier(effective_attribute: int) -> float:
    attribute = int(effective_attribute)
    step = 0.085 if attribute > 4 else 0.1
    return _f32(1 + (attribute - 4) * step)


def skill_cap_for_level(level: Optional[int]) -> Optional[int]:
    return None if level is None else 10 + 5 * int(level)


def _related_attribute_value(skill_name: str, attributes: Dict[str, int]) -> int:
    rule = GAME_RULES.get("skills", {}).get(skill_name, {})
    related = rule.get("related_attribute")
    if related == "max(Strength, Dexterity)":
        return max(int(attributes.get("Strength", 0)), int(attributes.get("Dexterity", 0)))
    if related == "max(Will, Strength)":
        return max(int(attributes.get("Will", 0)), int(attributes.get("Strength", 0)))
    if related:
        return int(attributes.get(related, 0))
    return 0


def preview_effective_skill(
    skill_name: str,
    allocated: int,
    attributes: Dict[str, int],
    level: Optional[int] = None,
    allocated_skills: Optional[Dict[str, int]] = None,
    flat_bonus: int = 0,
    multiplier_percent: int = 100,
) -> int:
    """Preview Underrail's effective-skill math from normalized rule metadata.

    This is an audit/helper path, not the writer's source of truth. The writer
    still preserves the loaded effective-minus-allocated delta unless a future
    fixture-backed rule engine proves every bonus source.
    """
    allocated_skills = allocated_skills or {}
    rule = GAME_RULES.get("skills", {}).get(skill_name)
    if not rule:
        raise KeyError(f"No game-rule entry for skill {skill_name!r}")
    modifier = base_ability_modifier(_related_attribute_value(skill_name, attributes))
    base_component = int(int(allocated) * modifier)
    synergies = 0
    for source_skill, percent in rule.get("synergies", {}).items():
        synergies += int(int(allocated_skills.get(source_skill, 0)) * int(percent) / 100)
    cap = skill_cap_for_level(level)
    if cap is not None:
        synergies = max(0, synergies - max(0, base_component + synergies - cap))
    effective = int((base_component + synergies + int(flat_bonus)) * int(multiplier_percent) / 100)
    return max(0, effective)



def _rounded_damage(parts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for part in parts:
        row = dict(part)
        if row.get("min") is not None:
            row["min"] = round(float(row["min"]), 1)
        if row.get("max") is not None:
            row["max"] = round(float(row["max"]), 1)
        out.append(row)
    return out


def psi_damage_estimates(skills: Dict[str, Dict[str, int]]) -> List[Dict[str, Any]]:
    tc = int(skills.get("Thought Control", {}).get("effective", 0))
    pk = int(skills.get("Psychokinesis", {}).get("effective", 0))
    mt = int(skills.get("Metathermics", {}).get("effective", 0))
    tm = int(skills.get("Temporal Manipulation", {}).get("effective", 0))
    return [
        {
            "name": "Neural Overload",
            "school": "Thought Control",
            "effective_skill": tc,
            "damage": _rounded_damage([{"type": "electrical/mental", "min": 10 + 0.2 * tc, "max": 11 + 0.4 * tc}]),
            "formula": "10-11 plus 0.2-0.4 per effective Thought Control; target Intelligence/Resolve and feats can further modify it.",
            "source": "Underrail Wiki: Neural Overload",
        },
        {
            "name": "Electrokinesis",
            "school": "Psychokinesis",
            "effective_skill": pk,
            "damage": _rounded_damage([{"type": "electrical", "min": 16 + 0.15 * pk, "max": 29 + 0.45 * pk}]),
            "formula": "16-29 plus 0.15-0.45 per effective Psychokinesis; jump damage drops by 20% of original per jump.",
            "source": "Underrail Wiki: Electrokinesis",
        },
        {
            "name": "Pyrokinesis",
            "school": "Metathermics",
            "effective_skill": mt,
            "damage": _rounded_damage([{"type": "heat", "min": 30 + 0.4 * mt, "max": 42 + 0.85 * mt}]),
            "formula": "30-42 plus 0.4-0.85 per effective Metathermics; AoE falloff/resistance not included.",
            "source": "Underrail Wiki: Pyrokinesis",
        },
        {
            "name": "Cryokinetic Orb shard",
            "school": "Metathermics",
            "effective_skill": mt,
            "damage": _rounded_damage([
                {"type": "cold", "min": 5 + 0.1 * mt, "max": 5 + 0.2 * mt},
                {"type": "mechanical", "min": 5 + 0.125 * mt, "max": 5 + 0.275 * mt},
            ]),
            "formula": "Per shard: cold 5 + 0.1-0.2/skill and mechanical 5 + 0.125-0.275/skill.",
            "source": "Underrail Wiki: Cryokinetic Orb",
        },
        {
            "name": "Thermodynamic Destabilization",
            "school": "Metathermics",
            "effective_skill": mt,
            "damage": [],
            "target_health_percent": min(100.0, round(30 + 0.5 * mt, 1)),
            "formula": "Explosion total equals 30% of afflicted target health + 0.5% per effective Metathermics, capped at 100%.",
            "source": "Underrail Wiki: Thermodynamic Destabilization",
        },
        {
            "name": "Temporal Distortion",
            "school": "Temporal Manipulation",
            "effective_skill": tm,
            "damage": _rounded_damage([
                {"type": "mechanical", "min": 5 + 0.05 * tm, "max": 6 + 0.1 * tm},
                {"type": "energy", "min": 5 + 0.05 * tm, "max": 6 + 0.1 * tm},
            ]),
            "formula": "Best-effort preview from listed 5-6 mechanical + 5-6 energy scaling with Temporal Manipulation; exact wiki per-skill table is not yet normalized.",
            "source": "Underrail Wiki: Temporal Distortion",
        },
    ]


def weapon_skill_scalars(skills: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, Any]]:
    rules = {
        "Guns": (0.7, "Base Damage * (1 + 0.7 * effective Guns / 100); light guns can use 0.5 instead."),
        "Heavy Guns": (0.7, "Best-effort same weapon-skill scalar family as Guns until heavy-gun-specific data is normalized."),
        "Crossbows": (0.7, "Base Damage * (1 + 0.7 * effective Crossbows / 100)."),
        "Melee": (0.7, "Best-effort melee skill scalar; strength, weapon type, feats, and special attacks can further modify damage."),
        "Throwing": (0.7, "Best-effort throwing-knife scalar; grenade damage is item-defined and not scaled this way."),
    }
    out: Dict[str, Dict[str, Any]] = {}
    for skill, (coef, formula) in rules.items():
        eff = int(skills.get(skill, {}).get("effective", 0))
        out[skill] = {
            "effective_skill": eff,
            "normal_weapon_damage_multiplier": round(1 + coef * eff / 100.0, 4),
            "formula": formula,
            "source": "Underrail Wiki skill pages / best-effort normalized preview",
        }
    return out


def _skill_for_equipped_weapon(item: Dict[str, Any]) -> Optional[str]:
    typ = (item.get("wiki_type") or "").lower()
    key = (item.get("datafile_key") or "").lower()
    name = (item.get("name") or "").lower()
    if "crossbow" in typ or "crossbow" in key or "crossbow" in name:
        return "Crossbows"
    if "melee" in typ or "knife" in key or "knife" in name:
        return "Melee"
    if "gun" in typ or "pistol" in typ or "rifle" in typ:
        return "Guns"
    return None


def equipped_weapon_damage_estimates(equipped: Dict[str, Any], skills: Dict[str, Dict[str, int]]) -> List[Dict[str, Any]]:
    scalars = weapon_skill_scalars(skills)
    rows = []
    for item in equipped.get("slots", []):
        if not item.get("slot", "").startswith("weapon_") or not item.get("equipped"):
            continue
        combat = item.get("combat") or {}
        base_damage = combat.get("damage") or []
        skill = _skill_for_equipped_weapon(item)
        if not base_damage or not skill:
            rows.append({"slot": item.get("slot"), "name": item.get("name"), "skill": skill, "base_damage": base_damage, "estimated_damage": [], "note": "No normalized base damage or skill mapping available yet."})
            continue
        mult = scalars[skill]["normal_weapon_damage_multiplier"]
        rows.append({
            "slot": item.get("slot"),
            "name": item.get("name"),
            "skill": skill,
            "effective_skill": scalars[skill]["effective_skill"],
            "multiplier": mult,
            "base_damage": base_damage,
            "estimated_damage": _rounded_damage([{**part, "min": float(part["min"]) * mult, "max": float(part["max"]) * mult} for part in base_damage]),
            "formula": scalars[skill]["formula"],
            "source": (combat.get("source") or "underrail-wiki-raw") + "; excludes crits, special attacks, ammo, target armor/resistance, and conditional feat/equipment modifiers.",
        })
    return rows


def build_damage_estimates(skills: Dict[str, Dict[str, int]], equipped: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "weapon_skill_scalars": weapon_skill_scalars(skills),
        "psi_abilities": psi_damage_estimates(skills),
        "equipped_weapon_estimates": equipped_weapon_damage_estimates(equipped, skills),
        "notes": [
            "Read-only estimate panel. It uses effective skills from the save and normalized wiki formulas, not live combat state.",
            "Damage excludes target resistances/thresholds, crits, special attacks, ammo effects, temporary buffs, and many feat/equipment conditionals unless explicitly stated.",
        ],
    }


def skill_rules_preview(
    skill_name: str,
    allocated: int,
    effective: int,
    attributes: Dict[str, Dict[str, int]],
    skills: Dict[str, Dict[str, int]],
    level: Optional[int],
) -> Dict[str, Any]:
    effective_attrs = {name: int(values["modified"]) for name, values in attributes.items()}
    allocated_skills = {name: int(values["allocated"]) for name, values in skills.items()}
    computed = preview_effective_skill(skill_name, allocated, effective_attrs, level, allocated_skills)
    rule = GAME_RULES.get("skills", {}).get(skill_name, {})
    return {
        "related_attribute": rule.get("related_attribute"),
        "attribute_value": _related_attribute_value(skill_name, effective_attrs),
        "attribute_modifier_percent": round(base_ability_modifier(_related_attribute_value(skill_name, effective_attrs)) * 100),
        "synergies": rule.get("synergies", {}),
        "computed_from_allocated": computed,
        "loaded_effective": int(effective),
        "unexplained_delta": int(effective) - computed,
    }


FEAT_RULES = load_feat_rules()
FEAT_IDS = load_feat_ids()
TOOLTIPS = load_tooltips()
COMMUNITY_MODS = load_community_mods()
GAME_RULES = load_game_rules()
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




RELATION_LABELS = {
    0: "Likely hostile",
    1: "Neutral / limited",
    2: "Friendly / non-hostile",
    3: "Self/allied",
    4: "Special/scripted",
}

KNOWN_FACTION_PREFIXES = (
    "campHathor", "coreCity", "freeDrones", "protectorate", "foundry", "junkyard",
    "blackEels", "scrappers", "faceless", "rathound", "player", "sgs", "oculus",
    "drones", "pirates", "expedition", "lunatic", "bandit", "native", "mutie",
)


def _is_ascii_identifier(raw: bytes) -> bool:
    return bool(raw) and all(32 <= c < 127 for c in raw)


def _looks_like_faction_id(text: str) -> bool:
    if not text or len(text) > 64:
        return False
    if text in {"player", "destructables"}:
        return True
    return any(text.startswith(prefix) for prefix in KNOWN_FACTION_PREFIXES) or ("_" in text and not text.startswith("messages"))


def _find_faction_object_markers(payload: bytes) -> List[Dict[str, Any]]:
    markers: List[Dict[str, Any]] = []
    for pos in range(0, max(0, len(payload) - 8)):
        if payload[pos] != 1:
            continue
        id_len = payload[pos + 1]
        if not (1 <= id_len <= 64):
            continue
        id_start = pos + 2
        id_end = id_start + id_len
        if id_end + 1 + id_len + 1 >= len(payload):
            continue
        faction_id_raw = payload[id_start:id_end]
        if not _is_ascii_identifier(faction_id_raw):
            continue
        if payload[id_end] != id_len or payload[id_end + 1:id_end + 1 + id_len] != faction_id_raw:
            continue
        display_len_pos = id_end + 1 + id_len
        display_len = payload[display_len_pos]
        display_start = display_len_pos + 1
        display_end = display_start + display_len
        if not (1 <= display_len <= 96) or display_end >= len(payload):
            continue
        display_raw = payload[display_start:display_end]
        if not _is_ascii_identifier(display_raw):
            continue
        faction_id = faction_id_raw.decode("ascii", "replace")
        if not _looks_like_faction_id(faction_id):
            continue
        markers.append({
            "offset": pos,
            "relations_start": display_end,
            "id": faction_id,
            "name": display_raw.decode("ascii", "replace"),
        })
    # Deduplicate overlapping false starts.
    out: List[Dict[str, Any]] = []
    last = -999
    for marker in sorted(markers, key=lambda m: m["offset"]):
        if marker["offset"] - last > 4:
            out.append(marker)
            last = marker["offset"]
    return out




FLAG_PREFIX_MEANINGS = {
    "loc": "location/local script state",
    "frag": "quest fragment / scripted encounter state",
    "npc": "NPC dialogue or lifecycle state",
    "ch": "Camp Hathor quest/dialogue state (observed)",
    "powSrc": "power source / switchable object state",
    "xpbl": "Expedition DLC / Black Sea content state",
    "gms": "GMS compound state",
    "fls": "Foundry/Lower-caves style quest state (inferred)",
    "dungeon": "dungeon instance/navigation state",
    "bulkDiscovery": "map discovery marker",
    "Event": "timed/random event state",
}

# Minimal decoded map labels from the Underrail wiki plus observed save strings.
# This is intentionally small and grows as we verify areas from saves/wiki.
KNOWN_AREA_IDS = {
    "cvw41": "Isaac's River",
    "cvw42": "Isaac's River",
    "cvw43": "Isaac's River",
    "cvw44": "Isaac's River",
    "cvw45": "Isaac's River",
    "cvw46": "Isaac's River",
    "cvw47": "Isaac's River",
    "cvw48": "Isaac's River",
    "cvw49": "Isaac's River",
    "cvw50": "Isaac's River",
    "cvw51": "Isaac's River",
    "cvw52": "Isaac's River",
    "cvw53": "Isaac's River",
    "dun_wasteWater": "Wastewater Processing Plant / mutant refuge",
    "mushroomCoveBase": "Mushroom Cove base",
    "gms_l3": "GMS compound level 3",
    "xpbl_ojyc": "Black Sea / Expedition OJYC content",
    "fls": "Foundry / Rathound King questline",
}

AREA_FACTION_HINTS = {
    "cvw47": [("campHathor", "Camp Hathor / Hathorians", "wiki+save: Isaac's River Hathorian camp"), ("campHathor_animals", "Camp Hathor animals", "save relation neighbor")],
    "dun_wasteWater": [("dun_wasteWater", "Dungeon WasteWater", "exact faction id"), ("dun_wasteWater_cameras", "Dungeon WasteWater - Cameras", "same area"), ("dun_wasteWater_slaves", "Dungeon WasteWater - Slaves", "same area")],
    "mushroomCoveBase": [("mushroomCove_hunterWolo", "MushroomCove NE - Hunter Wolo", "nearest save faction id; bug faction not mapped yet")],
    "gms_l3": [("gms_intruders", "GMS intruders / raiders", "raider marker likely maps to GMS intruder faction"), ("gms_intruders2", "GMS intruders 2", "same encounter family"), ("gms_l2_sentries", "GMS sentries", "nearby GMS hostile faction")],
    "xpbl_ojyc": [("blackLake_muties", "Black Lake Muties", "Expedition muties; low-confidence area/faction hint"), ("tchortists_beetle", "Tchortists Beetle", "coil-spider/beetle-like hostile fauna hint, low confidence")],
    "fls": [("rathoundKing", "Rathound King", "rat king kill marker / questline")],
}

MARKER_FACTION_HINTS = {
    "loc_cvw47_allHathoriansKilled": [("campHathor", "Camp Hathor / Hathorians", "exact marker text names Hathorians"), ("campHathor_animals", "Camp Hathor animals", "same faction family")],
    "ch_killRathoundKing": [("rathoundKing", "Rathound King", "exact quest target"), ("rathoundPack", "Rathound Pack", "related animal faction")],
    "ch_killRathoundKingStarted": [("rathoundKing", "Rathound King", "exact quest target"), ("rathoundPack", "Rathound Pack", "related animal faction")],
    "ch_killRathoundKingCompleted": [("rathoundKing", "Rathound King", "exact quest target"), ("rathoundPack", "Rathound Pack", "related animal faction")],
    "fls_ratkingKilled": [("rathoundKing", "Rathound King", "rat king / Rathound King wording"), ("rathoundPack", "Rathound Pack", "related animal faction")],
    "gms_l3_raidersKilled": [("gms_intruders", "GMS intruders / raiders", "raider marker likely maps to GMS intruder faction"), ("gms_intruders2", "GMS intruders 2", "same encounter family")],
    "gms_l3_allRaidersDead": [("gms_intruders", "GMS intruders / raiders", "raider marker likely maps to GMS intruder faction"), ("gms_intruders2", "GMS intruders 2", "same encounter family")],
    "frag_dun_wasteWater_killedBoss": [("dun_wasteWater", "Dungeon WasteWater", "exact area faction id"), ("old_junkyard_muties", "Old Junkyard Muties", "mutie/refuge faction family")],
    "frag_dun_wasteWater_corpseGender": [("dun_wasteWater", "Dungeon WasteWater", "same area metadata")],
    "xpbl_ojyc_mutiesKilled": [("blackLake_muties", "Black Lake Muties", "Expedition muties; low-confidence match")],
    "xpbl_ojyc_coilSpidersKilled": [("tchortists_beetle", "Tchortists Beetle", "hostile creature/faction-family hint, low confidence")],
    "npc_elwood_dead": [("junkyard_elwoods_house", "Junkyard Elwood's House", "NPC name exact to faction id")],
    "npc_jy_vilmer_dead": [("junkyard", "Junkyard", "JY prefix suggests Junkyard; exact faction not mapped")],
    "npc_lux_gerhardPage_dead": [("unknown", "Unknown NPC/page state", "lifecycle marker; faction not mapped yet")],
}

KILL_MARKER_WORDS = ("kill", "killed", "dead", "corpse", "all", "boss")
AREA_MARKER_PREFIXES = ("loc_", "frag_", "npc_", "ch_", "powSrc_", "xpbl_", "gms_", "fls_", "dungeon_", "bulkDiscovery_", "Event_")


def serialized_string_records(payload: bytes) -> List[Dict[str, Any]]:
    """Extract readable length-prefixed strings from the unpacked global.dat stream.

    Underrail's serialized graph frequently encodes strings as:
      0x06 <record-id:int32> <length:byte> <ascii bytes> <value/ref...>
    This is heuristic, but it is stable enough for read-only inspection of flags.
    """
    records: List[Dict[str, Any]] = []
    for pos in range(0, max(0, len(payload) - 8)):
        if payload[pos] != 0x06:
            continue
        strlen_pos = pos + 5
        strlen = payload[strlen_pos]
        if not (3 <= strlen <= 96):
            continue
        start = strlen_pos + 1
        end = start + strlen
        if end >= len(payload):
            continue
        raw = payload[start:end]
        if not _is_ascii_identifier(raw):
            continue
        text = raw.decode("ascii", "replace")
        records.append({
            "offset": pos,
            "string_offset": start,
            "length": strlen,
            "text": text,
            "value_byte": payload[end],
            "after_hex": bytes(payload[end:end + 12]).hex(),
        })
    return records


def decode_marker_prefix(text: str) -> Tuple[str, str]:
    for prefix in sorted(FLAG_PREFIX_MEANINGS, key=len, reverse=True):
        token = prefix + "_"
        if text.startswith(token):
            return prefix, FLAG_PREFIX_MEANINGS[prefix]
    if "_" in text:
        prefix = text.split("_", 1)[0]
        return prefix, "unknown/custom script namespace"
    return "", "unprefixed saved string"


def area_id_for_marker(text: str) -> Optional[str]:
    lower = text.lower()
    for area_id in sorted(KNOWN_AREA_IDS, key=len, reverse=True):
        if area_id.lower() in lower:
            return area_id
    return None


def faction_hints_for_marker(text: str, area_id: Optional[str]) -> List[Dict[str, str]]:
    hints = []
    seen = set()
    for fid, name, reason in MARKER_FACTION_HINTS.get(text, []):
        hints.append({"id": fid, "name": name, "reason": reason, "confidence": "medium" if fid != "unknown" else "low"})
        seen.add(fid)
    if area_id:
        for fid, name, reason in AREA_FACTION_HINTS.get(area_id, []):
            if fid not in seen:
                hints.append({"id": fid, "name": name, "reason": reason, "confidence": "low"})
                seen.add(fid)
    # Token-level fallbacks for newly discovered markers.
    lower = text.lower()
    fallback_rules = [
        ("hathor", ("campHathor", "Camp Hathor / Hathorians", "token contains Hathor", "medium")),
        ("rathound", ("rathoundPack", "Rathound Pack", "token contains rathound", "low")),
        ("mutie", ("blackLake_muties", "Muties / mutant faction family", "token contains mutie", "low")),
        ("mutant", ("old_junkyard_mutants", "Old Junkyard Mutants", "token contains mutant", "low")),
        ("raider", ("gms_intruders", "GMS intruders / raiders", "token contains raider", "low")),
    ]
    for token, (fid, name, reason, confidence) in fallback_rules:
        if token in lower and fid not in seen:
            hints.append({"id": fid, "name": name, "reason": reason, "confidence": confidence})
            seen.add(fid)
    return hints


def marker_category(text: str) -> str:
    lower = text.lower()
    if any(word in lower for word in ("kill", "killed", "dead", "corpse")):
        return "kill/death marker"
    if lower.startswith("powsrc_"):
        return "power/object state"
    if lower.startswith("event_") or "starttime" in lower:
        return "event timer"
    if lower.startswith("bulkdiscovery_"):
        return "discovery marker"
    if any(word in lower for word in ("met", "asked", "know", "talk", "report")):
        return "dialogue/knowledge marker"
    return "area/script marker"


def marker_relevance(text: str) -> bool:
    lower = text.lower()
    if text.startswith(AREA_MARKER_PREFIXES):
        if any(word in lower for word in ("kill", "dead", "corpse", "hathor", "cvw", "waste", "mut", "sewer", "mushroom", "gms", "hopsy", "coltrane")):
            return True
    return False


def extract_area_markers_from_payload(payload: bytes) -> Dict[str, Any]:
    markers = []
    for rec in serialized_string_records(payload):
        text = rec["text"]
        if not marker_relevance(text):
            continue
        prefix, meaning = decode_marker_prefix(text)
        area_id = area_id_for_marker(text)
        markers.append({
            "text": text,
            "offset": rec["offset"],
            "string_offset": rec["string_offset"],
            "length": rec["length"],
            "value_byte": rec["value_byte"],
            "after_hex": rec["after_hex"],
            "prefix": prefix,
            "prefix_meaning": meaning,
            "area_id": area_id,
            "area_label": KNOWN_AREA_IDS.get(area_id or "", ""),
            "mapped_factions": faction_hints_for_marker(text, area_id),
            "category": marker_category(text),
            "confidence": "heuristic/read-only",
        })
    markers.sort(key=lambda m: (m["area_label"] or "~", m["category"], m["text"], m["offset"]))
    kill_markers = [m for m in markers if m["category"] == "kill/death marker"]
    by_area: Dict[str, Dict[str, Any]] = {}
    for marker in markers:
        key = marker["area_id"] or "unknown"
        area = by_area.setdefault(key, {
            "area_id": marker["area_id"] or "unknown",
            "area_label": marker["area_label"] or "Unknown / unmapped area",
            "markers": [],
            "kill_markers": [],
            "mapped_factions": [],
        })
        area["markers"].append(marker)
        for hint in marker.get("mapped_factions", []):
            if hint["id"] not in {item["id"] for item in area["mapped_factions"]}:
                area["mapped_factions"].append(hint)
        if marker["category"] == "kill/death marker":
            area["kill_markers"].append(marker)
    return {
        "markers": markers[:300],
        "kill_markers": kill_markers[:120],
        "areas": sorted(by_area.values(), key=lambda a: (a["area_label"], a["area_id"])),
        "prefix_legend": FLAG_PREFIX_MEANINGS,
        "area_legend": KNOWN_AREA_IDS,
        "faction_hint_legend": {"area_hints": AREA_FACTION_HINTS, "marker_hints": MARKER_FACTION_HINTS},
        "notes": [
            "Read-only heuristic extraction from unpacked global.dat serialized strings.",
            "value_byte is the byte immediately after the serialized string; booleans often appear as 0/1, counters may be small ints or multi-byte values.",
            "CVW41-CVW53 are mapped from the Underrail wiki as Isaac's River; CVW47 is the tile that produced loc_cvw47_allHathoriansKilled.",
        ],
    }


def read_area_markers(path: str | Path) -> Dict[str, Any]:
    _, payload = unpack_dat(Path(path))
    return extract_area_markers_from_payload(bytes(payload))


def find_faction_relations_in_payload(payload: bytes) -> List[Dict[str, Any]]:
    """Best-effort read-only extraction of saved faction relation tables.

    Underrail serializes faction definitions into global.dat with repeated
    length-prefixed faction ids and 32-bit relation enum values.  This parser is
    intentionally conservative and read-only: it reports raw player relation
    codes and offsets for visualization, but does not claim enough certainty to
    patch them.
    """
    markers = _find_faction_object_markers(payload)
    rows: List[Dict[str, Any]] = []
    for index, marker in enumerate(markers):
        end = markers[index + 1]["offset"] if index + 1 < len(markers) else min(len(payload), marker["relations_start"] + 2000)
        segment = payload[marker["relations_start"]:end]
        relations = []
        cursor = 0
        while cursor < len(segment) - 10:
            rel_len = segment[cursor]
            if 1 <= rel_len <= 64 and cursor + 1 + rel_len + 8 <= len(segment):
                raw = segment[cursor + 1:cursor + 1 + rel_len]
                if _is_ascii_identifier(raw):
                    rel_id = raw.decode("ascii", "replace")
                    value_offset = marker["relations_start"] + cursor + 1 + rel_len
                    raw_value = segment[cursor + 1 + rel_len:cursor + 1 + rel_len + 4]
                    tail = segment[cursor + 1 + rel_len + 4:cursor + 1 + rel_len + 8]
                    value = int.from_bytes(raw_value, "little", signed=True)
                    if tail == b"\xff\xff\xff\xff" and -5 <= value <= 10 and _looks_like_faction_id(rel_id):
                        relations.append({
                            "target": rel_id,
                            "value": value,
                            "label": RELATION_LABELS.get(value, f"Unknown code {value}"),
                            "value_offset": value_offset,
                        })
                        cursor += 1 + rel_len + 8
                        continue
            cursor += 1
        player = next((rel for rel in relations if rel["target"] == "player"), None)
        if player or any(fid in marker["id"] for fid in ("campHathor", "coreCity", "freeDrones", "protectorate", "foundry", "junkyard")):
            rows.append({
                "id": marker["id"],
                "name": marker["name"],
                "offset": marker["offset"],
                "player_relation": player,
                "relations": relations[:80],
                "confidence": "heuristic",
            })
    return rows


def read_faction_relations(path: str | Path) -> List[Dict[str, Any]]:
    _, payload = unpack_dat(Path(path))
    return find_faction_relations_in_payload(bytes(payload))




def player_relation_map(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {row["id"]: row for row in rows if row.get("player_relation") is not None}


def faction_relation_deltas(current_rows: List[Dict[str, Any]], baseline_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    current = player_relation_map(current_rows)
    baseline = player_relation_map(baseline_rows)
    deltas: List[Dict[str, Any]] = []
    for faction_id in sorted(set(current) & set(baseline)):
        cur = current[faction_id]["player_relation"]
        base = baseline[faction_id]["player_relation"]
        if cur["value"] != base["value"]:
            deltas.append({
                "id": faction_id,
                "name": current[faction_id].get("name") or baseline[faction_id].get("name") or faction_id,
                "baseline_value": base["value"],
                "baseline_label": base["label"],
                "current_value": cur["value"],
                "current_label": cur["label"],
                "current_value_offset": cur.get("value_offset"),
            })
    return deltas


def sibling_baseline_faction_comparison(save_dat_path: Path, current_rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    save_folder = save_dat_path.parent
    saves_root = save_folder.parent
    for baseline_name in ("SortingNightmare", "NewEpicEnemies"):
        baseline_dat = saves_root / baseline_name / "global.dat"
        if baseline_dat.is_file() and baseline_dat.resolve() != save_dat_path.resolve():
            baseline_rows = read_faction_relations(baseline_dat)
            return {
                "baseline_name": baseline_name,
                "baseline_path": str(baseline_dat),
                "deltas": faction_relation_deltas(current_rows, baseline_rows),
                "note": "Automatic comparison against a nearby known-good save, if present. Read-only; no faction edits are applied.",
            }
    return None


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
    for name in SKILLS:
        skills[name]["rules_preview"] = skill_rules_preview(
            name,
            skills[name]["allocated"],
            skills[name]["effective"],
            attrs,
            skills,
            inferred_level,
        )

    attr_total = sum(v["base"] for v in attrs.values())
    skill_total = sum(v["allocated"] for v in skills.values())
    attr_budget = inferred_attribute_budget(inferred_level) or attr_total
    skill_budget = inferred_skill_budget(inferred_level) or skill_total
    feat_records = read_feat_records(sv.path)
    detected_feats = display_names_from_feat_records(feat_records) or detect_feats_for_path(path)
    faction_relations = read_faction_relations(sv.path)
    faction_relation_comparison = sibling_baseline_faction_comparison(sv.path, faction_relations)
    area_markers = read_area_markers(sv.path)
    inventory_weight = inventory_tool.analyze_inventory_weight(sv.path)
    equipped_items = inventory_tool.read_equipped_items(sv.path)
    damage_estimates = build_damage_estimates(skills, equipped_items)
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
        "community_mods": COMMUNITY_MODS,
        "game_rules": GAME_RULES,
        "faction_relations": faction_relations,
        "faction_relation_comparison": faction_relation_comparison,
        "area_markers": area_markers,
        "inventory_weight": inventory_weight,
        "equipped_items": equipped_items,
        "damage_estimates": damage_estimates,
        "notes": [
            "The save stores current allocated attributes/skills here, but unspent attribute/skill point offsets are not mapped.",
            "This UI preserves the loaded totals by default. If the character has unused points, enter a higher target budget to spend them without editing the unspent counters.",
            "Feat list is not read from the save; screenshot-known feats are preselected for provided reference saves and can be adjusted manually.",
            "Faction relation visualization is heuristic/read-only. Code 0 was observed on the latest Camp Hathor hostile save; code 2 matched the earlier non-hostile SortingNightmare save.",
            "Area marker extraction is heuristic/read-only and decodes readable loc_/frag_/npc_/xpbl_ script keys such as loc_cvw47_allHathoriansKilled.",
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

    def _send_file(self, path: Path) -> None:
        raw = path.read_bytes()
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
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
            if path == "/api/list-saves":
                sort = (query.get("sort") or ["alpha"])[0]
                self._send(200, {"saves": list_save_folders(sort=sort), "sort": sort})
            elif path == "/api/community-mods":
                self._send(200, COMMUNITY_MODS)
            elif path == "/api/runtime/scan":
                game_dir = (query.get("game_dir") or [None])[0]
                self._send(200, runtime_mods.scan_runtime_mods(game_dir))
            elif path == "/api/runtime/status":
                self._send(200, runtime_mods.runtime_process_status())
            elif path == "/api/health":
                self._send(200, {"ok": True, "frontend": str(frontend_out_dir()) if frontend_out_dir() else "legacy", "community_mods": len(COMMUNITY_MODS.get("mods", []))})
            else:
                static_file = static_file_for_url(path)
                if static_file:
                    self._send_file(static_file)
                elif path == "/" or path == "/index.html":
                    self._send(200, INDEX_HTML, "text/html")
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
            elif path == "/api/runtime/patch-throwing-cap":
                self._send(200, runtime_mods.patch_throwing_chance_cap(
                    body.get("game_dir"), float(body.get("cap", 0.99)), bool(body.get("dry_run", False)),
                ))
            elif path == "/api/runtime/patch-mods":
                self._send(200, runtime_mods.patch_runtime_mods(
                    body.get("game_dir"), body.get("mods", []), float(body.get("cap", 0.99)),
                    float(body.get("weight_multiplier", 0.1)), bool(body.get("dry_run", False)),
                ))
            elif path == "/api/runtime/rollback":
                self._send(200, runtime_mods.rollback_runtime_patch(body.get("game_dir"), body["backup"]))
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
    open_browser = False
    if "--open-browser" in argv:
        open_browser = True
        argv.remove("--open-browser")
    port = int(argv[0]) if argv else DEFAULT_PORT
    url = f"http://127.0.0.1:{port}"
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Underrail Visual Respec Editor running at {url}")
    frontend_dir = frontend_out_dir()
    print(f"Frontend: {frontend_dir if frontend_dir else 'legacy embedded HTML'}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
