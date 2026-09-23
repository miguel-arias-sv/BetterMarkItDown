"""The two prompts that do the actual work.

Both are written for transcription, not interpretation: the model is told to
reproduce what is on the page and to mark what it cannot read, rather than to
summarise. That distinction is what makes the output usable as study material.
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
  language. Do not summarise, translate, or modernise spelling.
- Use # / ## for headings, - for bullets, > for pull quotes, and Markdown tables
  for tabular data. Preserve footnotes as [^n] with their text at the end.
- Render mathematics as LaTeX: $inline$ for expressions in a sentence, $$display$$
  for set-off equations, and \\tag{n} for the equation numbers printed in the margin.
- Handwriting, gothic/blackletter type, marginalia, stamps and ornate initials
  must be transcribed too. Mark unreadable spans as [illegible: best guess].
- For every figure, chart or illustration on the page, insert a block at its
  position in the flow:
  > **[FIGURE]** <description; for charts include axes, series and a Markdown
  > table of the values you can read off>
- Keep the printed page number as a final line like `<!-- page number: 123 -->`.
- Output Markdown only, no preamble, no code fence around the whole answer.
"""
