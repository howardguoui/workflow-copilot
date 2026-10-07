"""workflow-copilot: turn an Obsidian workflow note into a chatbot.

workflow-copilot compile "vault/GPU Sizing Assistant.md"      # show the agent the note defines
workflow-copilot chat "vault/GPU Sizing Assistant.md"         # chat in the terminal (Ollama by default)
workflow-copilot serve "vault/GPU Sizing Assistant.md"        # Microsoft 365 Agents SDK endpoint on :3978
workflow-copilot record vault                                 # answer every note's examples, save transcripts
workflow-copilot site                                         # build the static demo in docs/
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from .note import compile_note

DEFAULT_BASE_URL = os.getenv("COPILOT_BASE_URL", "http://localhost:11434/v1")
DEFAULT_MODEL = os.getenv("COPILOT_MODEL", "qwen3:8b")


def workflow_notes(vault: Path) -> list[Path]:
    """Workflow notes in the vault folder, by their `order` property, then name."""
    from .note import split_frontmatter

    found = []
    for p in sorted(vault.glob("*.md")):
        meta, _ = split_frontmatter(p.read_text(encoding="utf-8"))
        if meta.get("type") == "workflow":
            found.append((int(meta.get("order", 999)), p.name, p))
    return [p for _, _, p in sorted(found)]


def _client(args):
    from .agent import make_client

    return make_client(args.base_url, args.model)


async def _chat(args) -> None:
    from .agent import WorkflowCopilot

    note = Path(args.note)
    compiled = compile_note(note, args.vault or note.parent)
    bot = WorkflowCopilot(compiled, args.vault or note.parent, _client(args))
    wf = compiled["workflow"]
    print(f"{wf['name']} ({args.model}). Try: {wf['examples'][0] if wf['examples'] else ''}\nEmpty line to quit.")
    while True:
        try:
            text = input("\nyou> ").strip()
        except EOFError:
            break
        if not text:
            break
        start = len(bot.calls)
        reply = await bot.ask(text)
        for c in bot.calls[start:]:
            print(f"  [tool] {c['tool']}({json.dumps(c['arguments'])})")
        print(f"bot> {reply}")


async def _record(args) -> None:
    from .agent import WorkflowCopilot

    vault = Path(args.vault)
    chats = []
    for note in workflow_notes(vault):
        compiled = compile_note(note, vault)
        for question in compiled["workflow"]["examples"]:
            bot = WorkflowCopilot(compiled, vault, _client(args))
            answer = await bot.ask(question)
            chats.append(
                {"workflow": compiled["workflow"]["name"], "question": question, "calls": bot.calls, "answer": answer}
            )
            print(f"[{compiled['workflow']['name']}] {question}\n  tools: {[c['tool'] for c in bot.calls]}\n")
    out = {
        "recorded_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "model": args.model,
        "runtime": f"Microsoft Agent Framework {version('agent-framework-core')}",
        "chats": chats,
    }
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"Wrote {path} ({len(chats)} conversations)")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="workflow-copilot", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def model_args(p):
        p.add_argument("--base-url", default=DEFAULT_BASE_URL, help="OpenAI-compatible endpoint (Ollama default)")
        p.add_argument("--model", default=DEFAULT_MODEL)

    c = sub.add_parser("compile", help="print the agent a workflow note defines")
    c.add_argument("note")
    c.add_argument("--vault")
    ch = sub.add_parser("chat", help="chat with a workflow note in the terminal")
    ch.add_argument("note")
    ch.add_argument("--vault")
    model_args(ch)
    sv = sub.add_parser("serve", help="Microsoft 365 Agents SDK endpoint (Agents Playground, Teams)")
    sv.add_argument("note")
    sv.add_argument("--vault")
    sv.add_argument("--port", type=int, default=3978)
    model_args(sv)
    r = sub.add_parser("record", help="answer every workflow's examples and save the transcripts")
    r.add_argument("vault", nargs="?", default="vault")
    r.add_argument("--out", default="docs/transcripts.json")
    model_args(r)
    s = sub.add_parser("site", help="build the static demo page")
    s.add_argument("--vault", default="vault")
    s.add_argument("--out", default="docs")
    a = ap.parse_args(argv)

    if a.cmd == "compile":
        print(json.dumps(compile_note(a.note, a.vault), indent=2))
    elif a.cmd == "chat":
        asyncio.run(_chat(a))
    elif a.cmd == "serve":
        from aiohttp import web

        from .m365 import create_web_app

        note = Path(a.note)
        app = create_web_app(compile_note(note, a.vault or note.parent), a.vault or note.parent, lambda: _client(a))
        print(f"Microsoft 365 Agents SDK endpoint: http://localhost:{a.port}/api/messages")
        web.run_app(app, host="localhost", port=a.port)
    elif a.cmd == "record":
        asyncio.run(_record(a))
    elif a.cmd == "site":
        from .site import build

        print(f"Wrote {build(Path(a.vault), Path(a.out))}")


if __name__ == "__main__":
    sys.exit(main())
