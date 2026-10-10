# What's New

Every version of BetterMarkItDown, newest first. Each GitHub Release uses its section of
this file as its release notes.

Versions follow [semantic versioning](https://semver.org): a **patch** (1.1.**1**) only
fixes bugs, a **minor** (1.**2**.0) adds features without breaking anything, and a
**major** (**2**.0.0) changes how you use the tool.

<!-- Add the next version's section above the newest one, with the same heading format:
     ## [X.Y.Z] - YYYY-MM-DD
     The release workflow refuses to publish a version that has no section here. -->

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
