// The workspace: add files, convert them, check and edit the result page by page,
// and take it away. Built on app.js (h, api, show, card...) and preview.js.
"use strict";

const KINDS = { ".pdf": "PDF", ".docx": "Word", ".doc": "Word 97-2003", ".pptx": "PowerPoint",
                ".ppt": "PowerPoint 97-2003" };
const ACCEPT = Object.keys(KINDS).join(",");

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const pageList = (pages, limit = 12) =>
  pages.slice(0, limit).join(", ") + (pages.length > limit ? ` and ${pages.length - limit} more` : "");
const fileUrl = (path, params) => `${path}?${new URLSearchParams({ ...params, t: TOKEN })}`;

function size(bytes) {
  return bytes >= 1e6 ? `${(bytes / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1e3))} KB`;
}

function duration(seconds) {
  if (seconds < 90) return plural(Math.max(1, Math.round(seconds)), "second");
  if (seconds < 5400) return plural(Math.round(seconds / 60), "minute");
  return `${(seconds / 3600).toFixed(1)} hours`;
}

// --- the conversion in progress: one at a time, followed wherever the page is --------------

const Run = { job: null, listeners: new Set(), polling: false };

// fn(job) is told about every change; returning false stops it being told. The first
// call comes after the screen is on the page, so a listener can check its own node.
function onRun(fn) {
  Run.listeners.add(fn);
  setTimeout(() => { if (Run.job && fn(Run.job) === false) Run.listeners.delete(fn); }, 0);
}

function watchRun(job) {
  Run.job = job;
  if (!Run.polling) pollRun();
}

async function pollRun() {
  Run.polling = true;
  try {
    while (Run.job && Run.job.status === "running") {
      tellRun();
      await sleep(1000);
      Run.job = await api(`/api/jobs/${Run.job.id}`);
    }
  } catch (_) { /* the server stopped; the next screen says so */ }
  Run.polling = false;
  tellRun();
}

function tellRun() {
  for (const fn of [...Run.listeners]) if (fn(Run.job) === false) Run.listeners.delete(fn);
  tellGame(Run.job);
}

function runLine(job) {
  const info = job.info || {};
  const unit = info.unit || "page";
  const parts = [job.message];
  if (job.total) parts.push(`${job.done} of ${plural(job.total, unit)}`);
  if (info.reading && info.reading.length) parts.push(`reading page ${info.reading.join(", ")}`);
  if (job.status === "running" && job.done < job.total && !info.stopping) {
    if (info.eta !== null && info.eta !== undefined) parts.push(`about ${duration(info.eta)} left`);
    else parts.push(`timing the first ${unit}`);
  }
  if (info.cost) parts.push(`${money(info.cost)} so far`);
  return parts.filter(Boolean).join(" · ") || "Getting ready...";
}

function tellGame(job) {
  if (!job || job.kind !== "convert" || !Game.isOpen()) return;
  if (job.status === "running") {
    Game.progress(job.total ? job.done / job.total : null, runLine(job));
    return;
  }
  const stopped = job.status === "failed" || (job.result.document || {}).last_run?.stopped;
  Game.finish(stopped ? "The conversion stopped. Finished pages are kept." : "Your file is ready",
              () => show("doc", job.info.doc));
}

// The header's Play: the game at any time, with the progress bar only while a file converts.
document.getElementById("nav-play").addEventListener("click", () => {
  Game.open();
  if (Run.job && Run.job.status === "running") tellGame(Run.job);
  else Game.idle();
});

// --- the library ----------------------------------------------------------------------------

function engineNotice(engine) {
  if (!engine.ready) {
    return h("div", { class: "notice" },
      h("p", { class: "warn", text: engine.problem || "No AI service is set up yet." }),
      h("p", { text: "You can still convert text only, for free: pages with a text layer come out " +
                     "fine, and scanned pages are listed for you." }),
      h("button", { type: "button", onclick: () => show("settings") }, "Open Settings"));
  }
  return h("p", { class: "notice", text: engine.local
    ? `Converting with ${engine.model} on this computer: nothing leaves it.`
    : `Converting with ${engine.name} (${engine.model}). Pages that need the AI are sent to it; ` +
      "the rest are read on this computer." });
}

