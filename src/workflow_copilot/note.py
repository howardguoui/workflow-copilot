"""Read an Obsidian workflow note and compile it into an agent definition.

A workflow note is ordinary Obsidian markdown: YAML properties (`type: workflow`, `name`, `description`), then
`## Goal`, `## Steps`, `## Tools`, `## Rules` and `## Examples` sections. Tools are [[wikilinks]] to tool notes;
any other wikilink is a note the agent may read. web/compile.js is a line-for-line port of this module, and the
tests check both produce the same JSON for every workflow in the vault.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")


@dataclass
class Workflow:
    name: str
    description: str
    goal: str
    steps: list[str]
    tools: list[str]
    rules: list[str]
    examples: list[str]
    notes: list[str] = field(default_factory=list)  # linked notes the agent may read


def split_frontmatter(text: str) -> tuple[dict, str]:
    text = text.replace("\r\n", "\n")
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            meta = yaml.safe_load(text[4:end]) or {}
            return meta, text[end + 4 :].lstrip("\n")
    return {}, text


def sections(body: str) -> dict[str, list[str]]:
    """Lines under each `## Heading`, keyed by the lower-cased heading."""
    out: dict[str, list[str]] = {}
    current = None
    for line in body.split("\n"):
        if line.startswith("## "):
            current = line[3:].strip().lower()
            out[current] = []
        elif current is not None:
            out[current].append(line)
    return out


def list_items(lines: list[str]) -> list[str]:
    return [m.group(1).strip() for line in lines if (m := LIST_ITEM.match(line))]


def paragraph(lines: list[str]) -> str:
    return " ".join(line.strip() for line in lines if line.strip())


def link_targets(text: str) -> list[str]:
    return [m.group(1).strip() for m in WIKILINK.finditer(text)]


def plain(text: str) -> str:
    """[[target|alias]] -> alias, [[target]] -> target: how links read in the prompt."""
    return WIKILINK.sub(lambda m: (m.group(2) or m.group(1)).strip(), text)


def parse_workflow(text: str) -> Workflow:
    meta, body = split_frontmatter(text)
    if meta.get("type") != "workflow":
        raise ValueError("Not a workflow note: add `type: workflow` to its properties.")
    sec = sections(body)
    tools: list[str] = []
    for item in list_items(sec.get("tools", [])):
        for target in link_targets(item) or [item]:
            if target not in tools:
                tools.append(target)
    linked: list[str] = []
    for key in ("goal", "steps", "rules"):
        for target in link_targets("\n".join(sec.get(key, []))):
            if target not in tools and target not in linked:
                linked.append(target)
    return Workflow(
        name=str(meta.get("name") or "Workflow"),
        description=str(meta.get("description") or ""),
        goal=plain(paragraph(sec.get("goal", []))),
        steps=[plain(s) for s in list_items(sec.get("steps", []))],
        tools=tools,
        rules=[plain(r) for r in list_items(sec.get("rules", []))],
        examples=[plain(e) for e in list_items(sec.get("examples", []))],
        notes=linked,
    )


def tool_description(text: str) -> str:
    """The first paragraph of a tool note's body."""
    _, body = split_frontmatter(text)
    paras = [p.strip() for p in body.split("\n\n") if p.strip() and not p.strip().startswith("#")]
    return " ".join(paras[0].split()) if paras else ""


def instructions(wf: Workflow, tool_docs: dict[str, str]) -> str:
    lines = [f"You are {wf.name}: {wf.description}".rstrip(": ").rstrip(), ""]
    if wf.goal:
        lines += [f"Goal: {wf.goal}", ""]
    if wf.steps:
        lines += ["Follow these steps in order:"] + [f"{i}. {s}" for i, s in enumerate(wf.steps, 1)] + [""]
    if wf.rules:
        lines += ["Rules:"] + [f"- {r}" for r in wf.rules] + [""]
    if wf.tools:
        lines += ["Tools you can call:"] + [f"- {t}: {tool_docs.get(t, '')}".rstrip(": ") for t in wf.tools] + [""]
    if wf.notes:
        lines += ["Notes you can read with read_note: " + ", ".join(f'"{n}"' for n in wf.notes) + "."]
    return "\n".join(lines).strip()


def compile_note(note_path: str | Path, vault: str | Path | None = None) -> dict:
    """Workflow note -> {workflow, instructions, tool_docs}: everything an agent runtime needs."""
    note_path = Path(note_path)
    vault = Path(vault) if vault else note_path.parent
    wf = parse_workflow(note_path.read_text(encoding="utf-8"))
    docs = {}
    for t in wf.tools:
        doc = vault / "Tools" / f"{t}.md"
        docs[t] = tool_description(doc.read_text(encoding="utf-8")) if doc.exists() else ""
    return {"workflow": asdict(wf), "instructions": instructions(wf, docs), "tool_docs": docs}


def find_note(vault: str | Path, title: str) -> Path | None:
    for path in sorted(Path(vault).rglob("*.md")):
        if path.stem == title:
            return path
    return None
