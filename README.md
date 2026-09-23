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

It runs on **Google Gemini through its OpenAI-compatible endpoint**, so the `openai` library
you already have works unchanged.

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

A 163-page scanned textbook came out as 464 KB of Markdown: 77,970 words, 2,347 inline
LaTeX expressions, 103 display equations, 92 figure descriptions, 35 footnotes — for
**$0.58**.

---

## Install

```bash
git clone https://github.com/YOUR-USERNAME/BetterMarkItDown.git
cd BetterMarkItDown
pip install -r requirements.txt
```

> **The `[pdf]` extra is not optional.** A plain `pip install markitdown` cannot open a PDF
> at all — it raises `MissingDependencyException` on every page. `requirements.txt` pins
> `markitdown[pdf]` for exactly this reason.

Then add your key. Get one free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey):

```bash
cp .env.example .env     # then edit .env and paste your key
```

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
4. **Run the whole thing** with `--budget-usd` as a seatbelt.
5. **If it stops** — cap, quota, Ctrl+C, dropped network — rerun the identical command. It
   resumes and re-pays for nothing.

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

Free tier is capped around 20 requests/day/model — enough to evaluate, not to convert a
book. Attach billing for real work.

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

On a 163-page textbook, 4 pages hit this. The rest transcribed cleanly.

---

## Options

| Flag | Default | What it does |
|---|---|---|
| `-o, --output` | next to the PDF | Where the `.md` goes |
| `--pages` | all | `5`, `10-40`, `1,5,9-12` |
| `--work-dir` | next to the output | Resume state and response cache. **Point this at a local disk if your output lives in Google Drive / OneDrive / Dropbox** |
| `--model` | `gemini-3.6-flash` | `--list-models` shows what your key can call |
| `--reasoning` | `none` | Thinking budget. `none` is ~3× cheaper with no measured quality loss |
| `--dpi` | 200 | Render resolution. 300 for small or ornate type |
| `--min-chars` | 120 | Below this many non-space characters, a page counts as scanned |
| `--figure-pad` | 22 | Points of margin around figure crops, so captions come along |
| `--workers` | 3 | Pages converted in parallel |
| `--rpm` | 60 | Request throttle. Lower it if you see 429s |
| `--budget-usd` | none | Stop cleanly at this spend. Resumable |
| `--estimate N` | off | Convert N pages, measure, project the rest |
| `--no-vision` | off | Text only, zero API calls |
| `--no-ocr-fallback` | off | Leave refused pages unconverted instead of using local OCR |
| `--fresh` | off | Redo pages already finished |

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

Python 3.10+, and a Gemini API key for the vision features.

```
markitdown[pdf]  openai  pymupdf  pillow  rich
rapidocr-onnxruntime   # optional, for the local OCR fallback
```

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
