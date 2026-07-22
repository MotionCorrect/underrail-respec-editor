"""Runtime Underrail assembly mod orchestration.

This module is deliberately separate from save editing. Runtime mods patch the
installed game assembly, so every write must be explicit and backup-first.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parents[1]
PATCHER_PROJECT = REPO_ROOT / "runtime-patcher" / "runtime-patcher.csproj"
UNDERAIL_APP_ID = "250520"
DEFAULT_SAVES_DIR = Path.home() / "Documents" / "My Games" / "Underrail" / "Saves"
RUNTIME_SAFETY_BACKUP_DIR = REPO_ROOT / "runtime_safety_backups"

COMMON_INSTALLS = [
    Path(r"C:\Program Files (x86)\Steam\steamapps\common\Underrail"),
    Path(r"C:\Program Files\Steam\steamapps\common\Underrail"),
    Path(r"H:\SteamLibrary\steamapps\common\Underrail"),
]


def _msys_to_windows(path: str) -> Path:
    if re.match(r"^/[a-zA-Z]/", path):
        return Path(path[1] + ":" + path[2:].replace("/", "\\"))
    return Path(path)


def parse_steam_library_paths(text: str) -> List[Path]:
    paths = []
    for match in re.finditer(r'"path"\s+"([^"]+)"', text):
        paths.append(Path(match.group(1).replace("\\\\", "\\")))
    return paths


def steam_library_config_paths() -> List[Path]:
    return [
        Path(r"C:\Program Files (x86)\Steam\steamapps\libraryfolders.vdf"),
        Path(r"C:\Program Files\Steam\steamapps\libraryfolders.vdf"),
        Path.home() / "AppData" / "Local" / "Steam" / "steamapps" / "libraryfolders.vdf",
    ]


def discover_underrail_installs() -> List[str]:
    candidates: List[Path] = []
    candidates.extend(COMMON_INSTALLS)
    for library_config in steam_library_config_paths():
        if not library_config.is_file():
            continue
        for library in parse_steam_library_paths(library_config.read_text(encoding="utf-8", errors="ignore")):
            manifest = library / "steamapps" / f"appmanifest_{UNDERAIL_APP_ID}.acf"
            if manifest.is_file():
                text = manifest.read_text(encoding="utf-8", errors="ignore")
                m = re.search(r'"installdir"\s+"([^"]+)"', text)
                install_dir = m.group(1) if m else "Underrail"
                candidates.append(library / "steamapps" / "common" / install_dir)
    out = []
    seen = set()
    for candidate in candidates:
        if (candidate / "underrail.exe").is_file():
            resolved = str(candidate.resolve())
            if resolved.lower() not in seen:
                out.append(resolved)
                seen.add(resolved.lower())
    return out


def resolve_game_dir(game_dir: Optional[str] = None) -> Path:
    if game_dir:
        path = _msys_to_windows(game_dir)
        if (path / "underrail.exe").is_file():
            return path
        raise ValueError(f"Underrail install folder must contain underrail.exe: {path}")
    installs = discover_underrail_installs()
    if installs:
        return Path(installs[0])
    raise ValueError("Could not auto-detect Underrail install. Select the folder containing underrail.exe.")


def patcher_command() -> List[str]:
    if not PATCHER_PROJECT.is_file():
        raise ValueError(f"Runtime patcher project not found: {PATCHER_PROJECT}")
    return ["dotnet", "run", "--project", str(PATCHER_PROJECT), "-c", "Release", "--"]


def run_patcher(command: str, game_dir: Optional[str] = None, **options: Any) -> Dict[str, Any]:
    resolved = resolve_game_dir(game_dir)
    args = patcher_command() + [command, "--game-dir", str(resolved)]
    for key, value in options.items():
        if value is None or value is False:
            continue
        flag = "--" + key.replace("_", "-")
        args.append(flag)
        if value is not True:
            args.append(str(value))
    proc = subprocess.run(args, cwd=str(REPO_ROOT), text=True, capture_output=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip())
    stdout = proc.stdout.strip()
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {"ok": True, "text": stdout, "game_dir": str(resolved)}


def underrail_process_running() -> bool:
    """Best-effort Windows process check used before live assembly writes."""
    if os.name != "nt":
        return False
    try:
        proc = subprocess.run(
            ["tasklist.exe", "/FI", "IMAGENAME eq underrail.exe"],
            text=True,
            capture_output=True,
            timeout=10,
        )
    except Exception:
        return False
    return "underrail.exe" in (proc.stdout or "").lower()


def ensure_game_not_running() -> None:
    if underrail_process_running():
        raise RuntimeError("Underrail is running. Close the game before patching or rolling back underrail.exe.")


def newest_save_folder(saves_dir: Path = DEFAULT_SAVES_DIR) -> Optional[Path]:
    if not saves_dir.is_dir():
        return None
    candidates = [p for p in saves_dir.iterdir() if p.is_dir() and (p / "global.dat").is_file()]
    if not candidates:
        return None

    def newest_file_mtime(folder: Path) -> float:
        newest = folder.stat().st_mtime
        for child in folder.iterdir():
            if child.is_file():
                newest = max(newest, child.stat().st_mtime)
        return newest

    return max(candidates, key=newest_file_mtime)


def backup_latest_save(
    saves_dir: Path = DEFAULT_SAVES_DIR,
    backup_root: Path = RUNTIME_SAFETY_BACKUP_DIR,
) -> Dict[str, Any]:
    """Copy the newest save folder into a repo-local ignored safety area."""
    latest = newest_save_folder(saves_dir)
    if latest is None:
        return {
            "created": False,
            "reason": f"No Underrail save folder with global.dat found under {saves_dir}",
            "saves_dir": str(saves_dir),
        }
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe_name = re.sub(r"[^A-Za-z0-9_. -]+", "_", latest.name).strip() or "Save"
    destination = backup_root / "latest-save-before-runtime-patch" / f"{stamp}-{safe_name}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(latest, destination)
    return {
        "created": True,
        "source": str(latest),
        "destination": str(destination),
        "files": sum(1 for p in destination.rglob("*") if p.is_file()),
    }


def scan_runtime_mods(game_dir: Optional[str] = None) -> Dict[str, Any]:
    result = run_patcher("scan", game_dir)
    result["available_installs"] = discover_underrail_installs()
    return result


def patch_runtime_mods(
    game_dir: Optional[str],
    mods: List[str],
    cap: float = 0.99,
    weight_multiplier: float = 0.1,
    dry_run: bool = False,
) -> Dict[str, Any]:
    if not dry_run:
        ensure_game_not_running()
    latest_save_backup = None if dry_run else backup_latest_save()
    result = run_patcher(
        "patch",
        game_dir,
        mods=",".join(mods),
        cap=cap,
        weight_multiplier=weight_multiplier,
        dry_run=dry_run,
    )
    if latest_save_backup is not None:
        result["latest_save_backup"] = latest_save_backup
    return result


def patch_throwing_chance_cap(game_dir: Optional[str], cap: float, dry_run: bool = False) -> Dict[str, Any]:
    return patch_runtime_mods(game_dir, ["throwing_chance_cap"], cap=cap, dry_run=dry_run)


def rollback_runtime_patch(game_dir: Optional[str], backup: str) -> Dict[str, Any]:
    ensure_game_not_running()
    return run_patcher("rollback", game_dir, backup=backup)
