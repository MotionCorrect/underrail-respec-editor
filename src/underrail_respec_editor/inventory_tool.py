"""Read-only Underrail inventory weight breakdown research tool.

The save stores inventory item instances in the BinaryFormatter payload inside
``global.dat``. Item instances expose a definition-provider path (for example
``ammo\\bolt``) and stack count; exact vanilla weights are definition data, not
saved per item, so this module joins parsed save rows to a wiki/game-data weight
catalog when one is available.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .save_tool import GZIP_MAGIC, HEADER_LEN, resolve_dat

ITEM_CLASSES = {"NEII", "AI3", "BII1", "BII", "QSII", "CII", "WII", "HII", "ASII", "SEII"}
CATALOG_PATH = Path(__file__).resolve().parent / "data" / "item_weights.json"
ITEM_ICONS_PATH = Path(__file__).resolve().parent / "data" / "item_icons.json"
ITEM_COMBAT_PATH = Path(__file__).resolve().parent / "data" / "item_combat.json"
WIKI_API = "https://www.stygiansoftware.com/wiki/api.php"
WIKI_RAW = "https://www.stygiansoftware.com/wiki/index.php"


def _load_nrbf():
    try:
        import nrbf  # type: ignore
        return nrbf
    except Exception as exc:  # pragma: no cover - exercised only when dependency is absent
        raise RuntimeError("inventory parsing requires the nrbf package; install with `uv pip install nrbf`") from exc


def unpack_payload(path: Path) -> bytes:
    dat = resolve_dat(path)
    blob = dat.read_bytes()
    if len(blob) <= HEADER_LEN or blob[HEADER_LEN:HEADER_LEN + 2] != GZIP_MAGIC:
        raise ValueError(f"{dat} is not a packed Underrail global.dat")
    return gzip.decompress(blob[HEADER_LEN:])


def parse_nrbf_objects(payload: bytes) -> Dict[int, Any]:
    nrbf = _load_nrbf()
    parser = nrbf.NRBFParser(payload)
    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old_limit, 20000))
    try:
        try:
            parser.parse()
        except RecursionError:
            # nrbf resolves object graphs recursively after reading all records.
            # Underrail saves contain cycles; the raw object table is still useful.
            pass
    finally:
        sys.setrecursionlimit(old_limit)
    return parser.objects


def _ref_id(value: Any) -> int | None:
    if isinstance(value, dict) and set(value.keys()) == {"__ref__"}:
        return int(value["__ref__"])
    return None


def deref(objects: Dict[int, Any], value: Any, depth: int = 8) -> Any:
    seen = set()
    current = value
    for _ in range(depth):
        rid = _ref_id(current)
        if rid is None or rid in seen:
            return current
        seen.add(rid)
        current = objects.get(rid)
    return current


def normalize_datafile(path: str | None) -> str:
    if not path:
        return ""
    value = str(path).replace("/", "\\").strip().lower()
    if value.endswith(".item"):
        value = value[:-5]
    value = re.sub(r"\\+", r"\\", value)
    return value


def item_path_from_definition(objects: Dict[int, Any], dp_value: Any) -> str | None:
    dp = deref(objects, dp_value)
    for _ in range(8):
        if isinstance(dp, str):
            return dp
        if not isinstance(dp, dict):
            return None
        for key in ("LIDP:P", "IIDP:D"):
            if key in dp:
                nxt = deref(objects, dp[key])
                if nxt is dp:
                    return None
                dp = nxt
                break
        else:
            return None
    return None


def parse_inventory_items(target: Path) -> List[Dict[str, Any]]:
    """Return item rows from the player's serialized inventory container.

    Verified structural clues:
    - global.dat is 24-byte header + gzip payload.
    - The root player object references exactly one inventory container class `IC`.
    - `IC:I:Count` plus `IC:I:<n>` slots hold item instance records.
    - Item records use shared fields `II:S` (stack count), `II:DP` (definition
      provider), optional `CII:QL` (component quality), plus obfuscated subclasses.
    """
    objects = parse_nrbf_objects(unpack_payload(target))
    containers = [obj for obj in objects.values() if isinstance(obj, dict) and obj.get("__class__") == "IC"]
    if not containers:
        return []
    # Player saves observed so far contain one IC; choose the largest if a future
    # payload carries small nested containers as well.
    inv = max(containers, key=lambda c: int(c.get("IC:I:Count", 0)))
    rows: List[Dict[str, Any]] = []
    for slot in range(int(inv.get("IC:I:Count", 0))):
        item = deref(objects, inv.get(f"IC:I:{slot}"))
        if not isinstance(item, dict) or item.get("__class__") not in ITEM_CLASSES:
            continue
        path = item_path_from_definition(objects, item.get("II:DP"))
        if not path:
            continue
        rows.append({
            "slot": slot,
            "class": item.get("__class__"),
            "path": path,
            "datafile_key": normalize_datafile(path),
            "stack": int(item.get("II:S", 1) or 1),
            "quality": item.get("CII:QL"),
            "durability": item.get("II:D"),
            "battery": item.get("II:B"),
        })
    return rows


def load_item_combat_catalog(path: Path | None = None) -> Dict[str, Dict[str, Any]]:
    combat_file = path or ITEM_COMBAT_PATH
    if not combat_file.exists():
        return {}
    raw = json.loads(combat_file.read_text(encoding="utf-8"))
    raw_items = raw.get("items", raw) if isinstance(raw, dict) else raw
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(raw_items, dict):
        iterable = raw_items.items()
    else:
        iterable = ((entry.get("datafile_key"), entry) for entry in raw_items if isinstance(entry, dict))
    for key, entry in iterable:
        norm = normalize_datafile(key)
        if norm and isinstance(entry, dict):
            out[norm] = entry
    return out


def load_item_icon_catalog(path: Path | None = None) -> Dict[str, Dict[str, Any]]:
    icon_file = path or ITEM_ICONS_PATH
    if not icon_file.exists():
        return {}
    raw = json.loads(icon_file.read_text(encoding="utf-8"))
    raw_items = raw.get("items", raw) if isinstance(raw, dict) else raw
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(raw_items, dict):
        iterable = raw_items.items()
    else:
        iterable = ((entry.get("datafile_key"), entry) for entry in raw_items if isinstance(entry, dict))
    for key, entry in iterable:
        if not isinstance(entry, dict):
            continue
        norm = normalize_datafile(key or entry.get("datafile") or entry.get("path") or entry.get("datafile_key"))
        if norm and entry.get("icon_path"):
            out[norm] = entry
    return out


def load_weight_catalog(path: Path | None = None) -> Dict[str, Dict[str, Any]]:
    catalog_file = path or CATALOG_PATH
    if not catalog_file.exists():
        return {}
    raw = json.loads(catalog_file.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "items" in raw:
        raw_items = raw["items"]
    else:
        raw_items = raw
    icons = load_item_icon_catalog()
    combat = load_item_combat_catalog()
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(raw_items, dict):
        iterable = raw_items.values()
    else:
        iterable = raw_items
    for entry in iterable:
        if not isinstance(entry, dict):
            continue
        key = normalize_datafile(entry.get("datafile") or entry.get("path") or entry.get("datafile_key"))
        if key:
            merged = dict(entry)
            if key in icons:
                merged["icon_path"] = icons[key].get("icon_path")
                merged["icon_image"] = icons[key].get("image")
                merged["icon_source_url"] = icons[key].get("source_url")
            if key in combat:
                merged["combat"] = combat[key]
            out[key] = merged
    return out


def category_for_path(path: str) -> str:
    return normalize_datafile(path).split("\\", 1)[0] or "unknown"


def clean_wiki_value(value: str) -> str:
    value = re.sub(r"<!--.*?-->", " ", value, flags=re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\{\{[^{}]*(?:\{\{[^{}]*\}\}[^{}]*)*\}\}", " ", value)
    value = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", value)
    value = re.sub(r"\[\[([^\]]+)\]\]", r"\1", value)
    value = re.sub(r"'''?", "", value)
    return re.sub(r"\s+", " ", value).strip()


def extract_infobox_fields(raw: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    for match in re.finditer(r"^\|\s*([A-Za-z0-9_ -]+)\s*=\s*(.*?)(?=\n\||\n\}\})", raw, flags=re.M | re.S):
        key = match.group(1).strip().lower().replace(" ", "_")
        fields[key] = clean_wiki_value(match.group(2))
    return fields


def _parse_float(value: str | None) -> float | None:
    if not value:
        return None
    text = value.strip()
    # Underrail Wiki item weights commonly use decimal commas (for example
    # ``1,00`` for one weight unit).  Values with both separators are treated as
    # thousands-comma + decimal-dot, but comma-only numeric fields are decimal.
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else None


def _parse_int(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"-?\d+", value.replace(",", ""))
    return int(match.group(0)) if match else None


def extract_item_weight_entry(title: str, raw: str) -> Dict[str, Any] | None:
    """Extract display metadata, weight, value, and datafile from a wiki raw page."""
    if "infobox item" not in raw.lower() and "infobox item2" not in raw.lower():
        return None
    fields = extract_infobox_fields(raw)
    datafile = fields.get("datafile")
    weight = _parse_float(fields.get("weight"))
    if not datafile or weight is None:
        return None
    entry: Dict[str, Any] = {
        "page": title,
        "name": fields.get("name") or title,
        "type": fields.get("type") or "",
        "datafile": datafile,
        "datafile_key": normalize_datafile(datafile),
        "weight": weight,
        "source": "underrail-wiki-raw",
    }
    value = _parse_int(fields.get("value"))
    if value is not None:
        entry["value"] = value
    return entry


def summarize_inventory_weight(items: List[Dict[str, Any]], catalog: Dict[str, Dict[str, Any]], target: str) -> Dict[str, Any]:
    known_total = 0.0
    unknown_items = []
    enriched = []
    for raw_item in items:
        item = dict(raw_item)
        item["category"] = category_for_path(item["path"])
        cat = catalog.get(item["datafile_key"])
        if cat and cat.get("weight") not in (None, ""):
            single = float(cat["weight"])
            item["name"] = cat.get("name") or item["path"]
            item["wiki_type"] = cat.get("type")
            item["wiki_page"] = cat.get("page")
            item["wiki_url"] = WIKI_RAW + "?" + urllib.parse.urlencode({"title": cat["page"]}) if cat.get("page") else None
            item["icon_path"] = cat.get("icon_path")
            item["icon_image"] = cat.get("icon_image")
            item["icon_source_url"] = cat.get("icon_source_url")
            item["single_weight"] = single
            item["total_weight"] = single * item["stack"]
            known_total += item["total_weight"]
        else:
            item["name"] = item["path"]
            item["single_weight"] = None
            item["total_weight"] = None
            unknown_items.append(item)
        enriched.append(item)
    for item in enriched:
        if item["total_weight"] is not None and known_total > 0:
            item["percent_of_known_weight"] = item["total_weight"] / known_total * 100.0
        else:
            item["percent_of_known_weight"] = None
    for rank, item in enumerate(
        sorted(
            (row for row in enriched if row["single_weight"] is not None),
            key=lambda row: (-(row["single_weight"] or 0), -(row["total_weight"] or 0), row["slot"]),
        ),
        start=1,
    ):
        item["single_weight_rank"] = rank

    by_category: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"weight": 0.0, "known_items": 0, "unknown_items": 0, "stacks": 0})
    for item in enriched:
        bucket = by_category[item["category"]]
        bucket["stacks"] += item["stack"]
        if item["total_weight"] is None:
            bucket["unknown_items"] += 1
        else:
            bucket["known_items"] += 1
            bucket["weight"] += item["total_weight"]
    categories = []
    for name, bucket in sorted(by_category.items(), key=lambda kv: kv[1]["weight"], reverse=True):
        bucket = dict(bucket)
        bucket["category"] = name
        bucket["percent_of_known_weight"] = (bucket["weight"] / known_total * 100.0) if known_total else None
        categories.append(bucket)
    return {
        "target": target,
        "item_count": len(enriched),
        "known_weight_total": known_total,
        "unknown_weight_items": len(unknown_items),
        "unknown_items": sorted(unknown_items, key=lambda row: (-row["stack"], row["slot"])),
        "items": sorted(enriched, key=lambda row: (row["total_weight"] is None, -(row["total_weight"] or 0), row["slot"])),
        "per_item_heaviest": sorted(
            (row for row in enriched if row["single_weight"] is not None),
            key=lambda row: (-(row["single_weight"] or 0), -(row["total_weight"] or 0), row["slot"]),
        ),
        "categories": categories,
        "notes": [
            "Read-only: no save bytes are changed.",
            "Percentages are of known joined weights only; update item_weights.json for exact full coverage.",
        ],
    }


def analyze_inventory_weight(target: Path, catalog_path: Path | None = None) -> Dict[str, Any]:
    catalog = load_weight_catalog(catalog_path)
    dat = resolve_dat(target)
    return summarize_inventory_weight(parse_inventory_items(target), catalog, target=str(dat))


def _definition_from_item(objects: Dict[int, Any], item: Dict[str, Any]) -> Dict[str, Any] | None:
    dp = deref(objects, item.get("II:DP"))
    if isinstance(dp, dict) and "IIDP:D" in dp:
        definition = deref(objects, dp.get("IIDP:D"))
        return definition if isinstance(definition, dict) else None
    return None


def describe_item_instance(objects: Dict[int, Any], item: Dict[str, Any], catalog: Dict[str, Dict[str, Any]] | None = None) -> Dict[str, Any]:
    catalog = catalog or load_weight_catalog()
    path = item_path_from_definition(objects, item.get("II:DP"))
    key = normalize_datafile(path)
    cat = catalog.get(key) if key else None
    if cat is None and key and "\\" in key:
        # Some equipped item definition providers omit the same folder prefix the
        # wiki catalog uses (for example armor\\liftingBelt vs LiftingBelt.item).
        cat = catalog.get(key.rsplit("\\", 1)[-1])
    definition = _definition_from_item(objects, item)
    name = (cat or {}).get("name") or (definition or {}).get("I:N") or path or "Unknown item"
    out: Dict[str, Any] = {
        "class": item.get("__class__"),
        "path": path,
        "datafile_key": key,
        "name": name,
        "stack": int(item.get("II:S", 1) or 1),
        "durability": item.get("II:D"),
        "battery": item.get("II:B"),
        "quality": item.get("CII:QL"),
    }
    if cat:
        out.update({
            "wiki_type": cat.get("type"),
            "wiki_page": cat.get("page"),
            "wiki_url": WIKI_RAW + "?" + urllib.parse.urlencode({"title": cat["page"]}) if cat.get("page") else None,
            "icon_path": cat.get("icon_path"),
            "icon_image": cat.get("icon_image"),
            "icon_source_url": cat.get("icon_source_url"),
            "single_weight": cat.get("weight"),
            "combat": cat.get("combat"),
        })
    if definition:
        out.update({
            "definition_name": definition.get("I:N"),
            "definition_weight": definition.get("I:W"),
            "description": definition.get("I:D"),
        })
    return out


def read_equipped_items(target: Path) -> Dict[str, Any]:
    objects = parse_nrbf_objects(unpack_payload(target))
    catalog = load_weight_catalog()
    character_sheets = [obj for obj in objects.values() if isinstance(obj, dict) and obj.get("__class__") == "CGS"]
    if not character_sheets:
        return {"slots": [], "notes": ["Read-only: no character equipment sheet was found in this save payload."]}
    cgs = character_sheets[0]
    slots: List[Dict[str, Any]] = []

    def add_slot(slot_id: str, label: str, field: str) -> None:
        slot_obj = deref(objects, cgs.get(field))
        item = deref(objects, slot_obj.get("IS:I")) if isinstance(slot_obj, dict) else None
        row: Dict[str, Any] = {"slot": slot_id, "label": label, "equipped": isinstance(item, dict)}
        if isinstance(item, dict):
            row.update(describe_item_instance(objects, item, catalog))
        slots.append(row)

    for slot_id, label, field in [
        ("head", "Head", "CGS:H"),
        ("armor", "Armor", "CGS:A"),
        ("belt", "Belt", "CGS:B"),
        ("boots", "Boots", "CGS:B1"),
        ("shield", "Shield emitter", "CGS:SE"),
    ]:
        add_slot(slot_id, label, field)
    for idx in range(int(cgs.get("CGS:W:Count", 0) or 0)):
        add_slot(f"weapon_{idx + 1}", f"Weapon {idx + 1}", f"CGS:W:{idx}:Value")
    return {
        "slots": slots,
        "notes": [
            "Read-only: equipment is decoded from the character gear sheet; no item/save bytes are changed.",
            "Crafted equipment may show save-derived definition names when no wiki datafile path exists.",
        ],
    }


def fetch_json(params: Dict[str, str]) -> Dict[str, Any]:
    url = WIKI_API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "underrail-respec-inventory/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_wiki_raw(title: str) -> str:
    url = WIKI_RAW + "?" + urllib.parse.urlencode({"title": title, "action": "raw"})
    req = urllib.request.Request(url, headers={"User-Agent": "underrail-respec-inventory/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def item_category_members(limit: int | None = None) -> List[str]:
    titles: List[str] = []
    params = {"action": "query", "list": "categorymembers", "cmtitle": "Category:Items", "cmlimit": "500", "format": "json"}
    while True:
        data = fetch_json(params)
        titles.extend(m["title"] for m in data["query"]["categorymembers"] if m["ns"] == 0 and m["title"] != "Items")
        if limit is not None and len(titles) >= limit:
            return sorted(set(titles[:limit]))
        cont = data.get("continue", {}).get("cmcontinue")
        if not cont:
            break
        params["cmcontinue"] = cont
    return sorted(set(titles))


def crawl_wiki_item_weights(limit: int | None = None, sleep: float = 0.0, workers: int = 12) -> Dict[str, Any]:
    items = []
    failures = []
    titles = item_category_members(limit)

    def fetch_entry(title: str) -> Dict[str, Any] | None:
        if sleep:
            time.sleep(sleep)
        return extract_item_weight_entry(title, fetch_wiki_raw(title))

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        future_to_title = {pool.submit(fetch_entry, title): title for title in titles}
        for future in as_completed(future_to_title):
            title = future_to_title[future]
            try:
                entry = future.result()
                if entry:
                    items.append(entry)
            except Exception as exc:
                failures.append({"title": title, "error": str(exc)})
    items.sort(key=lambda row: row["datafile_key"])
    failures.sort(key=lambda row: row["title"])
    return {"source": "Underrail Wiki Category:Items raw pages", "count": len(items), "pages_seen": len(titles), "failures": failures, "items": items}


def write_wiki_item_weight_catalog(path: Path = CATALOG_PATH, limit: int | None = None, sleep: float = 0.0, workers: int = 12) -> Dict[str, Any]:
    catalog = crawl_wiki_item_weights(limit=limit, sleep=sleep, workers=workers)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalog, indent=2, sort_keys=True), encoding="utf-8")
    return catalog


def print_report(result: Dict[str, Any], limit: int = 40) -> None:
    print(f"Inventory: {result['target']}")
    print(f"Items parsed: {result['item_count']} | known weight: {result['known_weight_total']:.2f} | unknown-weight rows: {result['unknown_weight_items']}")
    print("\n-- Category distribution (% of known weight) --")
    for cat in result["categories"]:
        pct = "?" if cat["percent_of_known_weight"] is None else f"{cat['percent_of_known_weight']:.1f}%"
        print(f"  {cat['category']:16s} {cat['weight']:8.2f}  {pct:>7s}  rows={cat['known_items']} unknown={cat['unknown_items']} stacks={cat['stacks']}")
    print("\n-- Heaviest item rows --")
    for item in result["items"][:limit]:
        tw = "?" if item["total_weight"] is None else f"{item['total_weight']:.2f}"
        pct = "?" if item["percent_of_known_weight"] is None else f"{item['percent_of_known_weight']:.1f}%"
        q = "" if item.get("quality") in (None, 0) else f" q{item['quality']}"
        print(f"  #{item['slot']:03d} {tw:>8s} {pct:>7s} x{item['stack']:<4d} {item['name']}{q} [{item['path']}]")
    print("\n-- Heaviest per single item (one-count reduction impact) --")
    for item in result.get("per_item_heaviest", [])[:limit]:
        sw = "?" if item["single_weight"] is None else f"{item['single_weight']:.2f}"
        tw = "?" if item["total_weight"] is None else f"{item['total_weight']:.2f}"
        q = "" if item.get("quality") in (None, 0) else f" q{item['quality']}"
        print(f"  #{item['slot']:03d} one={sw:>7s} stack={tw:>8s} x{item['stack']:<4d} {item['name']}{q} [{item['path']}]")


def main() -> None:
    ap = argparse.ArgumentParser(description="Read-only Underrail inventory weight breakdown")
    ap.add_argument("target", nargs="?", help="save folder or global.dat")
    ap.add_argument("--catalog", type=Path, default=None, help="JSON item weight catalog; defaults to packaged data/item_weights.json")
    ap.add_argument("--json", action="store_true", help="emit full JSON instead of text report")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--crawl-wiki-catalog", type=Path, default=None, help="crawl Underrail Wiki item weights and write catalog JSON, then exit")
    ap.add_argument("--crawl-limit", type=int, default=None, help="limit pages while testing the wiki catalog crawler")
    ap.add_argument("--crawl-sleep", type=float, default=0.0, help="seconds to sleep before each wiki raw page request")
    ap.add_argument("--crawl-workers", type=int, default=12, help="parallel wiki raw page requests for catalog crawling")
    args = ap.parse_args()
    if args.crawl_wiki_catalog:
        catalog = write_wiki_item_weight_catalog(args.crawl_wiki_catalog, limit=args.crawl_limit, sleep=args.crawl_sleep, workers=args.crawl_workers)
        print(f"Wrote {catalog['count']} item weight entries from {catalog['pages_seen']} wiki pages to {args.crawl_wiki_catalog}")
        if catalog["failures"]:
            print(f"Failures: {len(catalog['failures'])}")
        return
    if not args.target:
        ap.error("target is required unless --crawl-wiki-catalog is used")
    result = analyze_inventory_weight(Path(args.target), args.catalog)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_report(result, args.limit)


if __name__ == "__main__":
    main()
