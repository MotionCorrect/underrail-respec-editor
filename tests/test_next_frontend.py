import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class NextFrontendTests(unittest.TestCase):
    def test_next_frontend_files_exist(self):
        self.assertTrue((FRONTEND / "package.json").is_file())
        self.assertTrue((FRONTEND / "app" / "page.tsx").is_file())
        self.assertTrue((FRONTEND / "app" / "globals.css").is_file())

    def test_frontend_has_visible_tooltip_panel_not_only_native_title(self):
        page = (FRONTEND / "app" / "page.tsx").read_text(encoding="utf-8")
        self.assertIn("InfoPanel", page)
        self.assertIn("onMouseEnter", page)
        self.assertIn("hoverInfo", page)

    def test_frontend_supports_save_sort_modes(self):
        page = (FRONTEND / "app" / "page.tsx").read_text(encoding="utf-8")
        self.assertIn("modified", page)
        self.assertIn("modified_asc", page)
        self.assertIn("alpha", page)

    def test_frontend_surfaces_community_mod_references_as_reference_only(self):
        page = (FRONTEND / "app" / "page.tsx").read_text(encoding="utf-8")
        self.assertIn("External modding references", page)
        self.assertIn("runtime IL-hook reference", page)
        self.assertIn("scan, dry-run, backup, and rollback", page)

    def test_frontend_has_runtime_mod_expert_tab_and_backup_warning(self):
        page = (FRONTEND / "app" / "page.tsx").read_text(encoding="utf-8")
        self.assertIn("Runtime mods - expert live patch tab", page)
        self.assertIn("Backup and patch", page)
        self.assertIn("underrail_respec_backups", page)
        self.assertIn("runtime_safety_backups", page)
        self.assertIn("Fastforward (experimental; do not use yet)", page)
        self.assertIn("value={weightMultiplier}", page)
        self.assertIn("useState(0.1)", page)
        self.assertIn("Runtime mod controls are locked", page)
        self.assertIn("/api/runtime/status", page)
        self.assertIn("window.setInterval", page)
        self.assertIn("disabled={!gameDir || runtimeLocked}", page)


if __name__ == "__main__":
    unittest.main()
