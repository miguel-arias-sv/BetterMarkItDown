# Contributing to BetterMarkItDown

Thank you for testing and improving it. This page covers how to report a problem, how to
propose a fix, and the few rules every change keeps.

## The rules every change keeps

- **Never work around a model's refusal.** When a provider declines to transcribe a page
  (Gemini's recitation filter, for one), the tool does not split the page into pieces, blur
  or rotate it, reword the request to disguise it, or transcribe the page word for word some
  other way. It asks for **study notes** instead: the page's ideas in the model's own words,
  checked and labelled (see `bettermarkitdown/notes.py`), and falls back to local OCR only
  if that fails. A change that makes notes closer to the page's wording is not a fix.
- **Never spend, install or download without a yes.** A click on the setup page, a `--yes`,
  or an explicit answer.
- **Keys are never printed in full, logged or stored in files.**
- **No page goes missing silently.** A page that fails, is refused, or comes from local OCR
  is listed in the run summary and in `--verify`, and says so in the output.
- **Say what was measured.** A model, a provider or a feature is "untested here" until it
  has been run on real pages; documentation gives the numbers.

## Reporting a conversion problem

Open an issue with the **Conversion problem** form. Please:

- **Do not paste a book's text or attach a copyrighted file.** Page numbers and a
  description in your own words are enough; quoting one formula or one number is fine.
- If you can, reproduce the problem with a document you wrote yourself, or one that is free
  to share (public domain, or openly licensed), and attach that.
- Give the version (`bettermarkitdown --version`), the AI service and model, and the
  command you ran, without any key.

## Proposing a fix

1. Fork, branch, and keep the change focused on one problem.
2. Add a test that fails without the fix. Tests use made-up documents built in the test
   (see `tests/test_notes.py` or `tests/test_workspace.py`), never real books, and never
   touch the real keyring, settings, library, Documents, Office, Ollama or the network: the
   fixtures in `tests/conftest.py` take care of that.
3. Run `python -m pytest tests -q` and `ruff check bettermarkitdown tests`.
4. If the change affects what a model is asked or how its output is checked, **measure it
   before and after on the same pages**, and put the numbers in the pull request:
   - transcriptions: `bettermarkitdown FILE --verify --json` on a converted work dir;
   - study notes: `python scripts/notes_eval.py FILE --key WORK_DIR/pages --pages ...`
     compares notes with a reviewed transcription of pages the model did not refuse, and
     prints numbers only (copied wording, numbered items kept, exact figures kept, what a
     check finds wrong or missing). Use documents you own; share the numbers, not the text.
5. Add a line to `CHANGELOG.md` under `## [Unreleased]`.

## Known limits, open to fixes

- Study notes keep ideas, formulas and figures well in the measurements so far (six
  textbook pages, Gemini 3.6 Flash), but they condense by nature and the checking request
  is itself a model that makes mistakes. More measurements on other books, subjects and
  models are welcome.
- Figure descriptions of dense diagrams are the weakest part of a transcription (see
  "Reviewing the output" in the README).
- Local models (Qwen3-VL 4B and 8B) miss hand-drawn graphs; providers other than Gemini
  are untested with this tool.

## Code style

Python 3.10+, standard library where it is enough, `ruff` as configured in
`pyproject.toml`. Comments say why, not what. User-facing text is plain, short and says
what to do next.