function docStatus(d, running) {
  if (running && running.status === "running" && running.info.doc === d.id) {
    return `Converting: ${running.done} of ${running.total}`;
  }
  if (!d.last_run.when) return d.output_ready ? "Converted" : "Not converted yet";
  let text = "Converted";
  if (d.paged && d.converted.length < d.page_count) {
    text = `${d.converted.length} of ${d.page_count} pages converted`;
  }
  if (d.flagged.length) text += ` · ${plural(d.flagged.length, "page")} to check`;
  return text;
}

function uploadFile(file, onProgress) {
  // XMLHttpRequest, not fetch: only it reports upload progress.
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/library/add");
    xhr.setRequestHeader("X-BMID-Token", TOKEN);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.setRequestHeader("X-BMID-Filename", encodeURIComponent(file.name));
    xhr.upload.onprogress = (ev) => { if (ev.lengthComputable) onProgress(ev.loaded / ev.total); };
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText); } catch (_) { /* not JSON */ }
      if (xhr.status === 200) resolve(data);
      else reject(new Error(data.error || `Adding it failed (${xhr.status}).`));
    };
    xhr.onerror = () => reject(new Error("The file did not arrive. Is BetterMarkItDown still running?"));
    xhr.send(file);
  });
}

screens.library = async () => {
  const data = await api("/api/library");
  if (data.converting) watchRun(data.converting);

  const list = h("ul", { class: "docs" });
  const fill = (docs, running) => {
    list.replaceChildren(...docs.map((d) => {
      const status = h("span", { class: "status", text: docStatus(d, running) });
      if (running && running.info.doc === d.id) {
        onRun((job) => {
          if (!status.isConnected) return false;
          status.textContent = job.status === "running" ? `Converting: ${job.done} of ${job.total}` : "Converted";
        });
      }
      return h("li", { class: "doc" },
        h("div", {},
          h("strong", { text: d.name }),
          h("span", { class: "meta", text: [KINDS[d.kind], d.pages ? plural(d.pages, "page") : "", size(d.size)].filter(Boolean).join(" · ") }),
          status),
        h("button", { type: "button", onclick: () => show("doc", d.id) }, "Open"));
    }));
    empty.hidden = docs.length > 0;
  };
  const empty = h("p", { class: "explain", text: "No files yet." });

  const uploads = h("div", { class: "uploads", role: "status" });
  const input = h("input", { type: "file", id: "files", multiple: true, accept: ACCEPT, hidden: true });
  const addFiles = async (files) => {
    const added = [];
    for (const file of files) {
      const kind = "." + file.name.split(".").pop().toLowerCase();
      const line = h("p", { text: `${file.name}: adding...` });
      uploads.append(line);
      if (!(kind in KINDS)) {
        line.className = "error";
        line.textContent = `${file.name}: this tool reads PDF, Word and PowerPoint files only.`;
        continue;
      }
      const bar = h("progress", { max: 1, value: 0 });
      line.after(bar);
      try {
        const out = await uploadFile(file, (share) => { bar.value = share; });
        added.push(out.document);
        line.textContent = `${file.name}: added.`;
      } catch (err) {
        line.className = "error";
        line.textContent = `${file.name}: ${err.message}`;
      }
      bar.remove();
    }
    input.value = "";
    if (added.length === 1 && files.length === 1) { show("doc", added[0].id); return; }
    const fresh = await api("/api/library");
    fill(fresh.documents, fresh.converting);
  };
  input.addEventListener("change", () => addFiles([...input.files]));

  const choose = h("button", { type: "button", class: "primary", onclick: () => input.click() }, "Choose files");
  const drop = h("div", { class: "drop" },
    h("p", {}, h("strong", { text: "Drop files here" }), " or ", choose),
    h("p", { class: "explain", text: "PDF, Word (.docx, .doc) or PowerPoint (.pptx, .ppt). Adding a " +
      "file copies it into BetterMarkItDown's library on this computer; nothing is sent anywhere." }));
  drop.addEventListener("dragover", (ev) => { ev.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (ev) => {
    ev.preventDefault();
    drop.classList.remove("over");
    addFiles([...ev.dataTransfer.files]);
  });

  fill(data.documents, data.converting);
  return card("Your files", null,
    engineNotice(data.engine), drop, input, uploads,
    h("h2", { text: "Library" }), empty, list,
    h("p", { class: "explain", text: `Results are saved in ${data.output_root}.` }));
};

// --- one file: look, convert, see the result ----------------------------------------------

function inspectionFacts(d) {
  const i = d.inspection || {};
  if (i.pages) {
    const rows = [
      ["Pages", String(i.pages)],
      ["Scanned pages", `${i.scanned.length}: the AI reads these whole`],
      ["Equations set as pictures", `${plural(i.equations.length, "page")}: the AI reads these whole too`],
      ["Figures", `${i.figures}: the AI describes each one`],
      ["Chapters", i.outline.length ? `${i.outline.length} ${i.outline.length === 1 ? "entry" : "entries"} in its outline` : "no outline"],
    ];
    const verdict = i.scanned.length === i.pages ? "Fully scanned: without the AI it comes out empty."
      : i.scanned.length === 0 && i.equations.length === 0 ? "Born-digital: its text is read for free; the AI only describes the figures."
      : "Mixed: each page is read the way it needs.";
    return [h("table", { class: "facts" }, rows.map(([k, v]) => h("tr", {}, h("th", { text: k }), h("td", { text: v })))),
            h("p", { text: verdict })];
  }
  if (i.pictures !== undefined && i.pictures !== null) {
    return [h("p", { text: `${plural(i.pictures, "picture")} inside: the AI describes each one where it ` +
                           "stands. Text, headings and tables are read for free." })];
  }
  if (d.kind === ".doc" || d.kind === ".ppt") {
    return [h("p", { text: "An Office 97-2003 file: it is opened with Microsoft Office or LibreOffice " +
                           "first, then read like a new one." })];
  }
  return [];
}

function describeEstimate(est, engine, textOnly) {
  if (est.already && !est.pages) return "Every chosen page is converted already.";
  if (textOnly) return "Free: the text layer only, no AI. Scanned pages and pictures come out empty, and are listed for you to check.";
  if (est.calls === null) return `The AI describes each picture; the time and cost show once it starts.`;
  if (est.calls === 0) return "Free: every chosen page has a text layer and no figures, so the AI is not needed.";
  const n = `About ${plural(est.calls, "AI request")}`;
  if (engine.local) {
    return est.seconds ? `${n}: roughly ${duration(est.seconds)} on this computer, from its speed test. Free.`
      : `${n}. Free; the time left shows once the first page is done.`;
  }
  if (est.cost !== null) return `${n}: about ${money(est.cost)} at ${engine.model}'s list price. Rough: pages full of detail cost more.`;
  return `${n}. There is no price list for ${engine.model} here: check ${engine.name}'s billing page.`;
}

function lastRunSummary(d) {
  const r = d.last_run;
  if (!r.when) return [];
  const unit = r.unit || "page";
  const out = [];
  const used = r.text_only ? "as text only, without the AI"
    : `with ${r.provider_name}, ${r.model}${r.whole_pages ? ", every page read whole" : ""}`;
  if (r.stopped === "stopped") {
    out.push(h("p", { class: "warn", text: `Stopped on ${r.when}, with ${r.converted} of ${plural(r.selected, unit)} done. Convert again to continue where it stopped.` }));
  } else if (r.stopped === "budget") {
    out.push(h("p", { class: "warn", text: `Stopped at your spending cap, with ${r.converted} of ${plural(r.selected, unit)} done. Convert again to continue.` }));
  } else if (r.stopped === "DailyQuotaExceeded") {
    out.push(h("p", { class: "warn", text: "Stopped: this key reached its daily limit for this model. Try again tomorrow, or choose another model in Settings." }));
  } else if (unit === "picture" && r.text_only) {
    out.push(h("p", { text: `Converted on ${r.when}, as text only: the pictures are saved next to the result, without a description.` }));
  } else {
    out.push(h("p", { text: `${r.trial ? "Tried" : "Converted"} ${r.converted} of ${plural(r.selected, unit)} on ${r.when}, in ${duration(r.seconds)}, ${used}.` +
                            (r.cost ? ` It cost ${money(r.cost)}.`
                              : r.text_only || r.provider === "ollama" ? " Free: nothing was paid for." : "") }));
  }
  if (r.trial && r.converted && r.cost) {
    const left = d.page_count - d.converted.length;
    out.push(h("p", { class: "explain", text: `That is ${money(r.cost / r.converted)} a ${unit}, measured. ` +
      (left > 0 ? `The other ${plural(left, unit)} would cost roughly ${money(r.cost / r.converted * left)}, if they are like these.` : "") }));
  }
  if (r.failed.length) out.push(h("p", { class: "warn", text: `${plural(r.failed.length, unit)} came back empty and are not in the result: ${pageList(r.failed)}. Convert again to retry them.` }));
  if (r.ocr.length) out.push(h("p", { class: "warn", text: `The model refused ${plural(r.ocr.length, "page")}, so they were read by the local OCR fallback: ${pageList(r.ocr)}. Check the maths and layout there.` }));
  if (r.truncated.length) out.push(h("p", { class: "warn", text: `Cut off at the model's output limit: ${pageList(r.truncated)}. Finish those from the page image.` }));
  if ((r.empty || []).length) out.push(h("p", { class: "warn", text: `Without the AI, ${plural(r.empty.length, "page")} with little or no text layer came out empty or nearly: ${pageList(r.empty)}.` }));
  if (d.flagged.length) out.push(h("p", { text: `${plural(d.flagged.length, "page")} to check: the free check against the PDF's own text found differences.` }));
  return out;
}

function runPanel(job, id) {
  const bar = h("progress", { max: 1 });
  bar.removeAttribute("value");
  const line = h("p", { role: "status", class: "explain", text: runLine(job) });
  const stop = h("button", { type: "button" }, "Stop");
  stop.addEventListener("click", async () => {
    stop.disabled = true;
    try { await api("/api/doc/stop", { job: job.id }); } catch (err) { line.textContent = err.message; }
  });
  const play = h("button", { type: "button", hidden: true }, "Play LlamaGame while you wait");
  play.addEventListener("click", () => { Game.open(); tellGame(Run.job); play.hidden = true; });
  const node = h("div", { class: "run" }, h("h2", { text: "Converting" }), bar, line,
    h("p", { class: "explain", text: "You can leave this page, or close it: the conversion goes on, and finished pages are kept even if it stops." }),
    h("div", { class: "actions" }, stop, play));
  onRun((j) => {
    if (!node.isConnected) return false;
    if (j.id !== job.id) return undefined;
    if (j.total) { bar.max = j.total; bar.value = j.done; }
    line.textContent = runLine(j);
    play.hidden = !(S.state.settings.offer_game && j.info.eta > 120 && j.status === "running" && !Game.isOpen());
    if (j.status !== "running") {
      if (j.status === "failed") { line.className = "error"; line.textContent = j.error; stop.hidden = true; play.hidden = true; return false; }
      replace("doc", id);
      return false;
    }
    return undefined;
  });
  return node;
}

function inspectingPanel(job, id) {
  const bar = h("progress", { max: 1 });
  bar.removeAttribute("value");
  const line = h("p", { class: "explain", role: "status", text: "Looking through the file..." });
  follow(job, (j) => {
    if (j.total) { bar.max = j.total; bar.value = j.done; line.textContent = `Looking through the file: page ${j.done} of ${j.total}.`; }
  }).then(() => {
    // A job can end before this panel is on the page: wait until it is, then show
    // the results. Without the wait, a look that ended at once left the page stuck.
    setTimeout(() => { if (bar.isConnected) replace("doc", id); }, 0);
  }).catch((err) => { line.className = "error"; line.textContent = err.message; });
  return h("div", {}, bar, line);
}

// A converted file opens beside its review: the file's details in a narrow column, the
// pages on the right. Before that, and while it converts, the file has the page to itself.
// `page` (optional) is the page to show in the review.
screens.doc = async (id, page) => {
  await refresh();
  const data = await api(`/api/doc?id=${encodeURIComponent(id)}`);
  const d = data.document;
  const engine = data.engine;
  const running = data.converting && data.converting.status === "running" ? data.converting : null;
  if (running) watchRun(running);
  const mine = running && running.info.doc === d.id;
  const beside = d.output_ready && !mine;

  const intro = [KINDS[d.kind], d.pages ? plural(d.pages, "page") : "", size(d.size), `added ${d.added.slice(0, 10)}`]
    .filter(Boolean).join(" · ");
  const body = [];
  const looking = data.inspecting && data.inspecting.status === "running";
  const facts = looking ? [inspectingPanel(data.inspecting, id)] : inspectionFacts(d);
  if (!beside) body.push(...facts);

  if (mine) body.push(runPanel(running, id));
  else body.push(...lastRunSummary(d));

  if (d.output_ready) {
    const status = h("p", { role: "status" });
    body.push(
      h("h2", { text: "Result" }),
      h("p", { class: "path", text: d.output }),
      h("div", { class: "actions" },
        h("a", { class: "button", href: fileUrl("/api/doc/download", { id: d.id }), download: "" }, "Download .md"),
        h("a", { class: "button", href: fileUrl("/api/doc/download", { id: d.id, format: "zip" }), download: "" }, "Download .zip, with pictures"),
        h("button", { type: "button", onclick: async () => {
          try { await api("/api/doc/open-folder", { id: d.id }); status.textContent = ""; } catch (err) { status.className = "error"; status.textContent = err.message; }
        } }, "Open the folder")),
      status);
  }
  if (beside) {
    if (facts.length) body.push(h("details", {}, h("summary", { text: "What is in the file" }), ...facts));
    const unfinished = d.paged && d.page_count && d.converted.length < d.page_count;
    body.push(h("details", { open: Boolean(unfinished) },
      h("summary", { text: unfinished ? "Convert the rest" : "Convert again" }), convertForm(d, engine, data, running, false)));
  } else if (!mine) {
    body.push(convertForm(d, engine, data, running));
  }

  body.push(h("div", { class: "actions end" },
    h("button", { type: "button", class: "link", onclick: back }, "Back to your files"),
    h("button", { type: "button", class: "link danger", onclick: async () => {
      const kept = d.output_ready ? ` The result in ${d.output} stays.` : "";
      if (!confirm(`Remove ${d.name} from the library? Its copy and work files are deleted.${kept}`)) return;
      await api("/api/library/remove", { id: d.id });
      S.history.pop();
      replace("library");
    } }, "Remove from the library")));

  if (!beside) return card(d.name, intro, ...body);
  const side = card(d.name, intro, ...body);
  side.classList.add("doc-side");
  return h("div", { class: "doc-layout", "data-wide": "1" }, side, await reviewPanel(d, engine, page));
};

// The review on its own screen: links and history from before it moved beside the file.
screens.review = (id, page) => screens.doc(id, page);

function convertForm(d, engine, data, running, heading = true) {
  const nodes = heading ? [h("h2", { text: d.output_ready ? "Convert more" : "Convert" })] : [];
  if (running) {
    nodes.push(h("p", { class: "notice" }, `Another file is being converted: ${running.info.name}. One file converts at a time. `,
      h("button", { type: "button", class: "link", onclick: () => show("doc", running.info.doc) }, "Go to it")));
  }
  const allDone = d.paged && d.page_count && d.converted.length >= d.page_count;
  if (allDone) {
    nodes.push(h("p", { class: "explain", text: "Every page is converted. To redo one, open it in the review and press \"Transcribe this page again\"." }));
    return h("div", {}, ...nodes);
  }
  if (!engine.ready) nodes.push(engineNotice(engine));
  else nodes.push(h("p", { text: engine.local ? `With ${engine.model}, on this computer: nothing leaves it.`
    : `With ${engine.name}, ${engine.model}. The pages that need the AI are sent to it; the rest are read here.` }));

  const estimateLine = h("p", { class: "explain", role: "status" });
  let timer = null;
  const update = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const query = new URLSearchParams({ id: d.id, pages: pages ? pages.value.trim() : "", text_only: textOnly.checked ? "1" : "",
                                          whole_pages: whole && whole.checked ? "1" : "" });
      if (whole) wholeRow.hidden = textOnly.checked;
      try {
        const est = await api(`/api/doc/estimate?${query}`);
        estimateLine.className = "explain";
        estimateLine.textContent = describeEstimate(est, engine, textOnly.checked);
        trial.hidden = textOnly.checked || engine.local || !est.calls || est.calls <= 3;
        go.textContent = pages && pages.value.trim() ? "Convert these pages" : goLabel;
        go.disabled = Boolean(running) || (Boolean(est.already) && !est.pages);
      } catch (err) {
        estimateLine.className = "error";
        estimateLine.textContent = err.message;
      }
    }, 250);
  };

  const textOnly = h("input", { type: "checkbox", id: "textonly", checked: !engine.ready, disabled: !engine.ready, onchange: update });
  nodes.push(h("label", { class: "check" }, textOnly, " Text only, without the AI (free)"));

  // PDFs only: a Word or PowerPoint file read directly has no pages to read whole.
  let whole = null;
  let wholeRow = null;
  if (d.kind === ".pdf" || d.as_pages) {
    whole = h("input", { type: "checkbox", id: "wholepages", checked: d.whole_pages, onchange: update });
    wholeRow = h("div", {},
      h("label", { class: "check" }, whole, " Read every page with the AI (best for maths)"),
      h("p", { class: "explain", text: "Otherwise only scanned pages and figures go to the AI, and the rest is read from the PDF's text " +
        "layer, for free. That layer often garbles formulas, so for a maths-heavy book this is worth one request per page." }));
    nodes.push(wholeRow);
  }

  let pages = null;
  if (d.paged && d.page_count) {
    pages = h("input", { type: "text", id: "pages", placeholder: `all ${d.page_count}`, autocomplete: "off", oninput: update });
    nodes.push(h("label", { for: "pages", text: "Pages" }), pages,
      h("p", { class: "explain", text: "For example 1-20, or 3,5,9-12. Pages already converted are kept and skipped." }));
    const outline = (d.inspection.outline || []);
    if (outline.length) {
      const chapter = h("select", { id: "chapter", onchange: () => { pages.value = chapter.value; update(); } },
        h("option", { value: "" }, "Whole file"),
        outline.map((o) => h("option", { value: o.first === o.last ? String(o.first) : `${o.first}-${o.last}` },
          `${"  ".repeat(o.level - 1)}${o.title} (${o.first === o.last ? "p. " + o.first : `pp. ${o.first}-${o.last}`})`)));
      nodes.push(h("label", { for: "chapter", text: "Or pick a chapter" }), chapter);
    }
  }

  let asPages = null;
  if (data.can_as_pages) {
    asPages = h("input", { type: "checkbox", id: "aspages", checked: d.as_pages });
    nodes.push(h("label", { class: "check" }, asPages, " Show page pictures to check against"),
      h("p", { class: "explain", text: "Turns the file into a PDF first, with Microsoft Office or LibreOffice, and reads it page by page. Tables come out flatter." }));
  }

  let budget = null;
  if (engine.ready && !engine.local) {
    budget = h("input", { type: "text", id: "budget", inputmode: "decimal", placeholder: "no cap", autocomplete: "off" });
    nodes.push(h("label", { for: "budget", text: "Spending cap, in US dollars (optional)" }), budget,
      h("p", { class: "explain", text: "The run stops cleanly once it has spent this much; pages done so far are kept." }));
  }

  const status = h("p", { role: "status" });
  const start = async (extra) => {
    go.disabled = true;
    trial.disabled = true;
    status.className = "";
    status.textContent = "Starting...";
    try {
      const job = await api("/api/doc/convert", {
        id: d.id, pages: pages ? pages.value.trim() : "", text_only: textOnly.checked,
        as_pages: asPages ? asPages.checked : false, whole_pages: whole ? whole.checked : false,
        budget_usd: budget ? budget.value.trim() || 0 : 0, ...extra });
      watchRun(job);
      replace("doc", d.id);
    } catch (err) {
      status.className = "error";
      status.textContent = err.message;
      go.disabled = Boolean(running);
      trial.disabled = false;
    }
  };
  const partly = d.paged && d.converted.length > 0;
  const goLabel = partly ? "Convert the rest" : d.output_ready ? "Convert again" : "Convert";
  const go = h("button", { type: "button", class: "primary", disabled: Boolean(running), onclick: () => start({}) }, goLabel);
  const trial = h("button", { type: "button", hidden: true, disabled: Boolean(running), onclick: () => start({ trial: true }) },
    "Try 3 pages first");
  nodes.push(estimateLine, status, h("div", { class: "actions" }, go, trial));
  update();
  return h("div", {}, ...nodes);
}

