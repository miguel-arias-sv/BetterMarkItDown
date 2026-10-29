"""Agent mode: the skill and its installer, `--json`, `setup`, `inspect`, and the MCP
server. Homes, keys, settings and the library are temporary (see conftest)."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from bettermarkitdown import agent, cli, core, library

pymupdf = pytest.importorskip("pymupdf")


def make_pdf(path: Path, pages: int = 3) -> Path:
    doc = pymupdf.open()
    for n in range(pages):
        page = doc.new_page()
        page.insert_text((72, 90), f"Chapter {n + 1}: Harvest Yields", fontsize=16)
        for i in range(8):
            page.insert_text((72, 120 + 14 * i), "Wheat, barley and oats grew by 12 percent "
                             "in the northern region this year.", fontsize=11)
    doc.save(path)
    doc.close()
    return path


def lines(capsys) -> list[dict]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]


@pytest.fixture
def fake_vision(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-0123456789abcdef")
    seen = []

    def describe(client, model, png, prompt, **kwargs):
        seen.append(prompt)
        kwargs["meter"].add(SimpleNamespace(prompt_tokens=1500, completion_tokens=600,
                                            total_tokens=2100))
        return "Chapter 1: Harvest Yields. Wheat, barley and oats grew by 12 percent."

    monkeypatch.setattr(core, "describe_image", describe)
    return seen


# --- the skill ----------------------------------------------------------------------------

def test_the_skill_follows_the_agent_skills_format():
    text = agent.skill_text()
    front = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert front, "SKILL.md must start with YAML frontmatter"
    fields = dict(re.findall(r"^(\w[\w-]*): ?(.*)$", front.group(1), re.M))
    assert fields["name"] == "bettermarkitdown"
    assert re.fullmatch(r"[a-z0-9-]{1,64}", fields["name"])
    assert 0 < len(fields["description"]) <= 1024
    assert agent.MARK in text and "__VERSION__" not in text
    # Neutral: no one agent's tool names in the instructions.
    for word in ("Claude Code", "Read tool", "Bash tool", "Edit tool", "slash command"):
        assert word not in text.split("---", 2)[2].split("## What has been measured")[0]


def test_install_goes_where_each_agent_looks_and_is_shared_when_it_can(monkeypatch):
    home = agent.home()
    monkeypatch.setattr(agent.shutil, "which", lambda name: None)
    results = agent.install(["claude", "codex", "gemini"])
    folders = {Path(r["folder"]) for r in results}
    assert folders == {home / ".claude/skills", home / ".agents/skills"}   # one shared copy
    shared = next(r for r in results if r["folder"].endswith("skills") and ".agents" in r["folder"])
    assert shared["agents"] == "Codex, Gemini CLI"
    assert (home / ".claude/skills/bettermarkitdown/SKILL.md").is_file()
    assert agent.installed_version(home / ".agents/skills") == agent.__version__

    assert {r["result"] for r in agent.install(["claude"])} == {"updated"}
    removed = agent.uninstall(["claude", "codex"])
    assert {r["result"] for r in removed} == {"removed"}
    assert not (home / ".claude/skills/bettermarkitdown").exists()


def test_a_different_skill_with_the_name_is_never_replaced_or_removed():
    folder = agent.home() / ".claude/skills/bettermarkitdown"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nname: bettermarkitdown\ndescription: mine\n---\n")
    assert agent.install(["claude"])[0]["result"] == "skipped"
    assert agent.uninstall(["claude"])[0]["result"] == "skipped"
    assert "mine" in (folder / "SKILL.md").read_text()


def test_project_installs_use_the_project_folders(tmp_path):
    results = agent.install(["claude", "antigravity"], project=tmp_path)
    assert {Path(r["folder"]) for r in results} == {tmp_path / ".claude/skills",
                                                     tmp_path / ".agents/skills"}


def test_nothing_is_installed_without_a_yes(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: False))
    assert agent.main(["install", "--for", "claude"]) == 1
    assert "--yes" in capsys.readouterr().out
    assert not (agent.home() / ".claude/skills/bettermarkitdown").exists()
    assert agent.main(["install", "--for", "claude", "--yes", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["results"][0]["result"] == "installed"


def test_agents_are_found_by_their_command_or_their_folder(monkeypatch):
    monkeypatch.setattr(agent.shutil, "which", lambda name: "x" if name == "codex" else None)
    (agent.home() / ".claude").mkdir()
    found = {a["id"]: a["detected"] for a in agent.status()["agents"]}
    assert "codex" in found["codex"] and ".claude" in found["claude"]
    assert not found["gemini"] and not found["antigravity"]


def test_mcp_instructions_name_this_python(capsys):
    assert agent.main(["mcp", "--for", "all", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["command"][0] == sys.executable and out["command"][-1] == "mcp"
    assert "claude mcp add" in out["agents"]["claude"]
    assert "[mcp_servers.bettermarkitdown]" in out["agents"]["codex"]
    assert json.loads(out["agents"]["gemini"].split("\n\n", 1)[1])["mcpServers"]


# --- the command line for scripts and agents ------------------------------------------------

def test_json_conversion_prints_only_events_and_a_summary(tmp_path, capsys):
    pdf = make_pdf(tmp_path / "a.pdf")
    assert cli.main([str(pdf), "--no-vision", "--json"]) == 0
    events = lines(capsys)
    assert events[0]["event"] == "start" and events[-1]["event"] == "summary"
    assert {e["event"] for e in events} <= {"start", "page_start", "page_done", "summary"}
    assert events[-1]["pages_converted"] == 3 and events[-1]["exit"] == 0


def test_json_errors_and_verify_use_the_same_shape(tmp_path, capsys):
    assert cli.main([str(tmp_path / "missing.pdf"), "--json"]) == 1
    assert lines(capsys)[0] == {"event": "error", "message": f"Not found: "
                                f"{(tmp_path / 'missing.pdf').resolve()}", "exit": 1}
    pdf = make_pdf(tmp_path / "a.pdf")
    cli.main([str(pdf), "--no-vision", "--json"])
    capsys.readouterr()
    assert cli.main([str(pdf), "--verify", "--json"]) == 0
    report = lines(capsys)[0]
    assert report["event"] == "verify" and report["flagged"] == [] and report["exit"] == 0


def test_every_page_sends_every_page_to_the_model(tmp_path, capsys, fake_vision):
    pdf = make_pdf(tmp_path / "a.pdf")
    assert cli.main([str(pdf), "--every-page", "--json"]) == 0
    assert len(fake_vision) == 3 and lines(capsys)[-1]["calls"] == 3


def test_inspect_estimates_before_anything_is_spent(tmp_path, capsys, fake_vision):
    pdf = make_pdf(tmp_path / "a.pdf", pages=4)
    assert cli.main(["inspect", str(pdf), "--every-page", "--pages", "1-2", "--json"]) == 0
    out = lines(capsys)[0]
    assert out["pages"] == 4 and out["selected"] == 2
    assert out["estimate"]["requests"] == 2 and 0 < out["estimate"]["cost"] < 0.02
    assert fake_vision == []


def test_setup_saves_a_choice_and_a_key_from_stdin_only(monkeypatch, capsys, isolated_keys):
    from bettermarkitdown import settings

    monkeypatch.setattr(cli, "list_models", lambda key, url, provider=None: ["gpt-5.4-mini"])
    key = "sk-proj-abcdefghijklmnop"
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(readline=lambda: key + "\n"))
    assert cli.main(["setup", "--provider", "openai", "--key-stdin", "--json"]) == 0
    out = lines(capsys)[-1]
    assert out["engine"]["ready"] and out["engine"]["model"] == "gpt-5.4-mini"
    assert "abcdefghijklmnop" not in json.dumps(out)
    assert isolated_keys.saved[("bettermarkitdown", "openai")] == "sk-proj-abcdefghijklmnop"
    assert settings.load().provider == "openai" and settings.load().setup_done


def test_setup_reports_what_is_missing(capsys):
    assert cli.main(["setup", "--json"]) == 1
    assert "no Google Gemini key" in lines(capsys)[0]["engine"]["problem"].replace("There is ", "")


def test_library_runs_show_up_in_the_workspace(tmp_path, capsys):
    pdf = make_pdf(tmp_path / "Lecture 9.pdf")
    assert cli.main([str(pdf), "--no-vision", "--library", "--json"]) == 0
    events = lines(capsys)
    doc = library.get(next(e for e in events if e["event"] == "library")["document"])
    assert doc.output().is_file() and doc.last_run["converted"] == 3
    assert doc.last_run["by"] == "command line"
    cli.main([str(pdf), "--no-vision", "--library", "--json"])    # the same file: no copy
    assert len(library.documents()) == 1


# --- the MCP server ---------------------------------------------------------------------

def rpc(server, method, params=None, msg_id=1):
    return server.handle({"jsonrpc": "2.0", "id": msg_id, "method": method,
                          "params": params or {}})


def tool(server, name, **arguments):
    reply = rpc(server, "tools/call", {"name": name, "arguments": arguments})["result"]
    return reply["isError"], (reply.get("structuredContent") or reply["content"][0]["text"])


@pytest.fixture
def server():
    from bettermarkitdown.mcp import Server
    return Server()


def test_mcp_handshake_and_tool_list(server):
    init = rpc(server, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "test", "version": "1"}})
    assert init["result"]["protocolVersion"] == "2025-06-18"
    assert init["result"]["capabilities"] == {"tools": {"listChanged": False}}
    assert rpc(server, "initialize", {"protocolVersion": "1999-01-01"})["result"][
        "protocolVersion"] == "2025-11-25"
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    names = {t["name"] for t in rpc(server, "tools/list")["result"]["tools"]}
    assert {"inspect", "convert", "job_status", "verify", "get_page", "set_page"} <= names
    for t in rpc(server, "tools/list")["result"]["tools"]:
        assert t["inputSchema"]["type"] == "object" and t["description"]
    assert rpc(server, "no/such")["error"]["code"] == -32601


def test_mcp_tool_errors_are_results_not_crashes(server, tmp_path):
    error, text = tool(server, "inspect", path=str(tmp_path / "nope.pdf"))
    assert error and "Not found" in text
    error, text = tool(server, "job_status", job_id="nope")
    assert error


def test_mcp_converts_in_the_background_then_checks_and_edits(server, tmp_path, fake_vision):
    from apphttp import wait  # noqa: F401 - the job polling below is the same idea
    pdf = make_pdf(tmp_path / "notes.pdf")
    error, job = tool(server, "convert", path=str(pdf), every_page=True, budget_usd=1)
    assert not error and job["status"] == "running"
    for _ in range(600):
        error, job = tool(server, "job_status", job_id=job["id"])
        if job["status"] != "running":
            break
        time.sleep(0.05)
    assert job["status"] == "done", job["error"]
    assert job["result"]["converted"] == 3 and job["result"]["cost"] > 0
    assert Path(job["result"]["output"]).is_file()

    error, report = tool(server, "verify", path=str(pdf))
    assert not error and "flagged" in report
    error, page = tool(server, "get_page", path=str(pdf), page=2)
    assert not error and "## Page 2" in page["markdown"]
    edited = page["markdown"] + "\n\nAdded by an agent."
    error, saved = tool(server, "set_page", path=str(pdf), page=2, markdown=edited)
    assert not error and saved["saved"]
    assert "Added by an agent." in (tmp_path / "notes.md").read_text(encoding="utf-8")


def test_mcp_library_documents_are_the_workspaces(server, tmp_path):
    pdf = make_pdf(tmp_path / "Lecture 2.pdf")
    error, doc = tool(server, "library_add", path=str(pdf))
    assert not error
    doc_id = doc["document"]["id"]
    error, job = tool(server, "convert", document_id=doc_id, text_only=True)
    assert not error and job["document_id"] == doc_id
    for _ in range(600):
        _, job = tool(server, "job_status", job_id=job["id"])
        if job["status"] != "running":
            break
        time.sleep(0.05)
    assert job["status"] == "done"
    _, listing = tool(server, "library_list")
    assert listing["documents"][0]["converted"] == [1, 2, 3]
    error, page = tool(server, "get_page", document_id=doc_id, page=1)
    assert not error and page["converted"]


def test_mcp_over_stdio_keeps_stdout_for_the_protocol(tmp_path):
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "t", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    done = subprocess.run([sys.executable, "-m", "bettermarkitdown", "mcp"],
                          input="\n".join(json.dumps(m) for m in messages) + "\n",
                          capture_output=True, text=True, timeout=60,
                          cwd=Path(__file__).resolve().parents[1])
    replies = [json.loads(line) for line in done.stdout.splitlines()]
    assert [r["id"] for r in replies] == [1, 2]
    assert replies[1]["result"]["tools"]
