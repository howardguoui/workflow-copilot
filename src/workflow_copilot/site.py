"""Build the static demo (docs/, served by GitHub Pages).

The page runs a small model in the visitor's browser (WebLLM) on the same workflow notes, compiled by
web/compile.js. It also shows transcripts recorded with the full Microsoft Agent Framework runtime
(`workflow-copilot record`), which are real runs, never written by hand.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .cli import workflow_notes
from .tools import DATA, MODELS, planner_spec

WEB = Path(__file__).resolve().parents[2] / "web"


def build(vault: Path, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    for f in sorted(WEB.iterdir()):
        if f.is_file():
            shutil.copyfile(f, out / f.name)
    (out / ".nojekyll").write_text("", encoding="utf-8")
    shutil.rmtree(out / "vault", ignore_errors=True)
    shutil.copytree(vault, out / "vault", ignore=shutil.ignore_patterns(".obsidian", ".trash"))
    manifest = {
        "workflows": [p.relative_to(vault).as_posix() for p in workflow_notes(vault)],
        "notes": sorted(p.relative_to(vault).as_posix() for p in vault.rglob("*.md")),
        "planner": planner_spec(),
        "models": list(MODELS),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    shutil.copyfile(DATA / "filings_answers.json", out / "filings_answers.json")
    if not (out / "transcripts.json").exists():
        (out / "transcripts.json").write_text(json.dumps({"chats": []}), encoding="utf-8")
    return out / "index.html"
