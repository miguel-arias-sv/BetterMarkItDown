"""Local OCR fallback.

Why this exists: Gemini refuses some pages of published books with
`finish_reason: content_filter: RECITATION` - its copyright guardrail against
reproducing text it recognises from training data. That guardrail governs what
the *model* will emit. It is not a reason to reshape the request until it slips
through, and this project does not do that.

Instead, those pages go to a plain OCR engine running locally on your own file.
Nothing leaves the machine, no provider policy is involved, and OCR is the right
tool for reading a scan anyway. The trade-off is real and the output says so:
layout is flattened and mathematical notation is unreliable.
"""

from __future__ import annotations

import threading

_ENGINE = [None]
_LOCK = threading.Lock()

# Vertical tolerance (device pixels) for deciding that two boxes sit on the same
# line, and the fraction of a line's height that counts as a paragraph break.
_LINE_TOLERANCE = 20
_PARAGRAPH_GAP = 0.8


def available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


def ocr_page(page, dpi: int) -> str | None:
    """Transcribe one PyMuPDF page locally. Returns None if OCR is unavailable."""
    try:
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return None

    import pymupdf

    # RapidOCR's session is not documented as thread-safe, and the pixmap render
    # is cheap, so serialise the whole thing rather than risk interleaved state.
    with _LOCK:
        if _ENGINE[0] is None:
            _ENGINE[0] = RapidOCR()
        engine = _ENGINE[0]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72), alpha=False)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        result, _elapsed = engine(img)

    if not result:
        return None

    boxes = []
    for box, text, _score in result:
        text = (text or "").strip()
        if not text:
            continue
        ys = [point[1] for point in box]
        xs = [point[0] for point in box]
        boxes.append({"top": min(ys), "left": min(xs),
                      "height": max(ys) - min(ys), "text": text})
    if not boxes:
        return None

    # Reading order: down the page, then left to right within a line.
    boxes.sort(key=lambda b: (round(b["top"] / _LINE_TOLERANCE), b["left"]))

    out: list[str] = []
    previous = None
    for box in boxes:
        if previous is not None:
            gap = box["top"] - (previous["top"] + previous["height"])
            if gap > previous["height"] * _PARAGRAPH_GAP:
                out.append("\n\n")               # blank space = new paragraph
            elif out and out[-1].endswith("-"):
                out[-1] = out[-1][:-1]           # word split across two lines
            else:
                out.append(" ")
        out.append(box["text"])
        previous = box

    return "".join(out).strip() or None
