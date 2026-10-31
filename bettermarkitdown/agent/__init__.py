"""The skill for AI agents: one SKILL.md in the open Agent Skills format, copied to where
each agent looks for skills. `bettermarkitdown agent status|install|uninstall|mcp`.

Where each agent looks, from their own documentation (checked 2026-10-29):
  Claude Code      ~/.claude/skills/<name>/          project: .claude/skills/
  Codex            ~/.agents/skills/<name>/          project: .agents/skills/
  Gemini CLI       ~/.gemini/skills/ or its alias ~/.agents/skills/ (used here, so Codex
                   and Gemini CLI share one copy)  project: .agents/skills/
  Antigravity      app and IDE ~/.gemini/config/skills/, CLI ~/.gemini/antigravity-cli/skills/
                   project: .agents/skills/
Nothing is installed without a yes (--yes answers it in advance). Only folders this tool
made, marked in their SKILL.md, are ever replaced or removed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from .. import __version__

NAME = "bettermarkitdown"
SKILL = Path(__file__).with_name("skill") / "SKILL.md"
MARK = "installed-by: bettermarkitdown"


def home() -> Path:
    """$BMID_HOME (tests), else the person's home folder."""
    return Path(os.environ.get("BMID_HOME") or Path.home())


@dataclass(frozen=True)
class Agent:
    id: str
    name: str
    commands: tuple[str, ...]            # on PATH when it is installed
    marks: tuple[str, ...]               # folders under home that it creates
    folders: tuple[str, ...]             # personal skill folders, under home
    project: str                         # the project skill folder


AGENTS: dict[str, Agent] = {a.id: a for a in (
    Agent("claude", "Claude Code", ("claude",), (".claude",), (".claude/skills",),
          ".claude/skills"),
    Agent("codex", "Codex", ("codex",), (".codex",), (".agents/skills",), ".agents/skills"),
    Agent("gemini", "Gemini CLI", ("gemini",), (".gemini/settings.json", ".gemini/tmp"),
          (".agents/skills",), ".agents/skills"),
    Agent("antigravity", "Antigravity", ("antigravity", "agy"),
          (".gemini/antigravity", ".gemini/antigravity-cli", ".gemini/config"),
          (".gemini/config/skills", ".gemini/antigravity-cli/skills"), ".agents/skills"),
)}


def detected(agent: Agent) -> str:
    """Why we think this agent is installed, or "" if we do not."""
    for command in agent.commands:
        if shutil.which(command):
            return f"`{command}` is installed"
    for mark in agent.marks:
        if (home() / mark).exists():
            return f"~/{mark} exists"
    return ""


def skill_text() -> str:
    return SKILL.read_text(encoding="utf-8").replace("__VERSION__", __version__)


def installed_version(folder: Path) -> str | None:
    """The version of our skill in `folder`, "" if a skill there is not ours, None if
    there is none."""
    path = folder / NAME / "SKILL.md"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    if MARK not in text:
        return ""
    found = re.search(r'^\s*version:\s*"?([^"\n]+)"?\s*$', text, re.M)
    return found.group(1).strip() if found else "?"


def targets(chosen: list[str], project: Path | None) -> list[tuple[Path, list[Agent]]]:
    """The folders to install into, each with the agents it serves (one copy in
    ~/.agents/skills serves both Codex and Gemini CLI)."""
    out: dict[Path, list[Agent]] = {}
    for agent_id in chosen:
        agent = AGENTS[agent_id]
        if project is not None:
            folders = [project / agent.project]
        else:
            folders = [home() / f for f in agent.folders]
            if agent.id == "antigravity":
                # The app and IDE, or the CLI: whichever is there; the app if neither is.
                present = [home() / f for f, m in zip(agent.folders, (".gemini/config",
                           ".gemini/antigravity-cli"), strict=True) if (home() / m).exists()]
                folders = present or folders[:1]
        for folder in folders:
            out.setdefault(folder, []).append(agent)
    return list(out.items())


def status() -> dict:
    report = []
    for agent in AGENTS.values():
        folders = [home() / f for f in agent.folders]
        report.append({"id": agent.id, "name": agent.name, "detected": detected(agent),
                       "folders": [{"path": str(f), "installed": installed_version(f)}
                                   for f in folders]})
    return {"version": __version__, "agents": report, "mcp": mcp_command()}


def install(chosen: list[str], project: Path | None = None, force: bool = False) -> list[dict]:
    """Copy the skill; returns what was done per folder. Never replaces a skill named
    `bettermarkitdown` that this tool did not write, unless `force`."""
    done = []
    for folder, agents in targets(chosen, project):
        names = ", ".join(a.name for a in agents)
        current = installed_version(folder)
        if current == "" and not force:
            done.append({"folder": str(folder), "agents": names, "result": "skipped",
                         "why": "a different skill with this name is already there"})
            continue
        target = folder / NAME
        target.mkdir(parents=True, exist_ok=True)
        (target / "SKILL.md").write_text(skill_text(), encoding="utf-8", newline="\n")
        done.append({"folder": str(folder), "agents": names,
                     "result": "updated" if current else "installed", "version": __version__})
    return done


