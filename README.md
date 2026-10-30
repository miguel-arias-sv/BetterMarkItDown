![BetterMarkItDown banner](assets/banner.png)
# BetterMarkItDown

**Turn scanned and image-heavy PDFs into Markdown including graphs, equations and images.**

[![Latest release](https://img.shields.io/github/v/release/miguel-arias-sv/BetterMarkItDown)](https://github.com/miguel-arias-sv/BetterMarkItDown/releases/latest)
[![Tests](https://github.com/miguel-arias-sv/BetterMarkItDown/actions/workflows/ci.yml/badge.svg)](https://github.com/miguel-arias-sv/BetterMarkItDown/actions/workflows/ci.yml)
· [What's New](CHANGELOG.md) · [Code signing policy](CODE_SIGNING_POLICY.md) · [Privacy](PRIVACY.md)

[Microsoft's MarkItDown](https://github.com/microsoft/markitdown) is excellent, and it has
one gap that matters enormously for textbooks, papers and lecture notes: **its PDF path
never looks at images.**

MarkItDown accepts `llm_client` and `llm_model`, which makes it tempting to assume a vision
model will describe the pictures in your PDF. It won't. Those options apply to standalone
image files and to images inside `.pptx` / `.docx`. The PDF converter is pure text
extraction — pdfplumber falling back to pdfminer.six — so on a scanned book it produces an
empty file, and on a book full of graphs it silently drops every graph.

BetterMarkItDown keeps MarkItDown as the text engine and adds the missing vision layer:

| Page | What happens |
|---|---|
| **Has a text layer** | MarkItDown extracts the text. Every figure — embedded images *and* charts drawn as vectors — is cropped and sent to a vision model, which returns a description plus a data table read off the axes. |
| **No text layer** (scanned, photographed) | The whole page is rendered and transcribed to Markdown: headings, footnotes, LaTeX math, figure descriptions. |
| **Refused by the model** | Falls back to a local OCR engine on your own machine. See [Refused pages](#refused-pages). |

It talks to **any server that speaks the OpenAI chat-completions protocol.** Google Gemini
is the default because that is what the cost numbers below were measured against, but
`--base-url` points it at OpenAI, OpenRouter, or a model running on your own machine. See
[Providers and tiers](#providers-and-tiers) and [Running a local model](#running-a-local-model).

---

## What the output looks like

From a real scanned macroeconomics textbook page:

```markdown
## Page 100

<!-- source: full-page vision transcription -->

180 **Part 2** *Basic Macroeconomic Models*

The function $m$ has constant returns to scale. Recall that this means that
$$m(xQ, xA) = xm(Q, A), \tag{6.3}$$
for any $x > 0$. For the matching function, constant returns to scale implies that a
large economy is no more efficient at producing matches than a small economy.

### OPTIMIZATION BY CONSUMERS

If a consumer chooses to search for work, he or she may find a job, in which case the
consumer would be counted as employed by Statistics Canada...

<!-- page number: 180 -->
```

Charts become data you can reason about, not just alt text:

```markdown
**Figure 4.9 — transcribed by gemini-3.6-flash:**

> Line graph of Employment/Population Ratios in Canada and the United States, 1975–2020.
> **Vertical axis:** Rate in percent (56 to 65)   **Horizontal axis:** Year
>
> | Region | Yield (tons) |
> | :--- | :--- |
> | North | ~35 |
> | South | ~70 |
```

### Measured runs

| Document | Pages | Result | Cost |
|---|---|---|---|
| Scanned macroeconomics textbook | 163 | 464 KB of Markdown — 77,970 words, 2,347 inline LaTeX expressions, 103 display equations, 92 figure descriptions, 35 footnotes | **$0.58** |
| Three LaTeX lecture-note PDFs (born-digital) | 45 | 102 KB — 594 inline expressions, 135 display equations, 24 figure descriptions | **$0.13** |
| Publisher's textbook, four chapter selections, [every equation set as a picture](#when-the-equations-are-pictures) | 74 | 156 KB — 228 display equations, 5 tables transcribed from images | **$0.26** |
| Survey documentation: CCHS 2022 user guides (Statistics Canada) | 72 | 200 KB; every page checked word by word and number by number with `--verify` | **$0.26** |
| …and its codebooks, [parsed from the text layer](#codebooks-data-dictionaries-and-statistical-tables) | 281 | 255 variables, 59 derived variables, 108 CV tables; every number copied, not read | **$0** |

---

## Install

**On Windows, with the installer (easiest).** Download `BetterMarkItDown-Setup-<version>.exe`
from the [latest release](https://github.com/miguel-arias-sv/BetterMarkItDown/releases/latest)
and double-click it. No Python, no administrator rights: it installs for you alone, in
`%LOCALAPPDATA%\Programs\BetterMarkItDown`, with its own copy of Python (it downloads about
500 MB during setup, so it needs internet then). It adds a Start-menu entry and, if you
like, a desktop icon, both of which open the setup page; and it can put the
`bettermarkitdown` command on your PATH, for terminals and AI agents.

- **"Windows protected your PC"?** The installer is not code-signed yet (see the
  [code signing policy](CODE_SIGNING_POLICY.md): signing by SignPath Foundation is applied
  for), so Windows SmartScreen does not know it. Click **More info**, then **Run anyway**.
  Only do that for the file from this project's releases page.
- **What it sends where:** during setup it downloads Python and its libraries; afterwards
  nothing leaves your computer unless you convert with an online AI service you chose. The
  installer shows this before installing; details in [PRIVACY.md](PRIVACY.md).
- **Uninstall** from Settings > Apps > Installed apps > BetterMarkItDown. It removes the
  program and its Python, and asks whether to delete your library, settings and saved keys
  too. Your converted files in `Documents\BetterMarkItDown` are never removed.
- **Upgrade** by running a newer installer over the old one.

**With pip, from a release.** One command installs a fixed, tested version and its
dependencies, including the local OCR fallback:

```bash
pip install "bettermarkitdown[ocr] @ git+https://github.com/miguel-arias-sv/BetterMarkItDown@v1.5.0"
bettermarkitdown --version
```

Or download the `.whl` file from the [latest release](https://github.com/miguel-arias-sv/BetterMarkItDown/releases/latest)
and run `pip install bettermarkitdown-<version>-py3-none-any.whl`. Each release lists what
changed in it; the full history is in [CHANGELOG.md](CHANGELOG.md).

**From source**, if you want to change the code:

```bash
git clone https://github.com/miguel-arias-sv/BetterMarkItDown.git
cd BetterMarkItDown
pip install -r requirements.txt          # everything the converter needs
pip install -e .                         # optional: adds the `bettermarkitdown` / `bmid` commands
```

**Optional — math render check.** With [Node.js](https://nodejs.org) installed, `--verify`
also renders every formula with KaTeX and flags the ones that would show up as red error
boxes. One more command:

```bash
npm install                              # reads package.json: just KaTeX
```

If the repo lives in Google Drive, OneDrive or Dropbox, use `npm install -g katex` instead,
so a `node_modules` folder is not synced. Without Node the check is skipped, never failed.

> **The `[pdf]` extra is not optional.** A plain `pip install markitdown` cannot open a PDF
> at all — it raises `MissingDependencyException` on every page. `requirements.txt` pins
> `markitdown[pdf]` for exactly this reason.

Then add your key. Get a Gemini key free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey),
or use [another provider](#providers-and-tiers):

```bash
bettermarkitdown key set gemini      # paste it at the hidden prompt
bettermarkitdown key test gemini     # free: lists the models the key can use
```

The key goes into your computer's own password store (Windows Credential Manager, the macOS
Keychain, or the Secret Service on Linux), never into a plain file. An environment variable
or a `.env` file still works and wins over the store, which suits scripts and CI:

```bash
cp .env.example .env     # then edit .env and paste your key
```

Each provider reads only its own variables (`GEMINI_API_KEY`, `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, ...), so a key is never sent to another company's server.
`.env` is gitignored. The tool never prints a key in full or commits one.

---

## Use it

### The setup page (start here)

```bash
bettermarkitdown app
```

A plain page opens in your browser. It runs only on your computer, not on a website. It asks
who will use the tool (you, an AI agent, or both), how much help you want, and whether you
have an API key. Then it saves and checks your key, shows you how to get one, or sets up a
model on your computer. Every option comes with what it is good at and its limits, and
nothing is installed, downloaded or paid for without a click. Your choices become the
defaults for every command afterwards. Run it again any time, or open Settings to switch
provider or model. The installer's Start-menu entry opens this page too.

Once set up, the same page is a **workspace**. Add PDF, Word and PowerPoint files to a
library on your computer, and each gets a free look first: scanned pages, equations set as
pictures, figures, chapters, and an estimate of the cost (online service) or time (local
model). Convert all of it, a chapter, or a few pages to measure, with a spending cap if you
like, and watch the pages, time left and money spent. Then review each page's picture next
to its Markdown, with the maths drawn, edit it, and download the `.md` or a `.zip` with its
pictures. A conversion expected to take more than two minutes offers a small game while you
wait; it never starts by itself.

The page's server listens on 127.0.0.1 only and needs the one-time token in the address it
opens, so other websites and other computers cannot use it. It stops when you press Quit,
or a while after the tab is closed.

### Interactive, in the terminal

```bash
python -m bettermarkitdown
```

Paste the path to your PDF and answer a few questions. Before spending anything it tells
you what it found:

```
+--------------------- What is in this PDF ---------------------+
|   File               Williamson Macroecon - CH 4-7.pdf        |
|   Pages              163                                      |
|   Scanned pages      163  (no text layer -> full-page vision) |
|   Text pages         0    (MarkItDown text + figure crops)    |
|   Embedded images    1742                                     |
|                                                               |
| Fully scanned. Plain MarkItDown would produce an empty file.  |
+---------------------------------------------------------------+
```

Then a live progress bar, and a summary with the exact cost.

### Command line

```bash
# The whole thing
python -m bettermarkitdown book.pdf -o book.md

# Free dry run: no API calls, shows you which pages have a text layer
python -m bettermarkitdown book.pdf --no-vision -o dryrun.md

# Measure before you commit: convert 5 pages, project the full cost
python -m bettermarkitdown book.pdf --estimate 5

# Which pages hold which chapter? Prints the outline with page ranges, no API calls
python -m bettermarkitdown book.pdf --toc

# A section, with a spending cap and a readable heading
python -m bettermarkitdown book.pdf --pages 40-80 --budget-usd 2 --workers 4 \
    --title "Chapter 3: Simple Regression"

# Against a model on your own machine
python -m bettermarkitdown book.pdf --base-url http://localhost:11434/v1 --model qwen3-vl:8b-instruct
```

### With an AI agent

Agents such as Claude Code, Codex, Gemini CLI and Antigravity can use the tool on their own,
and ask you before they spend anything. Give them the skill once:

```bash
bettermarkitdown agent install     # asks first; for each agent found on this computer
bettermarkitdown agent status      # which agents have it
```

The skill is a `SKILL.md` in the open Agent Skills format, the same for every agent: look at
the file for free, tell you the requests and the cost or time and ask, convert, check the
result against the PDF, fix pages, report. It never replaces a skill it did not write, and
`agent uninstall` removes it. The setup page offers the same, one button per agent.

Underneath, it is plain commands with JSON output, which any script can use too:

```bash
bettermarkitdown setup --json                     # ready to convert? if not, what is missing
bettermarkitdown setup --provider gemini --key-stdin   # the key comes from standard input, never the command line
bettermarkitdown inspect book.pdf --json          # pages, scanned pages, figures, estimate: free
bettermarkitdown book.pdf --pages 40-80 --budget-usd 2 --json
bettermarkitdown book.pdf --verify --json
```

With `--json`, standard output carries one JSON object per line (progress events, then a
summary, or an error) and nothing else. Exit codes: 0 done, 1 error, 2 stopped early
(spending cap or daily quota), 3 `--verify` flagged pages, 130 interrupted. `--library`
converts the copy in the setup page's library, so you can review an agent's work in the
workspace.

**Or as an MCP server**, for agents that prefer tools to a shell: `bettermarkitdown mcp`
(stdio, nothing extra to install) offers the same steps as tools, with conversions running
in the background (`convert`, then `job_status` and `stop`). `bettermarkitdown agent mcp`
prints how to register it with each agent; for Claude Code:

```bash
claude mcp add --scope user bettermarkitdown -- bettermarkitdown mcp
```

Tried with Claude Code, both ways (skill and command line, and MCP). Codex, Gemini CLI and
Antigravity are untested here.

### As a library

```python
from pathlib import Path
from bettermarkitdown import Options, convert

result = convert(Options(pdf=Path("book.pdf"), output=Path("book.md"), api_key="..."))
print(result.pages_converted, result.cost)
```

### Word and PowerPoint files

```bash
python -m bettermarkitdown report.docx           # or slides.pptx, old.doc, lecture.ppt
python -m bettermarkitdown slides.pptx --as-pages
```

- **DOCX and PPTX** are read by MarkItDown, which keeps headings, lists and tables. On its
  own it leaves every picture as an empty placeholder. Here each picture is saved to
  `<name>_assets/` and described by the vision model where it stood, with a data table for
  charts. Pictures smaller than 48 px (icons, bullets) are kept but not sent.
- **DOC and PPT** (Office 97-2003) are opened by Microsoft Word or PowerPoint if installed,
  else by the free [LibreOffice](https://www.libreoffice.org/download/)
  (`winget install --id TheDocumentFoundation.LibreOffice -e`). They are saved as DOCX / PPTX
  in the work folder and read as above.
- **`--as-pages`** turns any of them into a PDF first and converts it page by page, like a
  PDF, with page images to compare against. Tables come out flatter, since PDF text has no
  table structure.

---

## Recommended workflow

1. **`--no-vision` first.** Free. Tells you whether the PDF is scanned, born-digital, or
   mixed. Pages reading `*[no extractable text on this page]*` are the ones that will cost
   money.
2. **`--estimate 5` on a representative range.** Converts five real pages and projects the
   total. Those pages stay done and cached, so it costs nothing extra later.
3. **Read that sample and tune.** This is the step worth your time — fixing settings after
   400 pages means redoing 400 pages.
   - Scanned pages not being transcribed → raise `--min-chars`
   - Small or ornate type coming out wrong → `--dpi 300`
   - Figure descriptions missing axis labels → raise `--figure-pad`
   - Born-digital pages extracting badly → see below
   - Equation numbers like `(12.1)` with nothing beside them → [the equations are
     pictures](#when-the-equations-are-pictures)
4. **Run the whole thing** with `--budget-usd` as a seatbelt.
5. **If it stops** — cap, quota, Ctrl+C, dropped network — rerun the identical command. It
   resumes and re-pays for nothing.

### When "born-digital" is a trap

A PDF with a text layer looks like the cheap case, and usually is. But text extraction
inherits whatever the generating program encoded, and **LaTeX output is a common offender.**
On a set of LaTeX lecture notes, the free text path produced:

```
(cid:136) Dynamic: Households and firms optimize intertemporally...
| challenges | posed by | uncertainty. |     |     |
Chapter4: TheRealBusinessCycle(RBC)FrameworkandNumericalMethods.
```

Three separate failures: the `itemize` bullet has no Unicode mapping and comes out as
`(cid:136)`, column whitespace gets misread as a Markdown table, and inter-word spaces are
missing because the font positions glyphs individually.

None of that is fixable in post-processing. Send those pages to the vision model instead by
raising the scanned-page threshold above any real page's character count:

```bash
python -m bettermarkitdown notes.pdf --min-chars 100000 -o notes.md
```

Every page now counts as "scanned" and gets a full-page transcription. The same pages came
back clean, with correct `$...$` math, `$$...$$` tagged equations and figure descriptions,
at about $0.003/page. Check a sample either way — if the text path looks right, keep it,
because it is free.

### When the equations are pictures

The other trap looks clean. Publishers' PDFs often set every equation as a small embedded
image: a 353 × 10 pt strip for a display equation, 11 × 13 pt for an inline $\hat{P}_i$. The
text layer holds the prose and nothing where the equations were, so the text path wrote this
for a finance textbook:

```
explanatory variables x2i, x3i, …, xki

(12.1)

The actual probabilities cannot be observed, so we would estimate a model
```

Every word is right and the equation is gone. `--verify` cannot see the loss either: it
compares against the same text layer, which never had the equation. Before v1.4.0 the
figure detector skipped these images too, because they are far smaller than any figure.

**Since v1.4.0 this is handled for you.** A page that has a text layer *and* images too
small to be figures (under `--min-figure-pt` on a side, over 2 pt so rules and bullets
don't count) is transcribed whole by the vision model, like a scanned page. The run
summary lists those pages. Through vision, the same page comes back as:

```markdown
$$P_i = p(y_i = 1) = \beta_1 + \beta_2 x_{2i} + \beta_3 x_{3i} + \dots + \beta_k x_{ki} + u_i, \quad i = 1, \dots, N \tag{12.1}$$
```

If small images on your pages are logos or icons rather than equations, pass
`--ignore-small-images` to keep those pages on the free text path. With `--no-vision` the
pages are listed as a warning instead: their equations are missing from the output.

To check a PDF before converting, count them:

```python
import pymupdf
doc = pymupdf.open("book.pdf")
for page in doc:
    small = [i for i in page.get_image_info()
             if 2 <= min(i["bbox"][2] - i["bbox"][0], i["bbox"][3] - i["bbox"][1]) < 60]
    if small:
        print(page.number + 1, len(small))
```

### Codebooks, data dictionaries and statistical tables

The opposite case: born-digital pages where the vision model is the wrong tool. A codebook
is a grid of codes, frequencies and percentages, and every one of those digits is already
exact in the text layer. Transcribing the page re-reads digits you already have, with a
small chance of misreading each one, and a misread `1,336,749` → `1,386,749` looks as
plausible as the real figure. Page-by-page output also splits records that continue onto
the next page, and a page full of numbers can be too long for one reply (see
[cut-off replies](#how-resuming-works)).

Parse the layout instead. Keep the coordinates of every span, assign each number to its
column by the column's right edge (numbers are right-aligned, so that is exact), and check
the result with the document's own arithmetic. Frequencies must sum to the printed total,
and the variables found must match the table of contents.

[`examples/codebooks/`](examples/codebooks/) does this for Statistics Canada's **CCHS 2022
public-use microdata** documentation: a 114-page data dictionary (255 variables), 49 pages
of derived-variable specifications and 118 pages of CV tables. All of it was copied from
the text layer for $0, every category table sums to its total, and every CV cell fits the
formula its table was built from. The scripts are templates for that layout, not a
general converter. The README there explains how to adapt them to another codebook in
about an hour.

| The document is… | Use |
|---|---|
| Prose, slides, a scanned book, figures | BetterMarkItDown |
| A born-digital codebook, data dictionary, frequency or CV tables | A layout parser, as in [`examples/codebooks/`](examples/codebooks/) |
| Born-digital prose *with* tables (a survey's user guide) | BetterMarkItDown, then [`--verify`](#check-the-wording-for-free---verify), which compares numbers as well as words |

### If your output lives in Google Drive, OneDrive or Dropbox

Two flags matter:

- **`--work-dir` on a local disk.** The work dir holds one file per page plus the response
  cache; leaving it in a synced folder means hundreds of files syncing during the run.
- **`--no-page-images`.** By default a PNG of every scanned page is written next to the
  `.md`, which on a long book is ~100 MB of sync traffic for images you already have inside
  the PDF.

```bash
python -m bettermarkitdown book.pdf \
  -o "G:/My Drive/Course/book.md" \
  --work-dir "C:/Users/you/.pdfmd_work/book" \
  --no-page-images
```

---

## Tested with

What has actually been run with this tool, and on what. Everything else is built in and
should work, but is **untested here**: try a few pages first (`--estimate 5`).

| Tried | On | What we found |
|---|---|---|
| **Gemini 3.6 Flash** (paid Tier 1) | The [measured runs](#measured-runs) above, and 352 pages of an econometrics textbook read whole | Strong on scans, tables and maths; $1.21 for the 352 pages, in about 10 minutes. Diagram descriptions are the weak spot ([Reviewing the output](#reviewing-the-output)) |
| **Gemini 3.6 Flash, study notes** | Six textbook pages, run as if refused | No copied wording, every numbered item kept; still about one real slip every few pages ([Refused pages](#refused-pages)) |
| **Qwen3-VL 4B and 8B**, through Ollama | A Core Ultra 7 laptop, processor only | About 90 s and 130-190 s a page; text and formulas right; 4B reads charts poorly, and both skipped hand-drawn graphs ([Running a local model](#running-a-local-model)) |
| **Claude Code** as the agent | A small made-up PDF: the skill with the command line, then the MCP server alone | Both ways it loaded the instructions by itself, estimated the cost, converted under a cap, ran the free check, compared the scanned page with its image, and reported ([With an AI agent](#with-an-ai-agent)) |
| **The Windows installer** | Windows 11, per user | Installed, ran and uninstalled cleanly, PATH restored; the release workflow repeats this on a clean machine |

Untested here: OpenAI, Claude through Anthropic's API, Moonshot Kimi, OpenRouter, other
local models and servers, and the agents Codex, Gemini CLI and Antigravity. The test suite
runs on Windows and Linux; macOS and Linux have not been tried by hand, and the installer
is for Windows only.

---

## Providers and tiers

**What this was built and measured on: Gemini API, Tier 1** — the paid tier you land on as
soon as you link an active billing account. Nothing in the tool requires that tier; it is
just the one the cost table reflects and the one that can actually finish a book.

### Gemini free tier

Works, and is the right way to evaluate the tool. Three caveats, in order of how likely they
are to bite:

1. **Daily request caps.** Free limits are per-model, per-day and low — on the order of a
   few dozen requests for Flash models, though Google changes the numbers and publishes the
   current ones in [AI Studio](https://aistudio.google.com/) rather than in the docs. One
   page is one request, so a 163-page book cannot be converted in a day. Use it on
   `--estimate 5`, then decide.
2. **Your documents are used to improve Google's products.** The
   [Gemini API terms](https://ai.google.dev/gemini-api/terms) draw the line explicitly: on
   unpaid services "Google uses the content you submit to the Services and any generated
   responses to provide, improve, and develop Google products and services," while on paid
   services "Google doesn't use your prompts... or responses to improve our products."
   If the PDF is confidential, unpublished, or someone else's, this is the caveat that
   matters — use a paid tier or a [local model](#running-a-local-model).
3. **Tighter throughput.** Expect 429s. Lower `--workers` to 1–2 and `--rpm` to match your
   tier; the tool backs off and retries, but a run that keeps hitting the wall is slow.

Free-tier keys also hit the same [recitation filter](#refused-pages) as paid ones. That is a
content policy, not a billing tier.

### Other hosted providers

Pick one with `--provider`. `bettermarkitdown providers` lists them, with each one's
default model and whether a key is set:

| `--provider` | Service | Key variable | Default model |
|---|---|---|---|
| `gemini` | Google Gemini (free tier available) | `GEMINI_API_KEY` | `gemini-3.6-flash` |
| `openai` | OpenAI | `OPENAI_API_KEY` | `gpt-5.4-mini` |
| `anthropic` | Claude, through Anthropic's SDK (`pip install "bettermarkitdown[anthropic]"`) | `ANTHROPIC_API_KEY` | `claude-opus-5-5` |
| `kimi` | Moonshot Kimi | `MOONSHOT_API_KEY` | none: choose with `--model` |
| `openrouter` | OpenRouter: one key, many models | `OPENROUTER_API_KEY` | `qwen/qwen3-vl-8b-instruct` |
| `ollama` | A model on your own computer | none | `qwen3-vl:8b-instruct` |
| `custom` | Any other OpenAI-compatible server (`--base-url`) | `BMID_API_KEY` | none |

```bash
bettermarkitdown key set anthropic
python -m bettermarkitdown book.pdf --provider anthropic --model claude-haiku-5-5

# OpenRouter: one key, many models
python -m bettermarkitdown book.pdf --provider openrouter
```

Set a default once with `BMID_PROVIDER` (and `BMID_MODEL`). A ChatGPT, Claude or Gemini
*subscription* does not include API access; each company bills its API separately.

Notes on individual providers:

- **Claude:** the current models always think a little before answering; `--reasoning none`
  asks for the lowest effort, which is all transcription needs. On models that support it,
  a request that a safety check declines is retried on another Claude model within the same
  call (Anthropic's server-side fallback).
- **OpenAI:** GPT-5 models refuse `max_tokens` and any temperature but the default. The
  tool sends what each model accepts, and learns from a refusal so it costs one call at
  most.

Two things to know when you leave Gemini:

- **The cost meter knows the prices of the models in the table above** (Gemini, OpenAI,
  Claude; checked on the date recorded in `bettermarkitdown/providers/__init__.py`). For
  any other model it reports **$0.00** rather than inventing a bill. Pass `--price-in` /
  `--price-out` (USD per 1M tokens) to get real numbers, and note that `--budget-usd`
  cannot stop a run whose prices it does not know.
- **The model must accept images.** `--list-models` prints what your key can reach. On a
  non-Gemini endpoint it lists everything the server offers, because there is no reliable way
  to tell which of those are multimodal — check the provider's docs.

---

## Running a local model

A model on your own machine changes the trade-offs completely: **nothing leaves your
computer, there is no quota, no per-page cost, and no recitation filter.** What you give up
is speed and, on the smaller models, accuracy on exactly the hard parts — dense mathematical
notation, multi-column layout, small print in figures.

**Which model fits your computer?** Ask it; nothing is downloaded:

```bash
bettermarkitdown system          # memory, graphics, disk, and a suggested model with the reason
bettermarkitdown system --json   # the same, for scripts
```

It suggests the largest Qwen3-VL size that runs well on the machine: 2B on 8 GB, 4B on
16 GB, 8B on 32 GB or with a graphics card of 8 GB or more, or on a Mac with 16 GB. It warns
when pages would be read by the processor alone, and lists every size with what it is good
at and its limits, so you choose. What we measured on a Core Ultra 7 laptop (processor only):

| | Per page | Text, tables, formulas | Textbook chart | Slide with two hand-drawn graphs |
|---|---|---|---|---|
| Qwen3-VL 4B | ~90 s | correct | one line | skipped |
| Qwen3-VL 8B | ~130-190 s | correct | nearly as good as Gemini | skipped |

Local models can leave a diagram out altogether, so check every figure, or use an online
provider for figure-heavy documents.

**Set it up in one command.** [Ollama](https://ollama.com) runs the model; the tool installs
it for you (Windows, through winget) and asks before installing or downloading anything:

```bash
bettermarkitdown local setup        # suggest a model, install Ollama, download, time a test page
```

Or step by step:

```bash
bettermarkitdown local install      # Ollama itself
bettermarkitdown local pull 4b      # 2b, 4b, 8b, or any Ollama tag; shows the size first
bettermarkitdown local test 4b      # seconds per page on this computer, and a plain verdict
bettermarkitdown local status       # what is installed and running
python -m bettermarkitdown book.pdf --provider ollama --model qwen3-vl:4b-instruct
```

Three things happen without you having to know about them:

- **Pages are not cut short.** Ollama gives every model a 4,096-token context, which a page
  image plus a dense transcription overflows without any error. The tool converts with a copy
  of the model that has a 12,288-token context (`bmid-qwen3-vl-4b-instruct`: settings only,
  no second download).
- **One page at a time, no throttle.** A local server works on one request at a time anyway,
  and parallel requests fight over memory, so `--workers 1 --rpm 0` are the defaults for
  `--provider ollama`.
- **Ollama is reached at 127.0.0.1**, not localhost, which on Windows tries IPv6 first and
  loses seconds on every page.

Any other OpenAI-compatible server (LM Studio, llama.cpp, vLLM) works with
`--provider custom --base-url http://...`. Set its context length yourself.

### Light models worth downloading

Sizes are the Ollama download where one exists; VRAM in practice runs somewhat above that.

| Model | Size | Why it is on this list |
|---|---|---|
| [**Qwen3-VL 8B**](https://ollama.com/library/qwen3-vl) | 6.1 GB | The reasonable default. OCR across 32 languages, holds up on blurred, tilted and badly lit scans. Fits a 12 GB card. `qwen3-vl:4b` (3.3 GB) and `:2b` (1.9 GB) trade accuracy for a smaller machine. |
| [**Granite-Docling 258M**](https://huggingface.co/ibm-granite/granite-docling-258M) | ~0.5 GB | Purpose-built for document conversion rather than general vision, with IBM's DocTags structural output. Astonishing capability per megabyte; runs on CPU. |
| [**PaddleOCR-VL 0.9B**](https://huggingface.co/PaddlePaddle/PaddleOCR-VL) | ~2 GB | Document parsing specialist — text, tables, formulas and charts across 109 languages, from a 0.9B model. |
| [**Nanonets-OCR2-3B**](https://huggingface.co/nanonets/Nanonets-OCR2-3B) | ~6 GB | Tuned for OCR to structured Markdown, including LaTeX for equations. A good middle option when math matters. |
| [**olmOCR 2**](https://github.com/allenai/olmocr) | ~15 GB | Allen AI's PDF-to-text pipeline, trained specifically on document linearization. Heavier, but built for this exact job. |
| [**Qwen2.5-VL 3B / 7B**](https://ollama.com/library/qwen2.5vl) | 3.2 / 6 GB | The previous generation, still strong on documents and very widely supported — the safe choice if a newer model misbehaves in your runtime. |

### Related tools worth knowing about

BetterMarkItDown is a MarkItDown wrapper. For some documents a purpose-built pipeline is
simply the better instrument, and it is worth knowing when to reach for one:

- [**Docling**](https://docling-project.github.io/docling/) (IBM) — document conversion with
  layout understanding, and a
  [catalog of local vision models](https://docling-project.github.io/docling/usage/vision_models/)
  it can drive via Transformers or MLX. Fastest route to Granite-Docling.
- [**Marker**](https://github.com/datalab-to/marker) — PDF to Markdown with strong table and
  equation handling.
- [**MinerU**](https://github.com/opendatalab/MinerU) — high-resolution document parsing,
  aimed at scientific PDFs.
- [**RapidOCR**](https://github.com/RapidAI/RapidOCR) — already bundled here as the
  [refusal fallback](#refused-pages); a solid choice on its own for plain text scans.
- [**Top 7 Open Source OCR Models**](https://www.kdnuggets.com/top-7-open-source-ocr-models) —
  a current survey if none of the above fits.

### Setting expectations honestly

On lecture notes full of `\frac`, subscripts and tagged equations, an 8B local model will get
the prose right and make mistakes in the notation that a frontier model does not. That is a
fine trade for a first pass, for private documents, or for bulk work you will proofread —
and a poor one if you are relying on the math being correct without checking it. Convert five
pages locally and five through a hosted model, read both, and decide with evidence.

---

## What it costs

Measured on a dense scanned textbook page at Gemini 3.6 Flash paid rates
($0.75 / $3.75 per 1M tokens):

| | Input | Billed output | Per page | 400-page book |
|---|---|---|---|---|
| Thinking on | 1,293 | 2,061 | $0.0087 | ~$3.50 |
| **Thinking off (default)** | 1,293 | 475 | **$0.0028** | **~$1.10** |

**Gemini bills hidden thinking tokens as output, and they do not appear in
`completion_tokens`** — they are the gap between `total_tokens` and
`prompt_tokens + completion_tokens`. On that page the model spent 1,574 thinking tokens to
produce a 475-token transcription: **77% of the bill was deliberation about an OCR task.**
Output with `reasoning_effort="none"` was character-for-character equivalent, so that is
the default. The cost meter counts `total - prompt` as output, so the number it reports is
what you are actually charged.

---

## Refused pages

Vision models refuse some pages of published books:

```
finish_reason: content_filter: RECITATION
```

That is Google's copyright guardrail against reproducing text it recognises from its
training data. It is deterministic — the same page fails every time — and **this project
does not try to defeat it.** No tiling pages into fragments, no rewording the prompt to
disguise the request.

Nor does it transcribe those pages word for word some other way. What a student needs from
the page is its knowledge, so the tool asks the model for something it does offer: **study
notes on the page, in the model's own words**. They are checked against the page by a
second request and revised once if that finds something wrong or missing; the page's
equation, example, table and figure numbers (read free from its text layer) must each
appear, and any that do not are listed; any line that shares eight or more words in a row
with the page is removed. Each such page is labelled "Study notes, not the book's text" and
names the PDF page to read for the full text. After a revision the notes are checked once
more, and whatever that check still questions is listed above them, to compare with the
page. A refused page costs up to four requests. `--no-study-notes` skips this.

Measured on six textbook pages with Gemini 3.6 Flash, run as if refused and compared with a
reviewed transcription (`scripts/notes_eval.py`): no copied wording, every numbered item and
every printed figure kept, and the formulas right where checked by hand. But after one
revision the final check still questioned five statements and five omissions across the six
pages, and at least one was a real slip (a "parameter" where the book means a "variable").
The checking request is itself a model and is sometimes wrong too. Treat study notes as
notes: read the original page when the exact wording or a detail matters.

If the notes fail too, the page goes to [RapidOCR](https://github.com/RapidAI/RapidOCR)
running locally on your own file. Nothing leaves your machine, and OCR is the right tool for
reading a scan anyway. The trade-off is real and the output says so in an HTML comment on
every affected page: layout is flattened, and mathematical notation is unreliable. Disable
with `--no-ocr-fallback`.

On a 163-page textbook, 4 pages hit this. On a 20-page set of lecture notes, 2 did — and
those two were a professor's own notes, not a published book, which is a useful reminder
that the filter matches patterns rather than checking who holds the copyright. Where it
lands on pages you need, render them from the PDF and read the image directly; that beats
any transcription.

---

## Reviewing the output

A conversion is a first draft. How good a draft depends on the source. Two full reviews
against the page images:

| | Scanned textbook (163 pp.) | LaTeX lecture notes (45 pp.) |
|---|---|---|
| Wording | Matched the book in every spot check | **Every word** matched the PDF text layer (`--verify`) |
| Equations | Exact in every spot check | 1 wrong subscript in ~135 display equations |
| Diagram descriptions | **22 of 93 wrong** | 1 of 24 wrong |
| Refused pages → local OCR | 4, with wrong numbers in a problem set | 2, words right but math garbage |

What that means in practice:

- **Body text and equations: reliable.** The one equation error is instructive: the notes
  printed a typo (`A_I`) and the model silently "corrected" it to a *different wrong* symbol
  (`A_1`). A vision model normalises what it reads, so a slip in the source can come out as
  a different slip.
- **The book's own figure captions: verbatim.**
- **The model's descriptions of diagrams: not reliable.** 22 of 93 were factually wrong, and
  about 1 in 4 analytical diagrams had a point, label or curve in the wrong place (two
  indifference curves swapped, a point attached to the wrong line, a line described that
  isn't drawn). Descriptions of data charts were rarely wrong but usually empty.
- **Local-OCR pages: wrong where it matters.** In a problem set, `π = 0.8` came out as
  `T = 0.8` and `a = 1` as `a  l`.

- **Dense diagrams are the weak spot.** The notes' simple, cleanly drawn diagrams did much
  better than the textbook's scanned, multi-curve figures, but still had one error.

If the Markdown is going to be used as context for an LLM, which then repeats a wrong figure
description with confidence, review at least the OCR pages and the diagrams.

### Check the wording for free: `--verify`

A born-digital PDF carries its words in a text layer. That layer is too mangled to *be* the
transcription (ligatures, split words, math glyphs out of order), which is why this tool
reads the page image instead. But it is an exact record of *which words* are on the page:

```bash
python -m bettermarkitdown notes.pdf -o notes.md --work-dir <same as before> --verify
```

This compares every finished page with the text layer and lists the pages where words were
dropped, invented or changed, including a single swapped word. It makes no API calls and
exits with code 3 if anything is flagged. It also always flags pages still holding local-OCR
text: OCR tends to get the words right and the math wrong, so a word match proves nothing
there.

**Numbers are compared too, separately from words.** A table of results can have every word
right and one figure wrong, and before v1.2.0 that page passed. Now any number that differs
flags the page:

```text
page 21: FLAGGED (34 words in the text layer)
    missing from the Markdown: -
    not in the PDF:            -
    numbers missing:           1336749
    numbers not in the PDF:    1386749
```

Thousands separators do not count as differences (`70,000`, `70 000` and `$70,000$` are
the same number), and neither does a number that equation text layers scatter into pieces
(`1.96` stored as `96` and `.1`). On 338 checked pages of lecture slides, LaTeX notes and
survey documentation, the number check did not flag a single page that the word check had
passed. Pages
[cut off at the output limit](#how-resuming-works) are always flagged.

It also checks, on every page including scanned ones, that the math is still well-formed:
unmatched `$$`, a blank line or a review note inside a display equation, and unmatched
`\begin`/`\end`. Pasting a `*[sic]*` note into the middle of an `aligned` block is an easy
slip during a review, and it breaks the equation silently.

With Node.js and KaTeX installed (see [Install](#install)), it then renders every
`$$display$$` and `$inline$` formula with KaTeX, the renderer most Markdown viewers use,
and lists any that fail, by page:

```
page 168: broken math -- KaTeX parse error: Unexpected end of input in a macro argument, expected '}' at end of input: \frac{a}{b in `\frac{a}{b`
Math render check (KaTeX): 1 formula(s) failed to render.
```

A 206-page textbook (4,600 formulas) checks in a few seconds. The most common real-world
failure is not LaTeX at all: a dollar amount like `$100 ... $5.97` written without a
backslash is read as one long formula. Write currency as `\$100`.

**Markup the word count cannot see.** Every page, scanned or not, is also checked for:

| Problem | Example | Why it matters |
|---|---|---|
| Invented footnote text | `[^7]: [footnote text not present on this page]`, `[^8]: 8` | In a book with chapter endnotes, the model used to make up a note on every page with a marker |
| A note repeating the body | `[^2]:` + a sentence copied from the page | Same cause, other symptom |
| Marker written as math | `book.$^{24}$`, `Pischke$^{12}$` | It renders as a superscript, not a footnote |
| Note label fused to its text | `[^8]Jeffery M. Wooldridge…`, `[<u>20</u>]Everaert…` | Not a footnote definition in any renderer |
| Unescaped money | `price of $1.10, we estimate…` | Pairs with the next `$` and turns the sentence into a formula |
| LaTeX table commands | `\multicolumn{2}{c}{…}` in a pipe table | Markdown tables cannot render them |
| LaTeX outside math | `$\mathrm{E}(y_t) = \mu$ \tag{6.18}`, a bare `\begin{align*}` | Prints as source code. The model puts an equation number after inline math, or alone at the top of the page after its equation |
| A link target with a space | `[Exercise 9.29](Exercise 9.29)`, `![fig](My Notes_assets/…)` | CommonMark ends the target at the space, so it shows as plain text |

The math check also catches more than one `\tag` in one display equation, the form the
model uses for a numbered `aligned` block: KaTeX and MathJax allow one tag per display, so
the whole block fails. New conversions repair it on the way in, as `\qquad (6.85)` at the
end of each line.

On a 672-page econometrics textbook this check found 60 such faults in pages that had
already been reviewed by eye, 41 of them unescaped dollar amounts.

**Read every word list, even on pages you trust.** The model sometimes "improves" the
text: it corrected two of the book's own typos ("multpliers", "test for nonstationary") and
dropped "*FBABY*, along with" from an exercise, which changed the model the exercise asks
for. Each showed up only as one or two words in the `missing` / `not in the PDF` lists. Put
the book's typos back as printed with a `*[sic: …]*` note.

**Tables that are pictures.** A results table is often an image in an otherwise
born-digital page. The model transcribes it as a Markdown table, and the text layer has none
of its words. On a page that holds an image, unmatched words and numbers in table rows are
therefore listed as `from an image, unchecked` instead of flagging the page, and the report
names those pages at the end. Compare their tables with the page image.

Two more false differences are gone in v1.4.0. Variables written as math (`$LLF$`, `$L_u$`)
used to be reported missing, because the math was joined into one string before ligature
pairs were dropped: `llflu` lost its `fl`. And a text layer that silently drops an accented
letter (`naïve` stored as `nave`) no longer flags the page. Any other changed letter still does.

It does not check whether equations and figure descriptions are *correct*, or the words of
scanned pages (no text layer). The report lists the pages it could not check, and those
still need a look at the page image.

**Fix the work dir, not the output.** The output is rebuilt from `<work-dir>/pages/`, so
edit `<work-dir>/pages/NNNN.md` and then rerun the same command with `--no-vision` added.
Every page already exists, so nothing is converted and nothing is billed. The output is
reassembled with your edits. A `--verify` run never rewrites the output, so rebuild after it.

Page files are written with `\n` line endings on every platform (since v1.4.0; older work
dirs on Windows have `\r\n`). A patch script that matches `"\n\n"` against an older page
finds nothing and changes nothing, without an error. Read pages as bytes, or normalise
line endings first.

> **Never pass `--fresh` to a work dir you have edited.** It re-converts every page and
> overwrites your fixes.

Conventions that keep a reviewed file honest:

| Mark | Meaning |
|---|---|
| `<!-- source: study notes … -->` | Written by the tool on a page the model refused: notes in the model's own words, not the book's text. Fix a wrong statement, but do not edit them towards the book's wording, and do not retype a refused page instead |
| `*[corrected in review: the original said …]*` | The model's description was wrong; record what it claimed |
| `*[added in review]*` | Something important was missing, e.g. the data behind a chart |
| `*[sic: …]*` | The **source** has the error; it is transcribed as printed and the note gives the intended reading. Keeps "the transcription is wrong" apart from "the professor made a typo" |

Two more tricks follow from "the output is every file in `pages/`, in name order":

- **A notes page.** `pages/0000.md` sorts first, so it becomes the top of the output: say how
  the file was made, how far to trust each part, and what was corrected. A reader (or an
  LLM) sees it before anything else, and it survives every rebuild.
- **Dropping pages.** To leave out covers or blank pages, move their files out of `pages/`
  (for example to `<work-dir>/excluded/`). `--pages` does not do this, by design.
- **Marking pages you have not converted yet.** When you convert a book a few chapters at a
  time, say where the gaps are, so a reader (or an LLM) does not take a missing chapter for
  the end of the book. Append a note to the page *before* the gap, as a blockquote between
  marker comments so a script can find and rewrite it as the gap shrinks:

  ```markdown
  <!-- gap-note -->
  > ### ⏸ Not in this file yet: PDF pages 574–838
  > Chapters 8–11 have not been converted. Read them in the PDF.
  <!-- /gap-note -->
  ```

  `--verify` ignores blockquotes, so the note is never flagged. **Do not** create a
  placeholder `pages/0574.md` instead: any existing page file counts as converted, so that
  page would never be sent to the model.

**Books with chapter endnotes.** Most textbooks print a chapter's notes at its end, not at
the foot of the page. The page prompt now tells the model to write only the marker `[^n]` on
such pages, and `[^n]: text` on the page that lists the notes. A note that runs onto the next
page should be joined into one definition by hand. The labels restart in every chapter, so
the same `[^1]` appears several times in a whole-book file. Most renderers then attach every
`[^1]` to the first definition, so read a note next to its own chapter's list.

---

## Options

| Flag | Default | What it does |
|---|---|---|
| `-o, --output` | next to the PDF | Where the `.md` goes |
| `--pages` | all | `5`, `10-40`, `1,5,9-12` |
| `--toc` | — | Print the PDF's outline with each chapter's and section's page range, then exit. A range includes the page where the next section starts when that section begins below text |
| `--title` | the PDF's file name | The output's `#` heading. Pass it on every rebuild, or the file name comes back |
| `--work-dir` | next to the output | Resume state and response cache. **Point this at a local disk if your output lives in Google Drive / OneDrive / Dropbox** |
| `--provider` | `gemini` | `gemini`, `openai`, `anthropic`, `kimi`, `openrouter`, `ollama` or `custom`. Also read from `$BMID_PROVIDER`, then from the setup page's choice |
| `--model` | the provider's own | Also read from `$BMID_MODEL` |
| `--base-url` | Gemini | Any OpenAI-compatible endpoint, e.g. `http://localhost:11434/v1`. Also read from `$BMID_BASE_URL` |
| `--list-models` | — | Print the models your key can reach, then exit |
| `--reasoning` | `none` | Thinking budget. `none` is ~3× cheaper with no measured quality loss |
| `--dpi` | 200 | Render resolution. 300 for small or ornate type |
| `--max-edge` | 1568 | Downscale page and figure uploads to this long edge before sending |
| `--min-chars` | 120 | Below this many non-space characters, a page counts as scanned. Set it huge to force vision on every page |
| `--min-figure-pt` | 60 | Ignore figures smaller than this many points — skips rules, logos and bullet glyphs |
| `--ignore-small-images` | off | Keep text-layer pages with images smaller than a figure on the free text path. By default they are [transcribed whole](#when-the-equations-are-pictures), because such images are usually equations |
| `--figure-pad` | 22 | Points of margin around figure crops, so captions come along |
| `--workers` | 3 | Pages converted in parallel. Use 1 for a local model |
| `--rpm` | 60 | Request throttle. Lower it if you see 429s, `0` to disable |
| `--budget-usd` | none | Stop cleanly at this spend. Resumable. Needs known prices to work |
| `--price-in` | model's list price | USD per 1M input tokens — required on non-Gemini endpoints |
| `--price-out` | model's list price | USD per 1M output tokens |
| `--estimate N` | off | Convert N pages, measure, project the rest |
| `--no-vision` | off | Text only, zero API calls |
| `--every-page` | off | Read every page whole with the AI, not only scanned pages and figures: best for maths, which a text layer often garbles. One request per page |
| `--as-pages` | off | Word / PowerPoint: turn the file into a PDF first and convert it page by page |
| `--library` | off | Convert the copy in the setup page's library, for review there. Results go to `Documents\BetterMarkItDown`; `-o` and `--work-dir` are ignored |
| `--json` | off | One JSON object per line on standard output, for scripts and agents. See [With an AI agent](#with-an-ai-agent) |
| `--no-study-notes` | off | On a refused page, go straight to local OCR instead of asking for [study notes](#refused-pages) |
| `--no-page-images` | off | Don't save a PNG of each scanned page |
| `--no-ocr-fallback` | off | Leave refused pages unconverted instead of using local OCR |
| `--fresh` | off | Redo pages already finished. **Overwrites hand edits in the work dir** — see [Reviewing the output](#reviewing-the-output) |
| `--verify` | off | Convert nothing; check the words and numbers of finished pages against the PDF text layer, and render every formula with KaTeX if Node.js is installed. See [`--verify`](#check-the-wording-for-free---verify) |

---

## How resuming works

```
book.md                 the output, rewritten every 10 pages while running
book_assets/            extracted figures, only created if something is written to it
<work-dir>/pages/       one .md per page — the resume state
<work-dir>/cache.json   responses keyed by image hash — reruns cost nothing
```

Delete the work dir to force a full, fully-billed re-run.

Five behaviours here were bought with real mistakes, and the tests lock them in:

- **Empty responses are never cached.** Caching a blank makes the loss permanent: the next
  run "resumes" straight past the page and you never learn it is missing.
- **A reply that is only an HTML comment counts as empty.** The page prompt asks for a
  trailing `<!-- page number: N -->`, and a model that transcribes nothing can still return
  `<!-- page number:  -->`. That once passed as a transcription: two pages of a textbook
  came out blank, with no OCR fallback and no failure reported. Such replies are now
  retried, never cached, and ignored if an older version cached them.
- **Output is assembled from the whole work dir, never from the current `--pages`
  selection.** Otherwise rerunning four pages rewrites your book as those four pages.
- **A `content_filter` verdict is not retried.** It will never succeed, and five retries
  with exponential backoff waste a minute per page.
- **A reply cut off at the output limit is not accepted as the page.** Each reply was
  capped at 4,096 tokens, and a page holding a dense table needs more. The model stopped
  mid-row and that partial page was cached as complete: the rest of the table and the
  paragraphs below it were lost without a warning. Now a cut-off reply is retried with
  room for 16,384 tokens, which costs nothing on pages that fit the first time. If it is
  still cut off, the page keeps what came back plus a visible
  `*[transcription cut off: …]*` note. It is listed at the end of the run, flagged by
  `--verify`, and never cached.

---

## Requirements

Python 3.10+, and a vision model to talk to — a hosted API key, or a local server.

```
markitdown[pdf,docx,pptx]  openai  pymupdf  pillow  rich  keyring   # requirements.txt
rapidocr-onnxruntime   # optional, for the local OCR fallback
anthropic              # optional, for Claude through Anthropic's SDK
Node.js + katex        # optional, for the math render check in --verify (package.json)
```

### Environment variables

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | Gemini key |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `MOONSHOT_API_KEY`, `OPENROUTER_API_KEY` | That provider's key; each provider reads only its own |
| `BMID_API_KEY` | Key for a `custom` server (falls back to `OPENAI_API_KEY`) |
| `BMID_PROVIDER` | Default provider, instead of passing `--provider` |
| `BMID_BASE_URL` / `OPENAI_BASE_URL` | Default endpoint, instead of passing `--base-url` |
| `BMID_MODEL` | Default model, instead of passing `--model` |
| `BMID_KATEX_DIR` | A folder whose `node_modules` holds KaTeX, if it is not in the repo or the global npm root |

All of these can live in `.env` instead. A real environment variable always wins over the
file, and both win over a key saved with `bettermarkitdown key set`.

## Tests

```bash
pip install pytest
python -m pytest tests -q
```

The suite never touches the network — it generates its own PDF, covers the billing
arithmetic, and includes regression tests for the data-loss bugs above. The KaTeX render
test is skipped when Node.js or KaTeX is missing; CI installs both so it always runs there.

## Releasing a new version

The version number lives in one place, `__version__` in `bettermarkitdown/__init__.py`.

1. Bump `__version__` (patch for fixes, minor for features, major for breaking changes).
2. Add a `## [X.Y.Z] - YYYY-MM-DD` section at the top of [CHANGELOG.md](CHANGELOG.md) with a
   short **What's New** for users, and update the version in the Install command above.
3. Commit, then tag and push:

   ```bash
   git tag v1.2.0 && git push origin main v1.2.0
   ```

The [release workflow](.github/workflows/release.yml) then checks that the tag matches
`__version__` and that the changelog has a section for it, builds and tests the wheel, and
publishes a GitHub Release with the wheel and source archive attached and that version's
What's New as the notes. A second job builds the Windows installer, installs, runs and
uninstalls it on a clean Windows machine, and attaches it to the same release. A missing changelog section or a mismatched tag stops it before
anything is published. To rehearse, run the workflow by hand from the Actions tab: it does
everything except publish.

## License

MIT — see [LICENSE](LICENSE).

Converting a copyrighted book is your call and your responsibility; this tool only
automates work on files you already have. Don't commit the PDFs — `.gitignore` excludes
`*.pdf` by default.
