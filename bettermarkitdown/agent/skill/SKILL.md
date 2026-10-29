---
name: bettermarkitdown
description: Convert PDF, Word and PowerPoint files to Markdown with BetterMarkItDown, keeping what plain text extraction drops - scanned pages, equations, tables and what figures show. Use when asked to turn a PDF, DOCX, PPTX, DOC or PPT into Markdown, to transcribe or OCR a book, paper or lecture slides, to prepare course material as text, or to check or fix such a transcription. Covers a free look first, asking before anything is spent, converting with progress, the free check against the PDF, and fixing single pages.
metadata:
  installed-by: bettermarkitdown
  version: "__VERSION__"
---

# Converting documents to Markdown with BetterMarkItDown

BetterMarkItDown runs MarkItDown for the text and sends what text extraction cannot read
(scanned pages, equations set as pictures, figures) to a vision model: an online service
(Gemini, OpenAI, Claude, Kimi, OpenRouter) or a model on this computer (Ollama). It is a
command, `bettermarkitdown` (also `python -m bettermarkitdown`), and every command below
takes `--json` for one JSON object per line.

Do not use plain MarkItDown for a PDF with pictures: on PDFs it only extracts the text
layer, so a scanned book comes out empty and every chart is dropped without a word.

## 0. Is it set up?

```
bettermarkitdown setup --json
```

`engine.ready` says whether an AI service is ready; `engine.problem` says what is missing.
If it is not ready, tell the person and offer the ways forward. Let them choose:

- **They add a key themselves**: `bettermarkitdown key set PROVIDER` (a hidden prompt), or
  the setup page, `bettermarkitdown app`. Never ask for a key in the conversation and never
  put one on a command line or in a file: it would be kept in the history.
- **Text only, free**: `--no-vision`. Fine for born-digital files; scanned pages and
  pictures come out empty.
- **A model on this computer**: `bettermarkitdown local status`, then `local setup` only once
  the person agrees: it installs Ollama and downloads several GB, and it is slow without a
  graphics card (minutes per page). `bettermarkitdown system --json` says what fits.

## 1. Look before spending (free)

```
bettermarkitdown inspect FILE --json [--pages 10-40] [--every-page]
bettermarkitdown FILE --toc --json
```

`inspect` gives the pages, which are scanned, which set their equations as pictures, the
number of figures, and an estimate (`estimate.requests`, `estimate.cost` in US dollars at
the model's list price, `estimate.seconds` for a local model whose speed was measured).
`--toc` lists the chapters with their page ranges, for choosing `--pages`.

Use `--every-page` when the file is maths-heavy and born-digital: a PDF's text layer often
garbles formulas (braces, sub- and superscripts out of order), and this reads every page as
an image instead, one request per page.

## 2. Ask before spending

Tell the person how many requests, the rough cost or time, and where pages go (an online
service receives the page images it reads). Convert only after they agree. Always pass a
spending cap for an online service: `--budget-usd 2` stops cleanly once $2 is spent, and
finished pages are kept. `--estimate 3` converts 3 pages and projects the rest from what
they really cost.

## 3. Convert

```
bettermarkitdown FILE --json -o OUT.md --budget-usd 2 [--pages 10-40] [--every-page]
                      [--work-dir LOCAL_DIR] [--title "Readable heading"] [--library]
```

- Events, one per line: `start`, `page_start`, `page_done` (with `cost` so far),
  `page_failed`, `log`, then `summary` (pages converted, failed, local-OCR and cut-off
  pages, cost, `cost_to_finish`, `work_dir`) or `error`.
- Exit codes: 0 done, 1 error, 2 stopped early (cap or daily quota), 130 interrupted.
- Long runs: run it in the background and read the events; a page takes seconds online
  and minutes on a laptop processor.
- Stopped or failed pages: run the same command again. It continues where it stopped and
  pays for nothing twice.
- Per-page files live in the work dir (`OUT_work/pages/NNNN.md` by default). When the
  output is in a synced folder (OneDrive, Google Drive, Dropbox), pass `--work-dir` on a
  local disk, or the sync client will fight the run.
- `--library` converts inside the setup page's library instead, with the result in
  `Documents\BetterMarkItDown\NAME\`, so the person can review and edit it side by side with
  the original in `bettermarkitdown app`.
- Word and PowerPoint: pictures are described where they stand. `--as-pages` goes through a
  PDF instead (needs Microsoft Office or LibreOffice), which gives page images to check.

## 4. Check, before saying it worked

```
bettermarkitdown FILE --verify --json -o OUT.md [--work-dir LOCAL_DIR]
```

Free and offline. It compares every page with the PDF's own text layer and lists, per page,
words or numbers that differ, pages still holding local-OCR text, cut-off pages, broken
maths (every formula is rendered when Node.js and KaTeX are installed) and markup faults.
Exit code 3 when something is flagged.

Read every flagged page's notes. Not every flag is an error: the text layer writes
exponents and footnote markers as plain digits ("2^32" as "232", "Table 4.3" plus note 3 as
"4.33"), and a book's own typos show up too. Pages with no text layer cannot be checked
this way. When you can look at images, render a page and compare it with its Markdown:

```
python -c "import pymupdf; pymupdf.open('FILE.pdf')[N-1].get_pixmap(dpi=110).save('page.png')"
```

## 5. Fix pages

Edit `<work_dir>/pages/NNNN.md` (4 digits, 1-based), keeping its `## Page N` heading and `\n`
line endings. Then rebuild the output with the same command plus `--no-vision` (no requests,
nothing spent). Never pass `--fresh` to a work dir with hand edits: it redoes those pages.

Conventions: typos that are in the source stay as printed, marked `*[sic]*`; notes are
`[^N]` markers with `[^N]: text` where the source prints the note; review notes are
`*[note from review: ...]*`.

## 6. Report

Pages converted, any missing or failed, pages read by local OCR, what the check flagged and
what you fixed, the total cost, and where the output is. Never report success before step 4.

## Pages the model refuses

Online models sometimes refuse a page of a published book (Gemini's recitation filter). Do
not work around it: no splitting the page into pieces, no rewording to disguise the request,
and do not transcribe the page yourself instead: that produces the very text the model
declined to. The tool falls back to local OCR on the person's own file; such pages are
listed in the summary, their layout is flattened and their maths unreliable. Tell the person
which pages they are, so they can read those in the original.

## Without the command line: MCP

`bettermarkitdown mcp` is a Model Context Protocol server (stdio) with the same steps as
tools: `setup_status`, `inspect`, `toc`, `convert` (runs in the background) with
`job_status` (pass `wait_seconds` to wait for it instead of polling) and `stop`, `verify`, `get_page`, `set_page`, and the shared library
(`library_list`, `library_add`). `bettermarkitdown agent mcp` prints how to register it.

## What has been measured

- Gemini 3.6 Flash: about $0.0034 a page read whole (352 textbook pages, $1.21, about ten
  minutes at three pages at a time). Strong on scans, tables and maths.
- Qwen3-VL 4B and 8B on a laptop processor: about 90 and 140 seconds a page; both miss
  hand-drawn graphs, and 4B reads charts poorly.
- Other services and models are untested with this tool: try a few pages first.