def uninstall(chosen: list[str], project: Path | None = None) -> list[dict]:
    done = []
    for folder, agents in targets(chosen, project):
        current = installed_version(folder)
        names = ", ".join(a.name for a in agents)
        if current is None:
            continue
        if current == "":
            done.append({"folder": str(folder), "agents": names, "result": "skipped",
                         "why": "that skill was not installed by this tool"})
            continue
        shutil.rmtree(folder / NAME)
        done.append({"folder": str(folder), "agents": names, "result": "removed"})
    return done


def mcp_command() -> list[str]:
    """How to start the MCP server: this Python, so it works without the PATH."""
    return [sys.executable, "-m", "bettermarkitdown", "mcp"]


def mcp_instructions() -> dict[str, str]:
    cmd = mcp_command()
    entry = json.dumps({"mcpServers": {NAME: {"command": cmd[0], "args": cmd[1:]}}}, indent=2)
    toml_args = ", ".join(json.dumps(a) for a in cmd[1:])
    quoted = " ".join(f'"{c}"' if " " in c else c for c in cmd)
    return {
        "claude": f"claude mcp add --scope user {NAME} -- {quoted}",
        "codex": (f"codex mcp add {NAME} -- {quoted}\n\nor in ~/.codex/config.toml:\n\n"
                  f"[mcp_servers.{NAME}]\ncommand = {json.dumps(cmd[0])}\n"
                  f"args = [{toml_args}]"),
        "gemini": f"Add to ~/.gemini/settings.json:\n\n{entry}",
        "antigravity": ("Add to ~/.gemini/config/mcp_config.json (older versions: "
                        f"~/.gemini/antigravity/mcp_config.json), or Manage MCP servers > "
                        f"View raw config:\n\n{entry}"),
    }


def _confirm(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print(f"{question} [needs a yes: rerun with --yes]")
        return False
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="bettermarkitdown agent",
                                     description="The skill that teaches AI agents to use "
                                                 "BetterMarkItDown, and its MCP server.")
    parser.add_argument("action", choices=["status", "install", "uninstall", "mcp"])
    parser.add_argument("--for", dest="agents", default="",
                        help=f"comma-separated: {', '.join(AGENTS)} or all "
                             "(default: the agents found on this computer)")
    parser.add_argument("--project", help="install into this project's folders instead "
                                          "of your personal ones")
    parser.add_argument("--yes", action="store_true", help="answer yes in advance")
    parser.add_argument("--force", action="store_true",
                        help="replace a different skill named bettermarkitdown")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.agents in ("", "all"):
        chosen = [a.id for a in AGENTS.values() if args.agents == "all" or detected(a)]
    else:
        chosen = [a.strip() for a in args.agents.split(",") if a.strip()]
        unknown = [a for a in chosen if a not in AGENTS]
        if unknown:
            parser.error(f"unknown agent(s): {', '.join(unknown)}; known: {', '.join(AGENTS)}")
    project = Path(args.project).expanduser().resolve() if args.project else None

    if args.action == "status":
        report = status()
        if args.json:
            print(json.dumps(report, indent=2))
            return 0
        for agent in report["agents"]:
            where = "; ".join(f"{f['path']}: " + ({None: "not installed", "": "another skill"}
                              .get(f["installed"], f"version {f['installed']}"))
                              for f in agent["folders"])
            print(f"{agent['name']:<12} {agent['detected'] or 'not found':<24} {where}")
        return 0

    if args.action == "mcp":
        lines = mcp_instructions()
        if args.json:
            print(json.dumps({"command": mcp_command(), "agents": lines}, indent=2))
            return 0
        print("The MCP server starts with:  " + " ".join(mcp_command()) + "\n")
        for agent_id in chosen or list(AGENTS):
            print(f"--- {AGENTS[agent_id].name}\n{lines[agent_id]}\n")
        return 0

    if not chosen:
        print("No AI agent was found on this computer. Name one with --for "
              f"({', '.join(AGENTS)}), or --for all.")
        return 1
    plan = targets(chosen, project)
    verb = "Install" if args.action == "install" else "Remove"
    listing = "\n".join(f"  {folder / NAME}  ({', '.join(a.name for a in agents)})"
                        for folder, agents in plan)
    if not args.json:
        print(f"{verb} the BetterMarkItDown skill:\n{listing}")
    if not _confirm(f"{verb} it?", args.yes):
        return 1
    results = (install(chosen, project, args.force) if args.action == "install"
               else uninstall(chosen, project))
    if args.json:
        print(json.dumps({"action": args.action, "results": results}, indent=2))
    else:
        for r in results:
            print(f"  {r['result']}: {r['folder']}" + (f" ({r['why']})" if "why" in r else ""))
        if args.action == "install":
            print("Restart the agent, or reload its skills, to pick it up. For the tool server "
                  "too: bettermarkitdown agent mcp")
    return 0 if all(r["result"] != "skipped" for r in results) else 1
