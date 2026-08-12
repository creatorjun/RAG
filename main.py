from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = PROJECT_ROOT / "src"


def main(argv: Sequence[str] | None = None) -> int:
    """Launch the desktop GUI directly from the source checkout."""
    source_path = str(SOURCE_ROOT)
    if source_path not in sys.path:
        sys.path.insert(0, source_path)

    from enterprise_rag.bootstrap import gui_main

    arguments = list(sys.argv[1:] if argv is None else argv)
    if "--project-root" not in arguments:
        arguments = ["--project-root", str(PROJECT_ROOT), *arguments]
    return gui_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
