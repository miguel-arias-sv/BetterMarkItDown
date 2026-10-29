"""The prompts that do the actual work.

FIGURE_PROMPT and PAGE_PROMPT are written for transcription, not interpretation: the
model is told to reproduce what is on the page and to mark what it cannot read, rather
than to summarise. That distinction is what makes the output usable as study material.
The NOTES prompts are the exception, for pages a model refuses to transcribe: there the
model writes study notes in its own words instead (see notes.py).
"""

FIGURE_PROMPT = """You are transcribing a figure taken from a book page into Markdown.

Rules:
- If it is a chart/graph/plot: state the chart type, axes (with units and ranges),
  every series, and the trend. Then reproduce the underlying values as a Markdown
  table, reading them off the axes. Mark estimated values with ~.
- If it is a table or a screenshot of text: transcribe it fully and literally.
- If it contains handwriting, stylised lettering, a signature, a stamp, or any
  text a normal OCR engine would mangle: transcribe it character by character.
  Put anything you cannot read confidently in [illegible: your best guess].
- If it is a photo/diagram/illustration: describe what it shows and what it is
  meant to demonstrate, including every label and caption.
- Do not invent content that is not visible. Do not comment on image quality.
  Output Markdown only, no preamble.
"""

PAGE_PROMPT = """This is one full page of a scanned book. Transcribe it into clean Markdown.

Rules:
- Transcribe ALL text verbatim, in reading order, preserving the original
  language. Do not summarise, translate, or modernise spelling. Keep typos and
  misspellings exactly as printed; never correct them.
- Use # / ## for headings, - for bullets, > for pull quotes, and Markdown tables
  for tabular data. Tables are plain Markdown pipe tables: no LaTeX table commands
  such as \\multicolumn; leave the cells of a merged cell empty.
- Footnotes: write every superscript note marker in the text as [^n], never as
  $^n$. Write a note's text, as `[^n]: text`, ONLY if that text is printed on this
  page. Many books print notes at the end of the chapter: then write the marker
  alone and no definition at all. Never write a placeholder such as "footnote text
  not present on this page". On a page that lists notes (a "Notes" section), write
  each one as `[^n]: text`, with the number from the page.
- A dollar sign that means money is written \\$ (\\$1,900), so it is not read as
  the start of a formula.
- Render mathematics as LaTeX: $inline$ for expressions in a sentence, $$display$$
  for set-off equations, and \\tag{n} for the equation numbers printed in the margin.
  One \\tag per $$...$$ block: when several lines each carry their own number, write
  each line as its own $$...$$ block. An equation number printed with no equation
  beside it (the equation is on another page) is written as plain text, (6.55),
  never as a \\tag outside $$...$$.
- Handwriting, gothic/blackletter type, marginalia, stamps and ornate initials
  must be transcribed too. Mark unreadable spans as [illegible: best guess].
- For every figure, chart or illustration on the page, insert a block at its
  position in the flow:
  > **[FIGURE]** <description; for charts include axes, series and a Markdown
  > table of the values you can read off>
- Keep the printed page number as a final line like `<!-- page number: 123 -->`.
- Output Markdown only, no preamble, no code fence around the whole answer.
"""

# Study notes, for a page the model refused to transcribe (see notes.py). Notes, not a
# rewrite: the ideas explained afresh, never the page's wording or sentence order.
NOTES_PROMPT = """This textbook page could not be transcribed. Write study notes on it for a
student instead, in your own words.

Rules:
- Explain the ideas the way a tutor would. Do not quote the page, and do not follow its
  wording or its sentence order: these are notes on the page, not a rewrite of it.
- Include the main ideas; each term the page defines and what it means; every formula on
  the page, stated exactly in LaTeX ($...$ inline, $$...$$ display), with the page's own
  equation number beside it in parentheses, as (15.4); for each example, what it
  estimates and its key results, with numbers exactly as printed (never rounded); for each
  exercise, what it asks.
- Mention every equation, example, table and figure number on the page, so the reader can
  find them in the book.
- Short Markdown bullet points under a few headings. Output Markdown only, no preamble.
"""

NOTES_CHECK_PROMPT = """Below are study notes about this textbook page. Compare them with the
page. Reply with JSON only, in this form: {"wrong": [...], "missing": [...]}.

- "wrong": each formula, number or statement in the notes that does not match the page;
  say what the page has instead, as a formula or in your own words.
- "missing": each important formula, result, condition or idea on the page that the notes
  leave out.
Do not quote the page's sentences. Use empty lists when there is nothing.

NOTES:
"""

NOTES_REVISE_PROMPT = """Below are study notes about this textbook page and the problems a check
found in them. Rewrite the notes so that every problem is fixed: correct what is wrong and
add what is missing. Same rules as before: your own words, never the page's wording or
sentence order; formulas exactly, in LaTeX, with the page's equation numbers; numbers
exactly as printed; short Markdown bullet points. Output the complete notes only, in
Markdown, no preamble.
"""
