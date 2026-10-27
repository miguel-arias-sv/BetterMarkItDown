# What's New

Every version of BetterMarkItDown, newest first. Each GitHub Release uses its section of
this file as its release notes.

Versions follow [semantic versioning](https://semver.org): a **patch** (1.1.**1**) only
fixes bugs, a **minor** (1.**2**.0) adds features without breaking anything, and a
**major** (**2**.0.0) changes how you use the tool.

<!-- Add the next version's section above the newest one, with the same heading format:
     ## [X.Y.Z] - YYYY-MM-DD
     The release workflow refuses to publish a version that has no section here. -->

## [Unreleased]

Work in progress on the `feature/setup-assistant` branch: choosing an AI service, then a
setup page and workspace in the browser.

### What's New

- **Choose your AI service with `--provider`:** Google Gemini, OpenAI, Anthropic (Claude),
  Moonshot Kimi, OpenRouter, Ollama on your own computer, or any other OpenAI-compatible
  server. `bettermarkitdown providers` lists them with their default models and whether a
  key is set.
- **Claude through Anthropic's own SDK** (`pip install "bettermarkitdown[anthropic]"`). The
  lowest thinking effort is used for transcription, and the cost meter knows Claude's prices.
- **Keys in your computer's password store:** `bettermarkitdown key set|test|forget|status`.
  `key test` checks a key for free by listing the models it can use. Environment variables
  and `.env` still work and take precedence.
- The cost meter knows OpenAI's GPT-5.4 mini and nano prices as well as Gemini's.

### Fixed

- **A Gemini key could be sent to another provider.** The key lookup always tried
  `GEMINI_API_KEY` first, whatever the endpoint, so with `BMID_BASE_URL` pointing at OpenAI
  and both keys set, the Google key went to OpenAI's server. Each provider now reads only its
  own variables.
- **Requests to OpenAI's GPT-5 models carried parameters those models refuse**:
  `max_tokens` and `temperature=0`. The tool now sends `max_completion_tokens` and no
  temperature to OpenAI, and drops any parameter a server refuses after the first refusal.

### Changed

- **OpenRouter keys go in `OPENROUTER_API_KEY`**, no longer `OPENAI_API_KEY`, so an OpenAI
  key is never sent to OpenRouter. Run `bettermarkitdown key set openrouter`, or rename the
  variable.

## [1.4.0] - 2026-10-26

Lessons from converting chapters of a publisher's finance textbook that sets every
equation as a picture.

### What's New

- **Pages whose equations are pictures are transcribed whole.** Publishers often set each
  equation as a small embedded image. The text layer has nothing in its place, so the text
  path dropped every equation without a trace: the prose read cleanly with `(12.1)` alone
  on a line. `--verify` could not see it either, since it checks against that same text
  layer. A page with a text layer and images too small to be figures now goes to the
  vision model like a scanned page, and the run summary lists those pages. With
  `--no-vision`, they are listed as a warning. `--ignore-small-images` keeps the old
  behaviour for PDFs whose small images are logos.
- **`--toc` prints the PDF's outline with a page range for every chapter and section**, for
  choosing `--pages` without hunting through the book. A range includes the page where the
  next section starts when that section begins below text, and stops before it when the next
  heading opens the page.
- **`--title` sets the output's heading.** It was always the PDF's file name, which for some
  downloads is 200 characters long. Rewriting the heading by hand did not survive a rebuild.
- **New `--verify` checks.** These were all found in reviewed files:
  - LaTeX printed as source outside math: `$\mu$ \tag{6.18}`, an orphaned `\tag{6.55}` at
    the top of a page, or a bare `\begin{align*}`.
  - Link targets with a space (`[Exercise 9.29](Exercise 9.29)`), which show as plain
    text.
  - More than one `\tag` in one display equation, which KaTeX and MathJax refuse to render.
- **Tables that are pictures are listed, not flagged.** On a page holding an image,
  unmatched words and numbers in Markdown table rows are reported as `from an image,
  unchecked`, and the report names those pages for a check against the image.
- **The page prompt asks for one `\tag` per display equation**, and for an equation number
  whose equation is on another page to be written as plain `(n)`.

### Fixed

- **Numbered `aligned` blocks did not render.** The model put a `\tag` on every line. New
  conversions write those numbers as `\qquad (n)`, which renders.
- **`--verify` reported variables written as math as missing.** Math was joined into one
  string before ligature pairs were dropped, so `$LLF$ $L_u$` became `llflu`, lost its `fl`,
  and the PDF's `LLF` was missing six times on a correct page.
- **A letter the text layer drops outright no longer flags the page**: `naïve` stored as
  `nave`. Only vowels and y, n and c (as in ÿ, ñ and ç) are forgiven.
- **Figure and page-image links broke when the output name had a space.** CommonMark ends a
  link target at the first space, so `![…](My Notes_assets/…)` did not display. Spaces are
  now written as `%20`.
- **Page files and the output are written with `\n` line endings on Windows too.** With
  `\r\n`, a review script that matched `"\n\n"` changed nothing and reported no error.
- **Windows console output.** Piped or redirected, stdout is cp1252 there. A PDF name with
  a curly apostrophe printed as mojibake, and a `--verify` report with a Greek letter
  crashed. Output is now UTF-8.

## [1.3.0] - 2026-10-19

Lessons from converting 672 pages of an econometrics textbook with chapter endnotes.

### What's New

- **`--verify` checks the Markdown itself, not just its words.** Every page, scanned or
  not, is checked for invented footnotes (`[^7]: [footnote text not present on this
  page]`, `[^8]: 8`, or a note that repeats a sentence of the page), footnote markers
  written as math (`book.$^{24}$`), note labels fused to their text (`[^8]Jeffery…`),
  unescaped dollar amounts that renderers read as formulas, and LaTeX table commands such
  as `\multicolumn` inside Markdown tables. On the textbook it found 60 such faults in
  pages that had already been reviewed by eye.
- **A clearer page prompt for footnotes, money, tables and typos.** The old rule, "preserve
  footnotes as [^n] with their text at the end", made the model invent a note on every page
  of a book whose notes are printed at the end of the chapter. The prompt now asks for the
  marker alone there, `[^n]: text` only where the note is printed, `\$` for money, plain
  pipe tables, and the book's typos left as printed. Pages already in a work dir are not
  converted again; only new pages use the new prompt.
- **The report names the pages without a text layer**, instead of only counting them.
- **README: reviewing books with endnotes, and marking chapters not converted yet.**
  Includes a warning learned the hard way: a placeholder `pages/NNNN.md` for a missing page
  stops that page from ever being converted.

### Fixed

- **An escaped `\$` was read as a math delimiter by `--verify`.** `\$1900 … when $P$` paired
  the dollar sign with the formula, hid the words between them from the word check, and
  produced false differences.
- **Footnote numbers no longer flag pages.** The text layer runs a superscript marker into
  what precedes it (`0.9926` + marker 22 becomes `0.992622`), and `[^22]` labels counted as
  numbers in the Markdown. Both are now matched up, which removed most false flags on pages
  with notes.

## [1.2.0] - 2026-10-10

### What's New

- **`--verify` now checks numbers, not just words.** A page with every word right and one
  figure wrong used to pass. Now any number that differs from the PDF flags the page, and
  the report lists it. Thousands separators (`70,000`, `70 000`, `$70,000$`) are not counted
  as differences, and neither are numbers that equation text layers break into pieces. On
  338 pages of real lecture notes, slides and survey documentation, it did not flag a single
  page that the word check had passed.
- **A guide to codebooks, data dictionaries and statistical tables.** For born-digital
  tables, the vision model is the wrong tool: every digit is already exact in the text
  layer. The new README section explains when to parse the layout instead.
  [`examples/codebooks/`](https://github.com/miguel-arias-sv/BetterMarkItDown/tree/main/examples/codebooks)
  does it for Statistics Canada's CCHS 2022
  documentation (255 variables, 59 derived variables, 108 CV tables), with checks that
  every category table sums to its total and every CV fits its formula.
- **Links no longer count as page text in `--verify`.** A URL written as
  `[url](url)` appears twice in the Markdown and once in the PDF, which used to flag the
  page.

### Fixed

- **Long pages could be cut off without warning.** Each reply was capped at 4,096 tokens.
  On a page holding a dense table, the model stopped mid-row and the partial page was
  cached as if it were complete: the rest of the table and the text below it were lost,
  and nothing said so. A cut-off reply is now retried with room for 16,384 tokens, at no
  extra cost on pages that fit the first time. A page that is still cut off keeps what came
  back, ends with a visible note saying it is incomplete, is listed at the end of the run,
  is flagged by `--verify`, and is never cached.

## [1.1.0] - 2026-10-02

### What's New

- **`--verify` now checks that your math renders.** If Node.js and KaTeX are installed,
  every formula is rendered the way a Markdown viewer would show it, and any that would
  appear as a red error box is listed by page. A 200-page textbook checks in seconds.
  Without Node.js the check is simply skipped. See the README's Install section.
- **`bettermarkitdown --version`** prints the version you have installed.
- **Easier installs.** The README has clone-and-install steps, `package.json` covers the
  optional KaTeX part in one `npm install`, and each release on GitHub comes with
  ready-to-install files.

### Fixed

- **Pages could come out blank with no warning.** When the model returned nothing but an
  empty page-number comment (`<!-- page number:  -->`), it was accepted as the page's text
  and cached. Such replies now count as empty: the page is retried, falls back to local
  OCR if needed, and a blank already in the cache from an older version is ignored, so a
  normal rerun repairs those pages.

## [1.0.0] - 2026-09-28

The first public version.

### What's New

- **Converts scanned and image-heavy PDFs to Markdown.** MarkItDown reads the text layer;
  pages without one, and every figure, go to a vision model (Gemini by default), which
  transcribes text, writes equations as LaTeX and describes charts and diagrams.
- **Any OpenAI-compatible model**, hosted or running on your own machine (Ollama, LM
  Studio), through `--base-url`.
- **Interactive wizard** when run with no arguments, plus a full command line.
- **Cost control:** `--estimate` projects the cost from a sample, `--budget-usd` stops at a
  cap, and the meter counts Gemini's hidden thinking tokens.
- **Resumable runs:** every page is cached, so an interrupted run continues where it
  stopped and reruns cost nothing.
- **Local OCR fallback** for pages the model declines under its copyright filter.
- **`--verify`:** a free check of every finished page against the PDF's own text layer,
  flagging dropped, invented or swapped words, pages still holding OCR text, and broken
  equation structure.
- **A documented review workflow** for hand-fixing pages and keeping corrections across
  rebuilds.

[1.1.0]: https://github.com/miguel-arias-sv/BetterMarkItDown/releases/tag/v1.1.0
[1.0.0]: https://github.com/miguel-arias-sv/BetterMarkItDown/releases/tag/v1.0.0
