# What's New

Every version of BetterMarkItDown, newest first. Each GitHub Release uses its section of
this file as its release notes.

Versions follow [semantic versioning](https://semver.org): a **patch** (1.1.**1**) only
fixes bugs, a **minor** (1.**2**.0) adds features without breaking anything, and a
**major** (**2**.0.0) changes how you use the tool.

<!-- Add the next version's section above the newest one, with the same heading format:
     ## [X.Y.Z] - YYYY-MM-DD
     The release workflow refuses to publish a version that has no section here. -->

## [1.5.0] - 2026-10-29

No Python knowledge needed any more: a Windows installer, a setup page and workspace in the
browser, a choice of AI services or a model on your own computer, Word and PowerPoint
files, study notes for pages a model refuses, and a mode for AI agents.

### What's New

- **A Windows installer**, `BetterMarkItDown-Setup-<version>.exe`, attached to each release.
  No Python and no administrator rights needed: it installs for the person alone, gives the
  program its own Python with uv, and adds a Start-menu entry (and, if wanted, a desktop
  icon and the `bettermarkitdown` command on the PATH). Local OCR and Claude support are
  options. Uninstalling removes the program and asks before deleting the library, settings
  and saved keys; converted files in Documents are never touched. Not code-signed yet, so
  Windows SmartScreen warns about it (the README says what to do). An icon, too: the setup
  page game's llama on a page.
- **A setup page in your browser: `bettermarkitdown app`.** It explains why a browser
  opened and when internet is needed, then asks who will use the tool (you, an AI agent,
  or both), how much help you want, and whether you have an API key. It saves and checks a
  key, guides you through getting one, or sets up a model on this computer: computer check,
  model choice with each model's limits, Ollama install, download with a progress bar, and
  a speed test. Settings lets you switch provider and model, manage keys, and install
  LibreOffice for old Word and PowerPoint files. It runs only on this computer; nothing
  is installed, downloaded or paid for without a click.
- **A workspace on the setup page: add, convert, check and edit your files.**
  - **Your files:** drop or choose PDF, Word and PowerPoint files. Adding one copies it into
    a library on this computer (`%LOCALAPPDATA%\BetterMarkItDown`); results go to
    `Documents\BetterMarkItDown\<name>\`.
  - **A free look first:** how many pages are scanned, which set their equations as
    pictures, how many figures, and the chapters, then an estimate: the cost at the model's
    list price for an online service, or the time from the speed test for a local model.
    Pick pages or a chapter, set a spending cap, or "Try 3 pages first" to measure the cost.
  - **Progress while it converts:** pages done, the page being read, the time left measured
    from this run's own pages, and the money spent so far. Stop at any time; finished pages
    are kept, and converting again continues where it stopped.
  - **Review side by side:** each page's picture next to its Markdown, which you can edit,
    with a preview that draws the maths (KaTeX) and the pictures. Saving puts the edit back
    in the result and checks the page again against the PDF's own text. Pages the free
    check flags are listed to go through first. "Transcribe this page again" asks the model
    anew.
  - **Take it away:** download the `.md`, or a `.zip` with its pictures, or open the folder.
  - Without an AI service, files convert as text only, for free, and pages with little or
    no text layer are listed.
  - **"Read every page with the AI (best for maths)"**: a PDF's text layer often garbles
    formulas, so this sends every page to the model, not only scanned pages and figures. The
    estimate then counts one request per page, and the file remembers the choice.
    Measured on the rest of a 1,340-page econometrics textbook with Gemini 3.6 Flash:
    352 pages for $1.21 in about 10 minutes, three pages at a time; the page's estimate was
    within 5% of the cost.
- **"Play while you wait":** during a conversion expected to take more than 2 minutes, a
  small game is offered (never started by itself): a llama hops over stacks of paper,
  ducks under flying staplers and collects loose pages. It plays in a corner of the page,
  full screen, or popped out above other windows in Chrome and Edge, with the progress bar
  on top, and says when your file is ready. Settings can turn the offer off.
- **Agent mode: AI agents can use BetterMarkItDown on their own.**
  - **`--json`** on a conversion, `--verify`, `--toc`, `--list-models` and `providers`:
    one JSON object per line (progress events, then a summary, or an error), and nothing
    else on standard output. Exit codes: 0 done, 1 error, 2 stopped early (spending cap or
    daily quota), 3 `--verify` flagged pages, 130 interrupted.
  - **`bettermarkitdown inspect FILE`**: the free look the setup page gives, with an
    estimate of requests, cost and time, before anything is spent.
  - **`bettermarkitdown setup`**: choose the AI service and model, and save a key read from
    standard input (never from the command line), without the setup page. With no options
    it says whether a conversion is ready and what is missing.
  - **`--every-page`** reads every page whole with the AI (best for maths), as on the
    setup page; **`--library`** converts the file in the setup page's library, so the person
    can review and edit an agent's result there.
  - **A skill** in the open Agent Skills format (`SKILL.md`), written for any agent: look
    first, ask before spending, convert, check against the PDF, fix pages, report.
    `bettermarkitdown agent install` copies it to where Claude Code, Codex, Gemini CLI and
    Antigravity look for skills (one copy serves Codex and Gemini CLI), after a yes;
    `agent status` and `agent uninstall` too. It never replaces a skill it did not write.
    The setup page offers the same, one button per agent found.
  - **An MCP server**, `bettermarkitdown mcp` (stdio, no extra install): the same steps as
    tools, with conversions running in the background (`convert`, `job_status`, `stop`),
    and documents either on disk or in the setup page's library. `bettermarkitdown agent
    mcp` prints how to register it with each agent.
- **Choose your AI service with `--provider`:** Google Gemini, OpenAI, Anthropic (Claude),
  Moonshot Kimi, OpenRouter, Ollama on your own computer, or any other OpenAI-compatible
  server. `bettermarkitdown providers` lists them with their default models and whether a
  key is set.
- **Every provider and listed model says what to expect**: a rough, plain-language note on
  what it is good at and where it falls short, shown by `providers`, `--list-models` and the
  wizard. Models not yet tried with this tool say so.
- **Keys in your computer's password store:** `bettermarkitdown key set|test|forget|status`.
  `key test` checks a key for free by listing the models it can use. Environment variables
  and `.env` still work and take precedence.
- `bettermarkitdown key forget all` removes every saved key.
- **Claude through Anthropic's own SDK** (`pip install "bettermarkitdown[anthropic]"`). The
  lowest thinking effort is used for transcription, and the cost meter knows Claude's prices.
- The cost meter knows OpenAI's GPT-5.4 mini and nano prices as well as Gemini's.
- **Your choices become the defaults** for every run: a flag, then an environment
  variable, then the setup page's choice, then the built-in default.
- **`bettermarkitdown system` reads your computer and suggests a local model.** It shows
  memory, processor, graphics (with their real memory, which Windows' usual report gets
  wrong) and free disk space. It suggests Qwen3-VL 2B, 4B or 8B with the reason, warns when
  pages would run on the processor and be slow, and lists every option with what it is good
  at and its limits, so you choose. `--json` for scripts.
- **`bettermarkitdown local setup` runs a model on your computer in one command.** It suggests
  a model, installs Ollama (Windows, through winget), downloads the model with a progress
  readout, and times a test page, with a plain verdict ("Usable. About 40 s per page...; a
  100-page book would take about 67 minutes"). It asks before installing or downloading
  anything. `local install`, `pull`, `test` and `status` do the steps one at a time.
- With `--provider ollama`, one page at a time and no rate limit are the defaults.
- Local models' limits now say what was measured on graph pages: Qwen3-VL 4B gave a
  textbook chart one line, 8B described it nearly as well as Gemini, and both skipped a
  slide's hand-drawn graphs.
- The speed test's result is remembered, for the workspace's time estimates.
- **Word and PowerPoint files: DOCX, PPTX, and Office 97-2003 DOC and PPT.** MarkItDown reads
  the text, headings and tables, but left every picture as an empty placeholder. Each
  picture is now saved next to the output and described by the vision model where it
  stood, like PDF figures. DOC and PPT are first saved as DOCX / PPTX by Microsoft Word or
  PowerPoint if installed, else LibreOffice, which keeps their tables intact.
  `--as-pages` sends any of them through PDF instead, page by page.
- **Study notes for pages the model refuses to transcribe.** Gemini declines some pages of
  published books (its recitation filter), which used to go straight to local OCR, word for
  word and with unreliable maths. The tool now asks for study notes on the page instead, in
  the model's own words: checked against the page and revised once, with every equation,
  example, table and figure number the page holds, and with any line that repeats the
  page's wording removed. Each such page is labelled and names the PDF page to read for the
  full text, and lists whatever a final check still questions; the run summary and
  `--verify` list such pages. Up to four requests a page; `--no-study-notes` turns it off.
  Local OCR remains the last resort. Measured on six textbook pages: no copied wording,
  every numbered item and printed figure kept, and still about one real slip every few
  pages after revision, which the listed doubts point to.
- **`bettermarkitdown doctor`** prints one report for a bug report: version, provider, where
  each key comes from (never the key), optional parts installed, and the system summary.
- **For collaborators:** `CONTRIBUTING.md` (the rules every change keeps, how to report a
  problem without sharing copyrighted text, how to measure a change), a "Conversion
  problem" issue form, a pull-request checklist, and `scripts/notes_eval.py`, which
  measures study notes against reviewed pages and prints numbers only.
- **A code signing policy and a privacy statement** (`CODE_SIGNING_POLICY.md`, `PRIVACY.md`),
  linked from the README and every release page, for free code signing by SignPath
  Foundation (applied for). The installer shows what the program sends where before it
  installs, and carries its product name and version in its file details. The release
  workflow signs the installer through SignPath once the project is approved, then tests
  and publishes the signed one.

### Fixed (setup page)

- **A refused request could reach the page as a network error.** When the server refused a
  request before reading what it sent, Windows reset the connection, now and then, instead
  of delivering the refusal. The server now reads the rest of the request first. This was
  the rare failure in the test suite.
- **`--verify` flagged every page converted with page pictures.** It read the converter's
  own picture links ("Page 85 scan") and figure labels ("transcribed by ...") as words of
  the page, which are not in the PDF. They are left out now.
- **Stopping one run could stop, or restart, another.** The stop signal was shared by every
  conversion in the process; each run now has its own.
- "Choose a OpenAI model" now reads "Choose a model: OpenAI", and Settings says how to set
  up another OpenAI-compatible server (from the command line, with `--base-url`).

### Fixed (local models)

- **Ollama cut dense pages short without saying so.** Its default context is 4,096 tokens,
  and a page image plus a long transcription overflows it. Conversions now use a copy of the
  model with a 12,288-token context, created automatically (settings only, no new download).
- **Ollama is reached at 127.0.0.1 instead of localhost**, which on Windows tries IPv6 first
  and lost seconds on every request.

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

[1.5.0]: https://github.com/miguel-arias-sv/BetterMarkItDown/releases/tag/v1.5.0
[1.1.0]: https://github.com/miguel-arias-sv/BetterMarkItDown/releases/tag/v1.1.0
[1.0.0]: https://github.com/miguel-arias-sv/BetterMarkItDown/releases/tag/v1.0.0
