# BetterMarkItDown

**Turn scanned and image-heavy PDFs into Markdown that actually contains the content.**

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

---

## Install

```bash
pip install -r requirements.txt          # from inside the repo
pip install -e .                         # or install it as a package
```

<!-- Not yet published to GitHub. Once it is, this becomes:
     git clone https://github.com/YOUR-USERNAME/BetterMarkItDown.git -->

> **The `[pdf]` extra is not optional.** A plain `pip install markitdown` cannot open a PDF
> at all — it raises `MissingDependencyException` on every page. `requirements.txt` pins
> `markitdown[pdf]` for exactly this reason.

Then add your key. Get one free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey):

```bash
cp .env.example .env     # then edit .env and paste your key
```

The tool reads, in order: `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `OPENAI_API_KEY`. A real
environment variable always beats the `.env` file, so you can keep the key in your user
environment and never have a secret in the repo at all.

`.env` is gitignored. No key is ever written to disk by the tool, printed in full, or
committed.

---

## Use it

### Interactive (recommended the first time)

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

# A section, with a spending cap
python -m bettermarkitdown book.pdf --pages 40-80 --budget-usd 2 --workers 4

# Against a model on your own machine
python -m bettermarkitdown book.pdf --base-url http://localhost:11434/v1 --model qwen3-vl:8b
```

### As a library

```python
from pathlib import Path
from bettermarkitdown import Options, convert

result = convert(Options(pdf=Path("book.pdf"), output=Path("book.md"), api_key="..."))
print(result.pages_converted, result.cost)
```

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

Any OpenAI-compatible endpoint works:

```bash
# OpenAI
python -m bettermarkitdown book.pdf \
  --base-url https://api.openai.com/v1 --model gpt-5-mini \
  --price-in 0.25 --price-out 2.00

# OpenRouter — one key, many models
python -m bettermarkitdown book.pdf \
  --base-url https://openrouter.ai/api/v1 --model qwen/qwen3-vl-8b-instruct
```

Set the key in `OPENAI_API_KEY`, or the endpoint once in `BMID_BASE_URL` and the model in
`BMID_MODEL`.

Two things to know when you leave Gemini:

- **The cost meter only knows Gemini's price list.** On any other endpoint it reports
  **$0.00** rather than inventing a bill. Pass `--price-in` / `--price-out` (USD per 1M
  tokens) to get real numbers, and note that `--budget-usd` cannot stop a run whose prices
  it does not know.
- **The model must accept images.** `--list-models` prints what your key can reach. On a
  non-Gemini endpoint it lists everything the server offers, because there is no reliable way
  to tell which of those are multimodal — check the provider's docs.

---

## Running a local model

A model on your own machine changes the trade-offs completely: **nothing leaves your
computer, there is no quota, no per-page cost, and no recitation filter.** What you give up
is speed and, on the smaller models, accuracy on exactly the hard parts — dense mathematical
notation, multi-column layout, small print in figures.

