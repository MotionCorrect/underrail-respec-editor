"""Portable Windows entrypoint for the bundled Underrail Respec Editor."""
from __future__ import annotations

from underrail_respec_editor.web_app import main as web_main


def main() -> None:
    web_main(["8765", "--open-browser"])


if __name__ == "__main__":
    main()