// --- review and edit, page by page ------------------------------------------------------------

const VIEW_KEY = "bmid-review-view";
function loadView() {
  try { return JSON.parse(localStorage.getItem(VIEW_KEY)) || {}; } catch (_) { return {}; }
}
function saveView(view) {
  try { localStorage.setItem(VIEW_KEY, JSON.stringify(view)); } catch (_) { /* private window */ }
}

// The pages of a converted file, beside the original: opens on the first page to check.
async function reviewPanel(d, engine, pageArg) {
  const id = d.id;
  const paged = d.paged;
  const total = paged ? d.page_count : 0;
  const hasImage = d.kind === ".pdf" || d.as_pages;
  let page = paged ? Math.min(Math.max(1, Number(pageArg) || d.flagged[0] || d.converted[0] || 1), total) : 0;
  let saved = "";
  let current = {};
  const view = { mode: "both", image: true, ...loadView() };

  const image = h("img", { class: "page-image", alt: "" });
  const imagePane = h("div", { class: "pane image-pane" }, image);
  const editor = h("textarea", { class: "editor", spellcheck: "false", "aria-label": "The Markdown, which you can edit" });
  const preview = h("div", { class: "pane preview markdown", "aria-label": "Preview" });
  const notes = h("div", { class: "page-notes" });
  const state = h("span", { class: "save-state", role: "status" });
  const dirty = () => !editor.disabled && editor.value !== saved;

  const assetUrl = (src) => fileUrl("/api/doc/asset", { id: d.id, path: src });
  let previewTimer = null;
  const renderPreview = () => {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(() => {
      if (view.mode === "edit") return;
      try { preview.replaceChildren(renderMarkdown(editor.value, assetUrl)); }
      catch (err) { preview.replaceChildren(h("p", { class: "error", text: `The preview failed: ${err.message}` })); }
    }, 200);
  };
  const setState = (text, kind) => { state.textContent = text; state.className = "save-state" + (kind ? " " + kind : ""); };

  const save = h("button", { type: "button", class: "primary" }, "Save");
  const again = h("button", { type: "button" }, "Transcribe this page again");
  const prev = h("button", { type: "button", "aria-label": "Previous page" }, "‹ Previous");
  const next = h("button", { type: "button", "aria-label": "Next page" }, "Next ›");
  const pageInput = h("input", { type: "number", class: "page-no", min: 1, max: total, "aria-label": "Page number" });
  const toCheck = h("select", { class: "to-check", "aria-label": "Pages to check" });

  const fillToCheck = () => {
    const flagged = Object.keys(d.checks).map(Number).sort((a, b) => a - b);
    toCheck.replaceChildren(h("option", { value: "" }, flagged.length ? `Pages to check (${flagged.length})` : "No pages to check"),
      flagged.map((n) => h("option", { value: String(n) }, `Page ${n}`)));
    toCheck.disabled = !flagged.length;
  };

  const fillNotes = () => {
    const items = [];
    if (!current.converted) items.push(h("li", { text: "This page is not converted yet." }));
    if (current.scanned) items.push(h("li", { class: "info", text: "Little or no text layer here, so the free check has nothing to compare: look at it beside the page image." }));
    for (const note of current.notes || []) items.push(h("li", { class: "flag", text: note }));
    notes.replaceChildren(items.length ? h("ul", {}, items) : h("p", { class: "ok", text: paged ? "Nothing to check on this page: its words and numbers match the PDF's text." : "" }));
    notes.hidden = !items.length && !paged;
  };

  const confirmLeave = () => !dirty() || confirm("This page has changes you have not saved. Leave without saving them?");

  async function load(n, force) {
    if (!force && !confirmLeave()) { pageInput.value = page; return; }
    page = n;
    pageInput.value = n;
    S.history[S.history.length - 1] = ["doc", [id, String(n)]];
    setState("Loading...");
    current = await api(`/api/doc/page?id=${encodeURIComponent(id)}&page=${n}`);
    if (hasImage && paged) { image.src = fileUrl("/api/doc/image", { id: d.id, page: n }); image.alt = `Page ${n} of the original`; }
    editor.value = current.markdown;
    saved = current.markdown;
    editor.disabled = !current.converted;
    again.textContent = current.converted ? "Transcribe this page again" : "Convert this page";
    again.hidden = !paged || (!engine.ready && current.converted);
    prev.disabled = n <= 1;
    next.disabled = n >= total;
    setState(current.converted ? (current.edited ? "Edited by hand" : "") : "Not converted yet");
    fillNotes();
    renderPreview();
  }

  async function savePage() {
    if (editor.disabled) return;
    save.disabled = true;
    setState("Saving...");
    try {
      const out = await api("/api/doc/page", { id: d.id, page, markdown: editor.value });
      saved = editor.value;
      current.notes = out.notes;
      current.edited = true;
      if (out.notes.length) d.checks[String(page)] = out.notes; else delete d.checks[String(page)];
      fillToCheck();
      fillNotes();
      setState(out.notes.length ? "Saved. The check still finds something: see above." : "Saved", out.notes.length ? "warn" : "ok");
    } catch (err) {
      setState(err.message, "error");
    } finally {
      save.disabled = false;
    }
  }

  again.addEventListener("click", async () => {
    if (dirty()) { setState("Save or undo your changes first.", "error"); return; }
    if (current.edited && !confirm("This page has your edits. Transcribing it again replaces them" +
        (engine.local ? "" : ", and pays for this page again") + ". Go ahead?")) return;
    again.disabled = true;
    try {
      const job = await api("/api/doc/convert", { id: d.id, pages: String(page), again: current.converted,
                                                  text_only: !engine.ready, whole_pages: d.whole_pages });
      watchRun(job);
      const forPage = page;
      onRun((j) => {
        if (!again.isConnected) return false;
        if (j.id !== job.id) return undefined;
        setState(runLine(j));
        if (j.status === "running") return undefined;
        again.disabled = false;
        if (j.status === "failed") setState(j.error, "error");
        else if (page === forPage) load(forPage, true);
        return false;
      });
    } catch (err) {
      setState(err.message, "error");
      again.disabled = false;
    }
  });

  editor.addEventListener("input", () => { setState(dirty() ? "Unsaved changes" : ""); renderPreview(); });
  editor.addEventListener("keydown", (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "s") { ev.preventDefault(); savePage(); }
  });
  save.addEventListener("click", savePage);
  prev.addEventListener("click", () => load(page - 1));
  next.addEventListener("click", () => load(page + 1));
  pageInput.addEventListener("change", () => {
    const n = Math.round(Number(pageInput.value));
    if (n >= 1 && n <= total && n !== page) load(n); else pageInput.value = page;
  });
  toCheck.addEventListener("change", () => { if (toCheck.value) load(Number(toCheck.value)); toCheck.value = ""; });

  // The layout: Edit, Preview or Both, with or without the page picture beside them.
  const body = h("div", { class: "review-body" });
  const right = h("div", { class: "pane-group" }, editor, preview);
  const tabs = ["edit", "preview", "both"].map((mode) =>
    h("button", { type: "button", class: "tab", "data-mode": mode, onclick: () => { view.mode = mode; layout(); } },
      { edit: "Edit", preview: "Preview", both: "Side by side" }[mode]));
  const showImage = h("input", { type: "checkbox", id: "showimage", checked: view.image, onchange: () => { view.image = showImage.checked; layout(); } });
  const layout = () => {
    saveView(view);
    for (const tab of tabs) tab.setAttribute("aria-pressed", String(tab.dataset.mode === view.mode));
    editor.hidden = view.mode === "preview";
    preview.hidden = view.mode === "edit";
    const withImage = hasImage && paged && view.image;
    imagePane.hidden = !withImage;
    body.className = `review-body mode-${view.mode}${withImage ? " with-image" : ""}`;
    renderPreview();
  };
  body.append(imagePane, right);

  S.unsaved = dirty;
  fillToCheck();
  layout();
  await load(page, true);

  const nav = paged ? h("div", { class: "page-nav" }, prev,
    h("label", { class: "inline" }, "Page ", pageInput, ` of ${total}`), next, toCheck) : null;
  return h("section", { class: "card review" },
    h("div", { class: "review-head" },
      h("h2", { text: d.flagged.length ? `Review: ${plural(d.flagged.length, "page")} to check` : "Review" }),
      h("p", { class: "intro", text: paged ? "Each page beside the original. Edits are saved into the result." : "The whole file. Edits are saved into the result." })),
    nav,
    h("div", { class: "review-tools" },
      h("div", { class: "tabs", role: "group", "aria-label": "View" }, tabs),
      hasImage && paged ? h("label", { class: "check inline" }, showImage, " Show the page") : null,
      h("span", { class: "spacer" }), state, again, save),
    notes, body);
}
