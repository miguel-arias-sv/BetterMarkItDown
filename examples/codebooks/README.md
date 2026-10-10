# Codebooks, data dictionaries and statistical tables

Worked example: the documentation of Statistics Canada's **Canadian Community Health
Survey (CCHS) 2022, Public Use Microdata File**. That's five PDFs: a 114-page data
dictionary with frequencies, 49 pages of derived-variable specifications, 118 pages of
CV look-up tables, and two user guides.

The two guides are prose and went through BetterMarkItDown as usual. The other three did
not, and this folder shows what was done instead and why.

## Why not the vision model

A codebook is almost all numbers in a grid: codes, unweighted and weighted frequencies,
percentages, coefficients of variation. In a born-digital PDF every one of those digits is
already in the text layer, exactly. Sending the page to a vision model means paying to
**re-read digits you already have**, with a small chance of misreading each one. On a page
like this, a misread digit is invisible: `1,336,749` and `1,386,749` both look plausible.

Two more problems are specific to page-by-page transcription:

- **Records cross page breaks.** A variable's header sits at the bottom of one page and its
  answer categories at the top of the next. Per-page output splits them apart.
- **Dense tables hit the output limit.** A full page of numbers is long in tokens. In this
  project the model's transcription of an image-only CV table stopped mid-row, and before
  v1.2.0 that partial page was kept as if it were complete.

## What to do instead: parse the layout

The text layer loses nothing, except the layout. [`layout_rows.py`](layout_rows.py) keeps
it: every span with its coordinates, grouped into visual rows.

```text
$ python layout_rows.py CCHS_2022_DataDictionary_Freqs.pdf 21
 615.3  41-122*:Answer Categories | 284-306*:Code | 342-387*:Frequency | 397-485*:Weighted Frequency | 512-520*:%
 631.2  41-86:Overweight | 301-306:1 | 359-387:27,143 | 440-485:12,027,139 | 505-523:36.3
 642.2  41-91:Underweight | 301-306:2 | 364-387:2,399 | 445-485:1,336,749 | 510-523:4.0
 653.1  41-102:Just about right | 301-306:3 | 359-387:36,255 | 440-485:18,873,345 | 505-523:57.0
 675.0  190-211*:Total | 359-387:67,079 | 440-485:33,099,725 | 501-523:100.0
```

Numbers are right-aligned, so **each column is one right edge** (306, 387, 485, 523
here). A value's column is decided by where it ends, which is exact. Labels start at a
fixed left edge, bold marks field names and totals, and ruled lines separate table rows.
A parser for one document is a page of rules built on that:

| Script | Source | What it handles |
|---|---|---|
| [`cchs_data_dictionary.py`](cchs_data_dictionary.py) | 114 pp. | 255 variables: metadata and code/frequency tables, labels that wrap, variables that continue onto the next page |
| [`cchs_derived_variables.py`](cchs_derived_variables.py) | 49 pp. | 59 derived variables: Value / Condition / Description / Notes tables whose rows are grouped by the ruled lines, soft wraps told apart from real line breaks |
| [`cchs_cv_tables.py`](cchs_cv_tables.py) | 118 pp. | 108 CV tables of 14 columns, plus the design-effect / sample-size input tables |

These scripts are **templates, not a general converter**. The column positions are
specific to Statistics Canada's layout. For another codebook, dump a page with
`layout_rows.py`, read off its edges, and adapt the parser. That takes an hour or so,
and in exchange every number in the output is copied, not read.

## Check it with arithmetic, not by eye

A deterministic parser fails loudly or not at all, and a codebook is full of
redundancy you can test against:

| Check | Catches |
|---|---|
| Category frequencies sum **exactly** to the printed Total, for all 255 variables; weighted frequencies sum within rounding | a dropped, duplicated or misassigned row |
| Every Total is the same (67,079 respondents) | a table merged with its neighbour |
| Variables found = table of contents, in order | a variable lost at a page break |
| Every CV cell fits `CV = K·sqrt((1-p)/X)`, with `K` fitted per table | a value in the wrong column, a misread digit |
| [`check_words.py`](check_words.py): every word and number of the PDF body appears in the Markdown | anything dropped silently |

All five passed on the CCHS documents. Everything reported missing had been dropped or
joined on purpose: repeated column headings, empty field labels, and one code printed
across two lines (`9999.99999999` + `6`, kept as `9999.999999996`).

## Output

One section per variable, so a reader or an LLM given the file as context can jump
straight to it:

```markdown
### WTP_50 — Self-perceived weight - overweight / underweight / just about right

- **Variable name:** `WTP_50` · **Length:** 1.0 · **Position:** 59 · *(PDF p. 21)*
- **Question Text:** Do you consider yourself overweight, underweight or just about right?
- **Universe:** Respondents with DOWTP = 1 and PROXYSEX = (1, 2) and who answered PRS_05 <> 1

| Answer category | Code | Frequency | Weighted frequency | % |
|---|---:|---:|---:|---:|
| Overweight | 1 | 27,143 | 12,027,139 | 36.3 |
| Underweight | 2 | 2,399 | 1,336,749 | 4.0 |
| Just about right | 3 | 36,255 | 18,873,345 | 57.0 |
| Not stated | 9 | 1,282 | 862,492 | 2.6 |
| **Total** |  | **67,079** | **33,099,725** | **100.0** |
```

Each file also starts with a "how to read this file" note: what the columns mean, and the
reserve codes (`6` = valid skip, `9` = not stated). That context lives elsewhere in the
documentation, and a reader of one file would otherwise miss it.

## When to use which

| The document is… | Use |
|---|---|
| Prose, slides, a scanned book, figures | BetterMarkItDown |
| A born-digital codebook, data dictionary, frequency or CV tables | a layout parser like these |
| A born-digital document with prose *and* tables (a user guide) | BetterMarkItDown, then `--verify`, which compares numbers as well as words |
| A table that is only an image inside the PDF | BetterMarkItDown, then check the numbers yourself; a formula or a total helps |

The PDFs are not included. They are public on the Statistics Canada website, under the
[Open Government Licence – Canada](https://www.statcan.gc.ca/en/reference/licence). The
output excerpts above are from them.
