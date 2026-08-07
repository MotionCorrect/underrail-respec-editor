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
        self.assertIn("disabled={hostedStaticMode || !gameDir || runtimeLocked}", page)

    def test_frontend_has_faction_relation_visualizer(self):
        page = (FRONTEND / "app" / "page.tsx").read_text(encoding="utf-8")
        self.assertIn("Faction relation visualizer", page)
        self.assertIn("faction_relations", page)
        self.assertIn("Changed to hostile versus", page)
        self.assertIn("Raw player relation code", page)
        self.assertIn("faction_relation_comparison", page)
        self.assertIn("Area clear / kill markers", page)
        self.assertIn("area_markers", page)
        self.assertIn("value_byte", page)
        self.assertIn("Faction hints", page)
        self.assertIn("mapped_factions", page)
    def test_frontend_has_inventory_weight_breakdown_panel(self):
        page = (FRONTEND / "app" / "page.tsx").read_text(encoding="utf-8")
        css = (FRONTEND / "app" / "globals.css").read_text(encoding="utf-8")
        self.assertIn("InventoryWeightPanel", page)
        self.assertIn("Inventory weight breakdown - read only", page)
        self.assertIn("known weight", page)
        self.assertIn("Heaviest item stacks", page)
        self.assertIn("Category distribution", page)
        self.assertIn("inventory_weight", page)
        self.assertIn("inventoryWeightPanel", css)
        self.assertIn("heavyRow", css)

    def test_frontend_inventory_weight_panel_has_tabs(self):
        page = (FRONTEND / "app" / "page.tsx").read_text(encoding="utf-8")
        css = (FRONTEND / "app" / "globals.css").read_text(encoding="utf-8")
        self.assertIn("inventoryWeightTab", page)
        self.assertIn("setInventoryWeightTab", page)
        self.assertIn("Summary", page)
        self.assertIn("Categories", page)
        self.assertIn("Heaviest stacks", page)
        self.assertIn("Unknown weights", page)
        self.assertIn("weightTabBar", css)
        self.assertIn("weightTab", css)
        self.assertIn("weightTab active", page)

    def test_frontend_has_top_level_workspace_tabs(self):
        page = (FRONTEND / "app" / "page.tsx").read_text(encoding="utf-8")
        css = (FRONTEND / "app" / "globals.css").read_text(encoding="utf-8")
        self.assertIn("type MainTab", page)
        self.assertIn("mainTab", page)
        self.assertIn("setMainTab", page)
        self.assertIn("Character editing", page)
        self.assertIn("Inventory", page)
        self.assertIn("Faction hostilities", page)
        self.assertIn("QoL patching", page)
        self.assertIn("mainTabBar", css)
        self.assertIn("mainTabButton", css)
        self.assertIn("mainTab active", page)
        self.assertIn("mainTab === 'character'", page)
        self.assertIn("mainTab === 'inventory'", page)
        self.assertIn("mainTab === 'factions'", page)
        self.assertIn("mainTab === 'qol'", page)

    def test_frontend_shows_equipped_items_and_damage_estimates(self):
        page = (FRONTEND / "app" / "page.tsx").read_text(encoding="utf-8")
        css = (FRONTEND / "app" / "globals.css").read_text(encoding="utf-8")
        self.assertIn("EquippedItemsPanel", page)
        self.assertIn("Current equipped gear - read only", page)
        self.assertIn("DamageEstimatesPanel", page)
        self.assertIn("Skill damage estimates / PSI ability preview", page)
        self.assertIn("equipped_items", page)
        self.assertIn("damage_estimates", page)
        self.assertIn("equipmentGrid", css)
        self.assertIn("damageCard", css)

    def test_frontend_links_attributes_skills_feats_items_and_damage_names_to_wiki(self):
        page = (FRONTEND / "app" / "page.tsx").read_text(encoding="utf-8")
        css = (FRONTEND / "app" / "globals.css").read_text(encoding="utf-8")
        self.assertIn("function wikiUrl", page)
        self.assertIn("function WikiLink", page)
        self.assertIn("<WikiLink title={name}", page)
        self.assertIn("wikiTitle={f}", page)
        self.assertIn("wikiTitle={row.name}", page)
        self.assertIn("wikiItemLink", page)
        self.assertIn('target="_blank"', page)
        self.assertIn('rel="noreferrer"', page)
        self.assertIn("wikiGenericLink", css)

    def test_frontend_inventory_has_category_filter_and_cube_tiles(self):
        page = (FRONTEND / "app" / "page.tsx").read_text(encoding="utf-8")
        css = (FRONTEND / "app" / "globals.css").read_text(encoding="utf-8")
        self.assertIn("selectedInventoryCategory", page)
        self.assertIn("setSelectedInventoryCategory", page)
        self.assertIn("filteredCategoryItems", page)
        self.assertIn("ItemCube", page)
        self.assertIn("inventoryCubeGrid", page)
        self.assertIn("cubeOverlay", page)
        self.assertIn("CategoryFilterBar", page)
        self.assertIn("inventoryCube", css)
        self.assertIn("cubeOverlay", css)
        self.assertIn("categoryFilterChip", css)

    def test_frontend_has_static_github_pages_upload_analyzer(self):
        page = (FRONTEND / "app" / "page.tsx").read_text(encoding="utf-8")
        css = (FRONTEND / "app" / "globals.css").read_text(encoding="utf-8")
        self.assertIn("StaticUploadAnalyzer", page)
        self.assertIn("Static GitHub Pages analyzer - no local API required", page)
        self.assertIn("JSZip", page)
        self.assertIn("DecompressionStream", page)
        self.assertIn("/data/item_weights.json", page)
        self.assertIn("webkitdirectory", page)
        self.assertIn("MAX_STATIC_UPLOAD_BYTES", page)
        self.assertIn("MAX_STATIC_ZIP_ENTRIES", page)
        self.assertIn("hostedStaticMode", page)
        self.assertIn("GitHub Pages static mode: upload analysis only", page)
        self.assertIn("staticUploadPanel", css)
        self.assertTrue((FRONTEND / "public" / "data" / "item_weights.json").is_file())


if __name__ == "__main__":
    unittest.main()
