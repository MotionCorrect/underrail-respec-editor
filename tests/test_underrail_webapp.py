import json
import os
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from underrail_respec_editor import web_app as app
from underrail_respec_editor import runtime_mods
from underrail_respec_editor import inventory_tool

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "data" / "fixtures"


class UnderrailWebAppTests(unittest.TestCase):
    def test_analyze_reference_dat_reports_attributes_skills_and_feats(self):
        result = app.analyze_target(FIXTURES / "jetski_global.dat")
        self.assertEqual(result["attributes"]["Strength"]["base"], 7)
        self.assertEqual(result["attributes"]["Agility"]["modified"], 8)
        self.assertEqual(result["skills"]["Crossbows"]["allocated"], 65)
        self.assertEqual(result["skills"]["Stealth"]["effective"], 109)
        self.assertEqual(result["totals"]["attribute_base"], 42)
        self.assertEqual(result["totals"]["skill_allocated"], 520)
        self.assertEqual(result["budgets"]["attribute_budget"], 43)
        self.assertEqual(result["budgets"]["attribute_remaining"], 1)
        self.assertEqual(result["budgets"]["skill_budget"], 560)
        self.assertEqual(result["budgets"]["skill_remaining"], 40)
        self.assertIn("Marksman", result["detected_feats"])

    def test_validate_respec_catches_budget_and_feat_breakage(self):
        current = app.analyze_target(FIXTURES / "jetski_global.dat")
        proposed_attrs = {k: v["base"] for k, v in current["attributes"].items()}
        proposed_skills = {k: v["allocated"] for k, v in current["skills"].items()}
        proposed_attrs["Dexterity"] = 4
        proposed_attrs["Strength"] = 10
        validation = app.validate_respec(current, proposed_attrs, proposed_skills, current["detected_feats"], level=12)
        self.assertFalse(validation["valid"])
        self.assertTrue(any(item["type"] == "attribute_budget" for item in validation["issues"]))
        self.assertTrue(any(item.get("feat") == "Marksman" for item in validation["issues"]))

    def test_validate_point_neutral_change_can_pass(self):
        current = app.analyze_target(FIXTURES / "assault_global.dat")
        proposed_attrs = {k: v["base"] for k, v in current["attributes"].items()}
        proposed_skills = {k: v["allocated"] for k, v in current["skills"].items()}
        proposed_attrs["Strength"] -= 1
        proposed_attrs["Constitution"] += 1
        validation = app.validate_respec(current, proposed_attrs, proposed_skills, current["detected_feats"], level=6)
        self.assertTrue(validation["valid"], json.dumps(validation["issues"], indent=2))

    def test_concussive_shots_requires_crossbows_not_guns(self):
        current = app.analyze_target(FIXTURES / "jetski_global.dat")
        proposed_attrs = {k: v["base"] for k, v in current["attributes"].items()}
        proposed_skills = {k: v["allocated"] for k, v in current["skills"].items()}
        proposed_skills["Guns"] = 0
        proposed_skills["Crossbows"] = 30
        validation = app.validate_respec(current, proposed_attrs, proposed_skills, ["Concussive Shots"], level=12)
        self.assertFalse(any("requires Guns" in item["message"] for item in validation["issues"]))
        self.assertFalse(any(item.get("feat") == "Concussive Shots" for item in validation["issues"]), json.dumps(validation["issues"], indent=2))

        proposed_skills["Crossbows"] = 29
        validation = app.validate_respec(current, proposed_attrs, proposed_skills, ["Concussive Shots"], level=12)
        self.assertTrue(any("requires Crossbows >= 30" in item["message"] for item in validation["issues"]))

    def test_negative_values_are_blocked_even_in_cheat_budget_mode(self):
        current = app.analyze_target(FIXTURES / "jetski_global.dat")
        proposed_attrs = {k: v["base"] for k, v in current["attributes"].items()}
        proposed_skills = {k: v["allocated"] for k, v in current["skills"].items()}
        proposed_attrs["Strength"] = -1
        proposed_skills["Crossbows"] = -1
        validation = app.validate_respec(current, proposed_attrs, proposed_skills, [], level=12, ignore_budget=True)
        self.assertFalse(validation["valid"])
        self.assertTrue(any(item["type"] == "attribute_range" for item in validation["issues"]))
        self.assertTrue(any(item["type"] == "skill_range" for item in validation["issues"]))

    def test_cheat_budget_mode_disables_remaining_point_checks_only(self):
        current = app.analyze_target(FIXTURES / "jetski_global.dat")
        proposed_attrs = {k: v["base"] for k, v in current["attributes"].items()}
        proposed_skills = {k: v["allocated"] for k, v in current["skills"].items()}
        proposed_attrs["Strength"] += 5
        proposed_skills["Crossbows"] += 100

        normal = app.validate_respec(current, proposed_attrs, proposed_skills, [], level=12)
        self.assertFalse(normal["valid"])
        self.assertTrue(any(item["type"] in {"attribute_budget", "skill_budget"} for item in normal["issues"]))

        cheat = app.validate_respec(current, proposed_attrs, proposed_skills, [], level=12, ignore_budget=True)
        self.assertTrue(all(item["type"] not in {"attribute_budget", "skill_budget"} for item in cheat["issues"]))

    def test_crawled_wiki_feat_rules_are_loaded_for_all_category_feats(self):
        self.assertGreaterEqual(len(app.FEAT_RULES), 200)
        self.assertEqual(app.FEAT_RULES["Concussive Shots"]["skills"]["Crossbows"], 30)
        aimed = app.FEAT_RULES["Aimed Shot"]
        self.assertIn({"skills": ["Guns", "Crossbows"], "min": 10}, aimed["any_skill_groups"])
        self.assertEqual(app.FEAT_RULES["Advanced Psi Empathy"]["level_min"], 26)

    def test_wiki_tooltips_loaded_for_attributes_skills_and_feats(self):
        self.assertIn("muscle power", app.TOOLTIPS["attributes"]["Strength"].lower())
        self.assertIn("precision", app.TOOLTIPS["skills"]["Guns"].lower())
        self.assertIn("crossbow", app.TOOLTIPS["feats"]["Concussive Shots"].lower())
        result = app.analyze_target(FIXTURES / "jetski_global.dat")
        self.assertIn("tooltips", result)
        self.assertIn("Strength", result["tooltips"]["attributes"])

    def test_game_rules_catalog_exposes_original_computation_metadata(self):
        rules = app.GAME_RULES
        self.assertEqual(rules["source_references"]["underrail_builder_remake"]["repo"], "cannedbean29/UnderrailBuilderRemake")
        self.assertIn("not vendored", rules["source_references"]["underrail_builder_remake"]["usage_note"].lower())
        self.assertEqual(rules["leveling"]["skill_cap"], "10 + 5 * level")
        self.assertEqual(rules["skills"]["Mechanics"]["related_attribute"], "Intelligence")
        self.assertEqual(rules["skills"]["Lockpicking"]["synergies"], {"Mechanics": 10, "Traps": 10})
        self.assertIn("float32", rules["skill_effective_formula"]["attribute_modifier"])
        self.assertIn("Carry Weight", rules["derived_stats"])

    def test_effective_skill_preview_uses_rule_catalog_for_attribute_mod_and_synergies(self):
        # Mechanics 80 with Intelligence 7: floor(80 * (1 + 3 * 0.085)) = 100.
        self.assertEqual(app.preview_effective_skill("Mechanics", 80, {"Intelligence": 7}, level=12), 100)
        # Lockpicking uses Dexterity plus Mechanics/Traps synergies when the cap has room.
        self.assertEqual(
            app.preview_effective_skill("Lockpicking", 68, {"Dexterity": 5}, level=20, allocated_skills={"Mechanics": 80, "Traps": 35}),
            84,
        )

    def test_analyze_exposes_game_rules_and_effective_preview_audit(self):
        result = app.analyze_target(FIXTURES / "jetski_global.dat")
        self.assertIn("game_rules", result)
        self.assertEqual(result["game_rules"]["skills"]["Crossbows"]["related_attribute"], "Perception")
        self.assertEqual(result["skills"]["Mechanics"]["rules_preview"]["computed_from_allocated"], 55)
        self.assertEqual(result["skills"]["Mechanics"]["effective"], 55)
        self.assertEqual(result["skills"]["Lockpicking"]["rules_preview"]["computed_from_allocated"], 53)

    def test_community_runtime_mod_catalog_is_reference_only(self):
        result = app.analyze_target(FIXTURES / "jetski_global.dat")
        catalog = result["community_mods"]
        self.assertEqual(catalog["source"]["name"], "Diverclaim/UnderrailMods")
        mod_ids = {item["id"] for item in catalog["mods"]}
        self.assertEqual(mod_ids, {"fastforward", "item_weight", "traders_buy_all", "force_restock", "throwing_chance_cap"})
        actions = {item["id"]: item["save_editor_action"] for item in catalog["mods"]}
        self.assertEqual(actions["fastforward"], "experimental-reference-only")
        self.assertEqual(actions["item_weight"], "runtime-patcher-available")
        self.assertEqual(actions["traders_buy_all"], "runtime-patcher-available")
        self.assertEqual(actions["force_restock"], "runtime-patcher-available")
        self.assertEqual(actions["throwing_chance_cap"], "runtime-patcher-available")
        self.assertIn("Runtime IL", catalog["scope_note"])
        self.assertIn("no game assets", catalog["scope_note"])

    def test_inventory_parser_extracts_player_item_slots(self):
        items = inventory_tool.parse_inventory_items(FIXTURES / "jetski_global.dat")
        self.assertGreaterEqual(len(items), 80)
        self.assertEqual(items[0]["path"].lower(), "currency\\stygiancoin")
        self.assertEqual(items[0]["stack"], 3121)
        self.assertEqual(items[2]["path"].lower(), "ammo\\bolt")
        self.assertEqual(items[2]["stack"], 247)

    def test_inventory_weight_breakdown_joins_catalog_and_computes_percentages(self):
        with tempfile.TemporaryDirectory() as td:
            catalog = Path(td) / "item_weights.json"
            catalog.write_text(json.dumps({"items": [
                {"name": "Stygian Coin", "datafile": "currency/stygiancoin.item", "type": "Currency", "weight": 0.0},
                {"name": "Bolt", "datafile": "ammo/bolt.item", "type": "Ammo", "weight": 0.02},
                {"name": "Rathound Regalia", "datafile": "armor/rathoundregalia.item", "type": "Armor", "weight": 8.0},
            ]}), encoding="utf-8")
            result = inventory_tool.analyze_inventory_weight(FIXTURES / "jetski_global.dat", catalog)

        bolt_key = "ammo" + chr(92) + "bolt"
        armor_key = "armor" + chr(92) + "rathoundregalia"
        bolt = next(item for item in result["items"] if item["datafile_key"] == bolt_key)
        self.assertAlmostEqual(bolt["total_weight"], 4.94)
        armor = next(item for item in result["items"] if item["datafile_key"] == armor_key)
        self.assertAlmostEqual(armor["total_weight"], 8.0)
        self.assertAlmostEqual(result["known_weight_total"], 12.94)
        self.assertGreater(armor["percent_of_known_weight"], 60)

    def test_item_weight_catalog_extracts_wiki_infobox_weight_and_datafile(self):
        raw = """{{infobox item
| name        = Adaptive Lens
| type        = Component
| weight      = 0.01
| value       = 350
| datafile    = Components\\Armors\\AdaptiveLens.item
}}"""
        entry = inventory_tool.extract_item_weight_entry("Adaptive Lens", raw)
        self.assertEqual(entry["name"], "Adaptive Lens")
        self.assertEqual(entry["type"], "Component")
        self.assertEqual(entry["datafile"], "Components\\Armors\\AdaptiveLens.item")
        self.assertEqual(entry["datafile_key"], "components\\armors\\adaptivelens")
        self.assertEqual(entry["weight"], 0.01)
        self.assertEqual(entry["value"], 350)

    def test_item_weight_catalog_accepts_wiki_decimal_comma_weights(self):
        raw = r"""{{infobox item
| name        = Cave Hopper Meat
| type        = Food
| weight      = 1,00
| value       = 5
| datafile    = Consumables\Food\CaveHopperMeat.item
}}"""
        entry = inventory_tool.extract_item_weight_entry("Cave Hopper Meat", raw)
        self.assertEqual(entry["name"], "Cave Hopper Meat")
        self.assertEqual(entry["datafile_key"], r"consumables\food\cavehoppermeat")
        self.assertEqual(entry["weight"], 1.0)
        self.assertEqual(entry["value"], 5)

    def test_weight_report_highlights_heavy_known_items_and_unknown_paths(self):
        items = [
            {"slot": 0, "path": "ammo\\bolt", "datafile_key": "ammo\\bolt", "stack": 100},
            {"slot": 1, "path": "armor\\metalarmor", "datafile_key": "armor\\metalarmor", "stack": 1},
            {"slot": 2, "path": "components\\unknownthing", "datafile_key": "components\\unknownthing", "stack": 5},
        ]
        catalog = {
            "ammo\\bolt": {"name": "Bolt", "datafile": "ammo\\bolt.item", "weight": 0.02, "type": "Ammo"},
            "armor\\metalarmor": {"name": "Metal Armor", "datafile": "armor\\metalarmor.item", "weight": 20.0, "type": "Armor"},
        }
        result = inventory_tool.summarize_inventory_weight(items, catalog, target="synthetic")
        self.assertEqual(result["items"][0]["name"], "Metal Armor")
        self.assertAlmostEqual(result["items"][0]["total_weight"], 20.0)
        self.assertGreater(result["items"][0]["percent_of_known_weight"], 90)
        self.assertEqual(result["unknown_weight_items"], 1)
        self.assertEqual(result["unknown_items"][0]["path"], "components\\unknownthing")

    def test_analyze_exposes_equipped_items_read_only(self):
        result = app.analyze_target(FIXTURES / "jetski_global.dat")
        equipped = result["equipped_items"]
        slots = {row["slot"]: row for row in equipped["slots"]}
        self.assertEqual(slots["weapon_1"]["name"], "Jawbone")
        self.assertEqual(slots["weapon_1"]["datafile_key"], "weapons\\rathoundkingcrossbow")
        self.assertEqual(slots["weapon_2"]["name"], "Jackknife")
        self.assertEqual(slots["belt"]["name"], "Lifting Belt")
        self.assertTrue(slots["armor"].get("equipped"))
        self.assertIn("read-only", equipped["notes"][0].lower())

    def test_damage_estimates_include_skill_scalars_psi_and_equipped_weapon_damage(self):
        result = app.analyze_target(FIXTURES / "jetski_global.dat")
        estimates = result["damage_estimates"]
        crossbows = estimates["weapon_skill_scalars"]["Crossbows"]
        self.assertEqual(crossbows["effective_skill"], result["skills"]["Crossbows"]["effective"])
        self.assertAlmostEqual(crossbows["normal_weapon_damage_multiplier"], 1 + result["skills"]["Crossbows"]["effective"] * 0.7 / 100)
        neural = next(row for row in estimates["psi_abilities"] if row["name"] == "Neural Overload")
        thought = result["skills"]["Thought Control"]["effective"]
        self.assertAlmostEqual(neural["damage"][0]["min"], 10 + 0.2 * thought)
        self.assertAlmostEqual(neural["damage"][0]["max"], 11 + 0.4 * thought)
        jawbone = next(row for row in estimates["equipped_weapon_estimates"] if row["name"] == "Jawbone")
        crossbow_eff = result["skills"]["Crossbows"]["effective"]
        self.assertEqual(jawbone["base_damage"][0]["min"], 30)
        self.assertAlmostEqual(jawbone["estimated_damage"][0]["min"], round(30 * (1 + 0.7 * crossbow_eff / 100), 1))

    def test_analyze_exposes_inventory_weight_breakdown_read_only(self):
        result = app.analyze_target(FIXTURES / "jetski_global.dat")
        breakdown = result["inventory_weight"]
        self.assertEqual(breakdown["target"], str(FIXTURES / "jetski_global.dat"))
        self.assertGreaterEqual(breakdown["item_count"], 80)
        self.assertGreater(breakdown["known_weight_total"], 80)
        self.assertIn("Read-only", breakdown["notes"][0])
        self.assertTrue(any(row["total_weight"] is not None for row in breakdown["items"]))
        self.assertTrue(any(row["category"] == "ammo" for row in breakdown["categories"]))

    def test_runtime_mod_steam_library_parser_finds_underrail_install(self):
        text = '"libraryfolders" { "2" { "path" "H:\\\\SteamLibrary" } }'
        paths = runtime_mods.parse_steam_library_paths(text)
        self.assertEqual(str(paths[0]), "H:\\SteamLibrary")

    def test_runtime_mod_game_dir_validation_requires_underrail_exe(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                runtime_mods.resolve_game_dir(td)

    def test_runtime_process_status_locks_when_underrail_is_running(self):
        original = runtime_mods.underrail_process_running
        try:
            runtime_mods.underrail_process_running = lambda: True
            status = runtime_mods.runtime_process_status()
        finally:
            runtime_mods.underrail_process_running = original

        self.assertTrue(status["underrail_running"])
        self.assertTrue(status["locked"])
        self.assertIn("locked", status["message"])

    def test_faction_relation_visualizer_extracts_player_relation(self):
        payload = (
            b"\x01\x0acampHathor\x0acampHathor\x0bCamp Hathor"
            b"\x00\x00\x00"
            b"\x06player\x00\x00\x00\x00\xff\xff\xff\xff"
            b"\x0crathoundPack\x02\x00\x00\x00\xff\xff\xff\xff"
        )
        rows = app.find_faction_relations_in_payload(payload)
        camp = next(row for row in rows if row["id"] == "campHathor")

        self.assertEqual(camp["name"], "Camp Hathor")
        self.assertEqual(camp["player_relation"]["value"], 0)
        self.assertIn("hostile", camp["player_relation"]["label"].lower())

    def test_faction_relation_delta_finds_changed_hostility(self):
        baseline_payload = (
            b"\x01\x0acampHathor\x0acampHathor\x0bCamp Hathor"
            b"\x00\x00\x00"
            b"\x06player\x02\x00\x00\x00\xff\xff\xff\xff"
        )
        current_payload = (
            b"\x01\x0acampHathor\x0acampHathor\x0bCamp Hathor"
            b"\x00\x00\x00"
            b"\x06player\x00\x00\x00\x00\xff\xff\xff\xff"
        )
        baseline = app.find_faction_relations_in_payload(baseline_payload)
        current = app.find_faction_relations_in_payload(current_payload)
        deltas = app.faction_relation_deltas(current, baseline)

        self.assertEqual(deltas, [{
            "id": "campHathor",
            "name": "Camp Hathor",
            "baseline_value": 2,
            "baseline_label": "Friendly / non-hostile",
            "current_value": 0,
            "current_label": "Likely hostile",
            "current_value_offset": current[0]["player_relation"]["value_offset"],
        }])

    def test_area_marker_extractor_decodes_prefix_area_and_kill_markers(self):
        def rec(text: str, value: int = 1) -> bytes:
            raw = text.encode("ascii")
            return b"\x06\x01\x02\x03\x04" + bytes([len(raw)]) + raw + bytes([value]) + b"\x05\x00\x00"

        payload = (
            rec("loc_cvw47_allHathoriansKilled", 1)
            + rec("frag_dun_wasteWater_killedBoss", 1)
            + rec("npc_coltrane_met", 1)
        )
        result = app.extract_area_markers_from_payload(payload)
        texts = {m["text"]: m for m in result["markers"]}

        self.assertEqual(texts["loc_cvw47_allHathoriansKilled"]["prefix"], "loc")
        self.assertEqual(texts["loc_cvw47_allHathoriansKilled"]["area_id"], "cvw47")
        self.assertIn("Isaac", texts["loc_cvw47_allHathoriansKilled"]["area_label"])
        self.assertEqual(texts["frag_dun_wasteWater_killedBoss"]["area_id"], "dun_wasteWater")
        self.assertTrue(any(h["id"] == "campHathor" for h in texts["loc_cvw47_allHathoriansKilled"]["mapped_factions"]))
        self.assertTrue(any(h["id"] == "dun_wasteWater" for h in texts["frag_dun_wasteWater_killedBoss"]["mapped_factions"]))
        self.assertTrue(any(m["category"] == "kill/death marker" for m in result["kill_markers"]))

    def test_runtime_mod_latest_save_backup_uses_repo_local_ignored_folder(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "Saves"
            backup_root = Path(td) / "runtime_safety_backups"
            older = root / "Older"
            newer = root / "Newest"
            older.mkdir(parents=True)
            newer.mkdir()
            (older / "global.dat").write_bytes(b"old")
            (newer / "global.dat").write_bytes(b"new")
            (newer / "info.dat").write_text("metadata")
            os.utime(older / "global.dat", (1000, 1000))
            os.utime(newer / "global.dat", (2000, 2000))

            result = runtime_mods.backup_latest_save(root, backup_root)

            self.assertTrue(result["created"])
            self.assertEqual(Path(result["source"]).name, "Newest")
            destination = Path(result["destination"])
            self.assertTrue(str(destination).startswith(str(backup_root)))
            self.assertEqual((destination / "global.dat").read_bytes(), b"new")
            self.assertEqual((destination / "info.dat").read_text(), "metadata")

    def test_level_requirement_validation_uses_crawled_rules(self):
        current = app.analyze_target(FIXTURES / "jetski_global.dat")
        attrs = {k: v["base"] for k, v in current["attributes"].items()}
        skills = {k: v["allocated"] for k, v in current["skills"].items()}
        skills["Thought Control"] = 100
        validation = app.validate_respec(current, attrs, skills, ["Advanced Psi Empathy", "Psi Empathy"], level=12, ignore_budget=True)
        self.assertFalse(validation["valid"])
        self.assertTrue(any("requires level >= 26" in item["message"] for item in validation["issues"]))

    def test_feat_records_are_read_from_save_payload(self):
        jetski = app.read_feat_records(FIXTURES / "jetski_global.dat")
        ids = [r["feat_id"] for r in jetski]
        self.assertIn("fastmetabolism", ids)
        self.assertIn("concussiveshots", ids)
        self.assertIn("versatility", ids)

        assault = app.read_feat_records(FIXTURES / "assault_global.dat")
        assault_ids = [r["feat_id"] for r in assault]
        self.assertIn("fastmetabolism", assault_ids)
        self.assertNotIn("concussiveshots", assault_ids)

    def test_feat_replacement_changes_clone_only_and_supports_different_length_ids(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "SourceSave"
            src.mkdir()
            original = (FIXTURES / "assault_global.dat").read_bytes()
            (src / "global.dat").write_bytes(original)
            rec = next(r for r in app.read_feat_records(src) if r["feat_id"] == "fastmetabolism")
            result = app.create_respec_copy(
                src,
                "SourceSave-FeatRespec",
                feats=["Conditioning", "Pack Rathound", "Disassemble", "Expanded Psi Capacitance", "Psi Empathy"],
                ignore_budget=True,
                feat_replacements=[{"offset": rec["offset"], "old_id": "fastmetabolism", "new_id": "conditioning"}],
            )
            self.assertEqual((src / "global.dat").read_bytes(), original)
            dest_ids = [r["feat_id"] for r in app.read_feat_records(Path(result["destination"]))]
            self.assertIn("conditioning", dest_ids)
            self.assertNotIn("fastmetabolism", dest_ids)

    def test_list_save_folders_supports_alpha_and_modified_sort(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name, ts in [("Bravo", 2000), ("alpha", 3000), ("Charlie", 1000)]:
                folder = root / name
                folder.mkdir()
                dat = folder / "global.dat"
                dat.write_bytes(b"dummy")
                os.utime(dat, (ts, ts))
                os.utime(folder, (ts, ts))
            alpha = app.list_save_folders(root, sort="alpha")
            self.assertEqual([x["name"] for x in alpha], ["alpha", "Bravo", "Charlie"])
            newest = app.list_save_folders(root, sort="modified")
            self.assertEqual([x["name"] for x in newest], ["alpha", "Bravo", "Charlie"])
            oldest = app.list_save_folders(root, sort="modified_asc")
            self.assertEqual([x["name"] for x in oldest], ["Charlie", "Bravo", "alpha"])
            self.assertIn("modified", newest[0])

    def test_create_respec_copy_never_modifies_source_dat(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "SourceSave"
            src.mkdir()
            original = (FIXTURES / "assault_global.dat").read_bytes()
            (src / "global.dat").write_bytes(original)
            (src / "info.dat").write_text("dummy")
            result = app.create_respec_copy(
                src,
                "SourceSave-Respec",
                attrs={"Strength": 6, "Constitution": 7},
                skills={"Crossbows": 35, "Hacking": 25},
                level=6,
                feats=["Fast Metabolism", "Pack Rathound", "Disassemble", "Expanded Psi Capacitance", "Psi Empathy"],
            )
            self.assertEqual((src / "global.dat").read_bytes(), original)
            dest = Path(result["destination"])
            self.assertTrue((dest / "global.dat").is_file())
            self.assertTrue(result["backup_created"])
            changed = app.analyze_target(dest)
            self.assertEqual(changed["attributes"]["Strength"]["base"], 6)
            self.assertEqual(changed["attributes"]["Constitution"]["base"], 7)
            self.assertEqual(changed["skills"]["Crossbows"]["allocated"], 35)
            self.assertEqual(changed["skills"]["Hacking"]["allocated"], 25)


if __name__ == "__main__":
    unittest.main()
