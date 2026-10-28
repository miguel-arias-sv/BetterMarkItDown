"""`bettermarkitdown local ...`: run models on this computer through Ollama.

    local status          what is installed and running, and the suggested model
    local install         install Ollama (asks first)
    local pull [MODEL]    download a model (asks first, shows the size)
    local test [MODEL]    time one test page
    local setup           all of the above, choosing at each step

MODEL is a tag (qwen3-vl:4b-instruct) or a size: 2b, 4b, 8b. Default: the suggestion.
Nothing is installed or downloaded without a yes; --yes answers it in advance.
"""

from __future__ import annotations

import argparse
import sys

from ..system import detect
from . import CATALOG, LocalModel, describe, ollama, recommend


def resolve(choice: str | None, suggested: LocalModel | None) -> LocalModel | str | None:
    """A catalog model for a size or tag; any other tag passes through as text."""
    if not choice:
        return suggested
    wanted = choice.strip().lower()
    for model in CATALOG:
        if wanted in (model.tag, model.tag.split(":")[1].split("-")[0], model.tier):
            return model
    return choice


def confirm(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print(f"{question} [needs a yes: rerun with --yes]")
        return False
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def _progress(status: str, done: int, total: int) -> None:
    if total:
        print(f"\r  {done / 1e9:5.2f} / {total / 1e9:.2f} GB  {100 * done / total:5.1f}%   ",
              end="", flush=True)
    elif status:
        print(f"\r  {status:<48}", end="", flush=True)


def _ensure_server(assume_yes: bool) -> bool:
    if ollama.ensure_running():
        return True
    if ollama.find():
        print("Ollama is installed but its server did not start. Open Ollama from the Start "
              "menu, then try again.")
        return False
    print("Ollama, the free program that runs models on this computer, is not installed.")
    if not ollama.install_command():
        print(f"Install it from {ollama.DOWNLOAD_URL}, then try again.")
        return False
    if not confirm("Install Ollama now (about 1 GB, from its official package)?", assume_yes):
        return False
    if not ollama.install():
        print(f"The installer did not finish. Install it from {ollama.DOWNLOAD_URL}.")
        return False
    if not ollama.ensure_running():
        print("Ollama is installed; start it from the Start menu, then try again.")
        return False
    return True


def cmd_status() -> int:
    profile = detect()
    rec = recommend(profile)
    program = ollama.find()
    running = ollama.version()
    print(f"Ollama program   {program or 'not installed'}")
    print(f"Ollama server    {('running, version ' + running) if running else 'not running'}")
    if running:
        models = ollama.installed()
        print("Models           " + (", ".join(models) if models else "none yet"))
    print(f"Suggested model  {rec.model.tag if rec.model else 'none: use an online provider'}")
    return 0


def cmd_install(assume_yes: bool) -> int:
    return 0 if _ensure_server(assume_yes) else 1


def cmd_pull(choice: str | None, assume_yes: bool) -> int:
    profile = detect()
    rec = recommend(profile)
    target = resolve(choice, rec.model)
    if target is None:
        print("This computer is too small for a local model; use an online provider.")
        return 1
    tag = target.tag if isinstance(target, LocalModel) else target
    if not _ensure_server(assume_yes):
        return 1
    if ollama.has(tag):
        print(f"{tag} is already downloaded.")
    else:
        size = f" ({target.download_gb:g} GB)" if isinstance(target, LocalModel) else ""
        if isinstance(target, LocalModel) and profile.disk_free_gb and \
                profile.disk_free_gb < target.download_gb + 2:
            print(f"Only {profile.disk_free_gb:g} GB free; {tag} needs {target.download_gb:g} GB "
                  "plus room to spare.")
            return 1
        if not confirm(f"Download {tag}{size}?", assume_yes):
            return 1
        print(f"Downloading {tag}")
        try:
            ollama.pull(tag, _progress)
        except ollama.OllamaError as exc:
            print(f"\nDownload failed: {exc}")
            return 1
        print("\n  done")
    name = ollama.with_context(tag)
    print(f"Ready. Convert with:  bettermarkitdown BOOK.pdf --provider ollama --model {name}")
    return 0


def cmd_test(choice: str | None) -> int:
    rec = recommend(detect())
    target = resolve(choice, rec.model)
    if target is None:
        print("No model to test.")
        return 1
    tag = target.tag if isinstance(target, LocalModel) else target
    if not ollama.ensure_running():
        print("Ollama is not running. Run: bettermarkitdown local install")
        return 1
    if not ollama.has(tag) and not tag.startswith(ollama.PREFIX):
        print(f"{tag} is not downloaded. Run: bettermarkitdown local pull {tag}")
        return 1
    name = ollama.with_context(tag)
    print(f"Timing one test page with {name}. The first run loads the model into memory, "
          "which takes a while.")
    try:
        result = ollama.speed_test(name)
    except Exception as exc:
        print(f"The test failed: {exc}")
        return 1
    print(f"  Loading      {result.load_seconds:g} s (once per session)")
    print(f"  Test page    {result.page_seconds:g} s")
    share = result.gpu_share
    print("  Graphics     " + ("unknown" if share is None else f"{share:.0%} of the model "
                                                              "in graphics memory"))
    print(f"  Read right   {'yes' if result.read_ok else 'no: check the output below'}")
    print(f"\n{result.verdict()}")
    if not result.read_ok:
        print("\n--- what the model wrote ---\n" + result.text[:1500])
    return 0 if result.read_ok else 2


def cmd_setup(assume_yes: bool) -> int:
    profile = detect()
    rec = recommend(profile)
    print(describe(profile, rec))
    if not rec.model:
        return 1
    print()
    if assume_yes or not sys.stdin.isatty():
        choice = None
    else:
        sizes = "/".join(m.tag.split(":")[1].split("-")[0] for m in CATALOG)
        default = rec.model.tag.split(":")[1].split("-")[0]
        choice = input(f"Which model? ({sizes}, Enter for {default}) ").strip() or None
    model = resolve(choice, rec.model)
    tag = model.tag if isinstance(model, LocalModel) else model
    if cmd_pull(tag, assume_yes) != 0:
        return 1
    print()
    return cmd_test(tag)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="bettermarkitdown local",
                                     description="Run models on this computer with Ollama.")
    parser.add_argument("action", choices=["status", "install", "pull", "test", "setup"])
    parser.add_argument("model", nargs="?", help="2b, 4b, 8b, or an Ollama tag "
                                                 "(default: the suggested model)")
    parser.add_argument("--yes", action="store_true",
                        help="answer yes to install and download questions")
    args = parser.parse_args(argv)
    if args.action == "status":
        return cmd_status()
    if args.action == "install":
        return cmd_install(args.yes)
    if args.action == "pull":
        return cmd_pull(args.model, args.yes)
    if args.action == "test":
        return cmd_test(args.model)
    return cmd_setup(args.yes)
