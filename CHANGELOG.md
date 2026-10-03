# What's New

Every version of BetterMarkItDown, newest first. Each GitHub Release uses its section of
this file as its release notes.

Versions follow [semantic versioning](https://semver.org): a **patch** (1.1.**1**) only
fixes bugs, a **minor** (1.**2**.0) adds features without breaking anything, and a
**major** (**2**.0.0) changes how you use the tool.

<!-- Add the next version's section above the newest one, with the same heading format:
     ## [X.Y.Z] - YYYY-MM-DD
     The release workflow refuses to publish a version that has no section here. -->

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