Anything with an OpenAI-compatible server works. [Ollama](https://ollama.com) is the
shortest path:

```bash
ollama pull qwen3-vl:8b
python -m bettermarkitdown book.pdf \
  --base-url http://localhost:11434/v1 \
  --model qwen3-vl:8b \
  --workers 1 --rpm 0
```

`--workers 1` because a local server usually processes one request at a time anyway, and
parallel requests just fight over VRAM. `--rpm 0` removes a throttle you no longer need.

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

Instead, those pages go to [RapidOCR](https://github.com/RapidAI/RapidOCR) running locally
on your own file. Nothing leaves your machine, no provider policy is involved, and OCR is
the right tool for reading a scan anyway. The trade-off is real and the output says so in
an HTML comment on every affected page: layout is flattened, and mathematical notation is
unreliable. Disable with `--no-ocr-fallback`.

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

It does not check math, figures, or scanned pages (no text layer). The report says how many
pages it could not check, and those still need a look at the page image.

**Fix the work dir, not the output.** The output is rebuilt from `<work-dir>/pages/`, so
edit `<work-dir>/pages/NNNN.md` and then rerun the same command with `--no-vision` added.
Every page already exists, so nothing is converted and nothing is billed. The output is
reassembled with your edits.

> **Never pass `--fresh` to a work dir you have edited.** It re-converts every page and
> overwrites your fixes.

Conventions that keep a reviewed file honest:

| Mark | Meaning |
|---|---|
| `<!-- source: transcribed by hand from the page scan … -->` | Replaces the local-OCR comment on a page you retyped |
| `*[corrected in review: the original said …]*` | The model's description was wrong; record what it claimed |
| `*[added in review]*` | Something important was missing, e.g. the data behind a chart |
| `*[sic: …]*` | The **source** has the error; it is transcribed as printed and the note gives the intended reading. Keeps "the transcription is wrong" apart from "the professor made a typo" |

Two more tricks follow from "the output is every file in `pages/`, in name order":

- **A notes page.** `pages/0000.md` sorts first, so it becomes the top of the output: say how
  the file was made, how far to trust each part, and what was corrected. A reader (or an
  LLM) sees it before anything else, and it survives every rebuild.
- **Dropping pages.** To leave out covers or blank pages, move their files out of `pages/`
  (for example to `<work-dir>/excluded/`). `--pages` does not do this, by design.

---

## Options

| Flag | Default | What it does |
|---|---|---|
| `-o, --output` | next to the PDF | Where the `.md` goes |
| `--pages` | all | `5`, `10-40`, `1,5,9-12` |
| `--work-dir` | next to the output | Resume state and response cache. **Point this at a local disk if your output lives in Google Drive / OneDrive / Dropbox** |
| `--model` | `gemini-3.6-flash` | Also read from `$BMID_MODEL` |
| `--base-url` | Gemini | Any OpenAI-compatible endpoint, e.g. `http://localhost:11434/v1`. Also read from `$BMID_BASE_URL` |
| `--list-models` | — | Print the models your key can reach, then exit |
| `--reasoning` | `none` | Thinking budget. `none` is ~3× cheaper with no measured quality loss |
| `--dpi` | 200 | Render resolution. 300 for small or ornate type |
| `--max-edge` | 1568 | Downscale page and figure uploads to this long edge before sending |
| `--min-chars` | 120 | Below this many non-space characters, a page counts as scanned. Set it huge to force vision on every page |
| `--min-figure-pt` | 60 | Ignore figures smaller than this many points — skips rules, logos and bullet glyphs |
| `--figure-pad` | 22 | Points of margin around figure crops, so captions come along |
| `--workers` | 3 | Pages converted in parallel. Use 1 for a local model |
| `--rpm` | 60 | Request throttle. Lower it if you see 429s, `0` to disable |
| `--budget-usd` | none | Stop cleanly at this spend. Resumable. Needs known prices to work |
| `--price-in` | model's list price | USD per 1M input tokens — required on non-Gemini endpoints |
| `--price-out` | model's list price | USD per 1M output tokens |
| `--estimate N` | off | Convert N pages, measure, project the rest |
| `--no-vision` | off | Text only, zero API calls |
| `--no-page-images` | off | Don't save a PNG of each scanned page |
| `--no-ocr-fallback` | off | Leave refused pages unconverted instead of using local OCR |
| `--fresh` | off | Redo pages already finished. **Overwrites hand edits in the work dir** — see [Reviewing the output](#reviewing-the-output) |
| `--verify` | off | Convert nothing; check finished pages against the PDF text layer. See [`--verify`](#check-the-wording-for-free---verify) |

---

## How resuming works

```
book.md                 the output, rewritten every 10 pages while running
book_assets/            extracted figures, only created if something is written to it
<work-dir>/pages/       one .md per page — the resume state
<work-dir>/cache.json   responses keyed by image hash — reruns cost nothing
```

Delete the work dir to force a full, fully-billed re-run.

Three behaviours here were bought with real mistakes, and the tests lock them in:

- **Empty responses are never cached.** Caching a blank makes the loss permanent: the next
  run "resumes" straight past the page and you never learn it is missing.
- **Output is assembled from the whole work dir, never from the current `--pages`
  selection.** Otherwise rerunning four pages rewrites your book as those four pages.
- **A `content_filter` verdict is not retried.** It will never succeed, and five retries
  with exponential backoff waste a minute per page.

---

## Requirements

Python 3.10+, and a vision model to talk to — a hosted API key, or a local server.

```
markitdown[pdf]  openai  pymupdf  pillow  rich
rapidocr-onnxruntime   # optional, for the local OCR fallback
```

### Environment variables

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` / `OPENAI_API_KEY` | API key, tried in that order |
| `BMID_BASE_URL` / `OPENAI_BASE_URL` | Default endpoint, instead of passing `--base-url` |
| `BMID_MODEL` | Default model, instead of passing `--model` |

All of these can live in `.env` instead. A real environment variable always wins over the
file.

## Tests

```bash
pip install pytest
python -m pytest tests -q
```

The suite never touches the network — it generates its own PDF, covers the billing
arithmetic, and includes regression tests for the two data-loss bugs above.

## License

MIT — see [LICENSE](LICENSE).

Converting a copyrighted book is your call and your responsibility; this tool only
automates work on files you already have. Don't commit the PDFs — `.gitignore` excludes
`*.pdf` by default.
