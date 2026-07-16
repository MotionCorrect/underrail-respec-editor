import json
import os
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from underrail_respec_editor import web_app as app

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
