// The Markdown preview: marked reads the Markdown, KaTeX draws the maths, DOMPurify
// keeps it safe. Model output is untrusted HTML on a page that can spend money and
// install programs, so it is sanitized before it reaches the page, with every style
// attribute removed; the maths is put back afterwards as KaTeX's own output, which
// KaTeX builds from text and never from HTML.
"use strict";

// $$...$$, \[...\], $...$ and \(...\). An inline $ must hug its content, as in
// Pandoc, so "$5 and $10" stays money.
const MATH_RE = /\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|(?<![\\$\w])\$(?![\s$])((?:\\.|[^$\\\n])+?)(?<![\s\\])\$(?![\w$])|\\\(([\s\S]+?)\\\)/g;
const CODE_RE = /```[\s\S]*?(?:```|$)|`[^`\n]+`/g;
const HOLE = "BMIDMATH";

function renderMarkdown(md, assetUrl) {
  const code = [];
  const math = [];
  // Code first, so a $ inside it is left alone; then the maths, so marked never sees
  // its underscores and backslashes.
  let text = md.replace(CODE_RE, (m) => { code.push(m); return `\u0001${code.length - 1}\u0001`; });
  text = text.replace(MATH_RE, (_m, display, bracket, inline, paren) => {
    math.push({ tex: display ?? bracket ?? inline ?? paren, display: display !== undefined || bracket !== undefined });
    return `${HOLE}${math.length - 1}X`;
  });
  text = text.replace(/\u0001(\d+)\u0001/g, (_m, i) => code[Number(i)]);

  const html = marked.parse(text, { gfm: true, breaks: false, async: false });
  const frag = DOMPurify.sanitize(html, {
    RETURN_DOM_FRAGMENT: true,
    FORBID_TAGS: ["style", "form", "input", "button", "textarea", "select", "iframe"],
    FORBID_ATTR: ["style"],
  });

  for (const img of frag.querySelectorAll("img")) {
    const src = img.getAttribute("src") || "";
    if (src && !/^[a-z][a-z0-9+.-]*:|^\/|^#/i.test(src)) {
      img.src = assetUrl(src);                 // a picture saved next to the .md
      img.loading = "lazy";
    } else if (!src.startsWith("data:image/")) {
      img.replaceWith(document.createTextNode(img.alt ? `[picture: ${img.alt}]` : "[picture]"));
    }
  }
  for (const a of frag.querySelectorAll("a[href]")) {
    if (/^https?:/i.test(a.getAttribute("href"))) {
      a.target = "_blank";
      a.rel = "noopener noreferrer";
    } else if (!a.getAttribute("href").startsWith("#")) {
      a.removeAttribute("href");
    }
  }
  if (math.length) putMathBack(frag, math);
  return frag;
}

function putMathBack(root, math) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const holes = [];
  while (walker.nextNode()) if (walker.currentNode.nodeValue.includes(HOLE)) holes.push(walker.currentNode);
  const pattern = new RegExp(`${HOLE}(\\d+)X`, "g");
  for (const node of holes) {
    const parts = node.nodeValue.split(pattern);    // text, index, text, index, ...
    const out = document.createDocumentFragment();
    parts.forEach((part, i) => {
      if (i % 2 === 0) { if (part) out.append(part); return; }
      const item = math[Number(part)];
      const span = document.createElement("span");
      try {
        katex.render(item.tex, span, { displayMode: item.display, throwOnError: false,
                                       trust: false, strict: "ignore", maxExpand: 1000 });
      } catch (_) {
        span.textContent = item.display ? `$$${item.tex}$$` : `$${item.tex}$`;
        span.className = "math-error";
      }
      out.append(span);
    });
    node.replaceWith(out);
  }
}
