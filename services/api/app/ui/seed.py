"""Load template files into the catalogue as published platform templates.

    uv run python -m app.ui.seed ../../design-showcase/templates

Safe to run again: a file whose version is already stored is skipped; a higher version is stored
as a new version and published. This is an operator command; it does not go through the web API.
"""

import sys
from pathlib import Path

from app.db.tenant_session import platform_session
from app.services.org import Conflict, Invalid
from app.ui import service


def seed_directory(directory: Path, *, engine=None) -> dict[str, list[str]]:
    report: dict[str, list[str]] = {"imported": [], "skipped": [], "failed": []}
    for path in sorted(directory.glob("*.json")):
        try:
            with platform_session(engine) as db:
                template = service.import_platform_template(
                    db, path.read_text(encoding="utf-8"), publish=True
                )
            report["imported"].append(f"{template.template_key} {template.version}")
        except Conflict:
            report["skipped"].append(path.name)
        except Invalid as exc:
            report["failed"].append(f"{path.name}: {exc}")
    return report


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or not Path(args[0]).is_dir():
        print("usage: python -m app.ui.seed <directory with template .json files>", file=sys.stderr)
        return 2
    report = seed_directory(Path(args[0]))
    for kind, items in report.items():
        print(f"{kind}: {len(items)}" + "".join(f"\n  {i}" for i in items))
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
