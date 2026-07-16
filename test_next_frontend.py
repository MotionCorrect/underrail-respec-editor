import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
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


if __name__ == "__main__":
    unittest.main()
