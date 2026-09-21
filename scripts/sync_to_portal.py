"""Copy this app into the JSA Admin Portal (jsa-admin-portal/apps/cost_of_carry).

The portal runs every dashboard in one Python process, so a module name is imported
once and shared by every page. grain_seasonal ships its own massive_api.py and
cme_feeder_cattle its own snowflake_db.py; whichever page loads first would otherwise
serve its copy to the others. Every local module is therefore renamed with a coc_
prefix in the portal copy, and imports are rewritten to alias back to the original
names so the page code is unchanged.

Other portal adjustments:
  * st.set_page_config is removed — Home.py makes the one allowed call.
  * The page's own directory is put on sys.path (st.Page scripts don't get it).
  * SNOWFLAKE_SCHEMA is dropped from the secrets bridge (see the portal's CLAUDE.md);
    coc_snowflake_db queries COST_OF_CARRY.<table> fully qualified anyway.

Usage:  python scripts/sync_to_portal.py [path-to-portal-repo]
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
PORTAL = Path(sys.argv[1]) if len(sys.argv) > 1 else SRC.parent / "jsa-home-page"
DEST = PORTAL / "apps" / "cost_of_carry"

MODULES = ["massive_api", "storage_rates", "interest_rates", "vsr_tracker",
           "history_archive", "snowflake_db", "seasonal_pattern",
           "snapshot_copy", "ethanol_grind", "stocks_use"]
DATA_FILES = ["fed_funds_dff.csv", "futures_history_archive.csv",
              "ams_ethanol_weekly.csv", "ams_plant_corn.csv"]
ASSETS = ["logo-50yr.png", "jsa_favicon.png", "logo-full.png"]


def rewrite_imports(text: str) -> str:
    for mod in MODULES:
        text = re.sub(rf"^(\s*)import {mod}$", rf"\1import coc_{mod} as {mod}", text, flags=re.M)
        text = re.sub(rf"^(\s*)from {mod} import", rf"\1from coc_{mod} import", text, flags=re.M)
    return text


def portal_app(text: str) -> str:
    text = rewrite_imports(text)

    page_config = re.search(r"^st\.set_page_config\(\n(?:.*\n)*?\)\n", text, flags=re.M)
    if not page_config:
        raise SystemExit("set_page_config block not found — update sync_to_portal.py")
    text = text.replace(
        page_config.group(0),
        "# st.set_page_config removed — the JSA Admin Portal shell (Home.py) makes the\n"
        "# single set_page_config call allowed per multi-page run.\n",
    )

    anchor = "HERE = Path(__file__).parent\n"
    if anchor not in text:
        raise SystemExit("HERE anchor not found — update sync_to_portal.py")
    text = text.replace("import base64\n", "import base64\nimport sys\n", 1)
    first_local = min(text.index(f"coc_{m}") for m in MODULES if f"coc_{m}" in text)
    line_start = text.rfind("\n", 0, first_local) + 1
    text = (text[:line_start]
            + "# st.Page scripts don't get their own directory on sys.path.\n"
              "sys.path.insert(0, str(Path(__file__).parent))\n\n"
            + text[line_start:])

    bridged = '"SNOWFLAKE_DATABASE", "SNOWFLAKE_SCHEMA"'
    if bridged in text:
        text = text.replace(bridged, '"SNOWFLAKE_DATABASE"')
    if '"SNOWFLAKE_SCHEMA"' in text.split("def asset", 1)[0]:
        raise SystemExit("SNOWFLAKE_SCHEMA still bridged — must never be set in the portal")
    return text


def main():
    if not (PORTAL / "Home.py").exists():
        raise SystemExit(f"No portal at {PORTAL}")
    DEST.mkdir(parents=True, exist_ok=True)
    (DEST / "data").mkdir(exist_ok=True)
    (DEST / "assets").mkdir(exist_ok=True)

    app = portal_app((SRC / "app.py").read_text(encoding="utf-8"))
    (DEST / "app.py").write_text(app, encoding="utf-8")
    for mod in MODULES:
        text = rewrite_imports((SRC / f"{mod}.py").read_text(encoding="utf-8"))
        (DEST / f"coc_{mod}.py").write_text(text, encoding="utf-8")
    stale = DEST / "massive_api.py"  # pre-rename copy from earlier syncs
    if stale.exists():
        stale.unlink()
    for name in DATA_FILES:
        source = SRC / "data" / name
        if source.exists():
            shutil.copy2(source, DEST / "data" / name)
    for name in ASSETS:
        if (SRC / "assets" / name).exists():
            shutil.copy2(SRC / "assets" / name, DEST / "assets" / name)
    print(f"synced into {DEST}")


if __name__ == "__main__":
    main()
