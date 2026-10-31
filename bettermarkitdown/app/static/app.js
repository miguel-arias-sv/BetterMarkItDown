// The setup page. Plain JavaScript; the only libraries are the preview's, in vendor/.
// Every screen is a function that returns DOM; show() renders one and remembers it for
// the Back button. The workspace's screens are in workspace.js.
"use strict";

const TOKEN = document.querySelector('meta[name="bmid-token"]').content;
const root = document.getElementById("app");
// unsaved: set by a screen with work not saved yet; asked before leaving it.
const S = { state: null, system: null, localModel: null, history: [], unsaved: null };

// --- helpers ---------------------------------------------------------------------

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function api(path, body) {
  const res = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "X-BMID-Token": TOKEN, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = {};
  try { data = await res.json(); } catch (_) { /* not JSON */ }
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

// Follow a background job (install, download, speed test) until it ends.
async function follow(job, onUpdate) {
  while (job.status === "running") {
    onUpdate(job);
    await sleep(700);
    job = await api(`/api/jobs/${job.id}`);
  }
  onUpdate(job);
  if (job.status === "failed") throw new Error(job.error);
  return job.result;
}

const automatic = () => S.state.settings.help_level === "automatic";
const provider = (id) => S.state.providers.find((p) => p.id === id);
const keyProviders = () => S.state.providers.filter((p) => p.needs_key && p.key_url);
const gb = (bytes) => (bytes / 1e9).toFixed(2);
// A key set in an environment variable wins over the password vault.
const fromEnvironment = (p) => Boolean(p.key_source) && p.key_source !== "password store";
const money = (usd) => (usd < 0.01 ? `$${usd.toFixed(4)}` : `$${usd.toFixed(2)}`);

// --- colours: the system's, or light or dark, from the header's button ----------------------

const THEMES = ["auto", "light", "dark"];
const THEME_LABELS = { auto: "◐ Auto", light: "☀ Light", dark: "☾ Dark" };
const THEME_HELP = { auto: "Colours follow your system", light: "Light colours", dark: "Dark colours" };

function applyTheme(theme) {
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
  const button = document.getElementById("nav-theme");
  const next = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
  button.textContent = THEME_LABELS[theme] || THEME_LABELS.auto;
  button.title = `${THEME_HELP[theme] || THEME_HELP.auto}. Click for: ${THEME_HELP[next].toLowerCase()}.`;
  button.setAttribute("aria-label", button.title);
}

async function refresh() {
  S.state = await api("/api/state");
  applyTheme(S.state.settings.theme);
  document.getElementById("nav-settings").hidden = !S.state.settings.setup_done;
  document.getElementById("nav-library").hidden = !S.state.settings.setup_done;
}

async function save(changes) {
  const out = await api("/api/settings", changes);
  S.state.settings = out.settings;
}

// --- screen plumbing -----------------------------------------------------------------

const screens = {};

// What a slow screen is waiting for, shown under the llama once the loading screen is up.
let loadingText = "";
function loadingNote(text) {
  loadingText = text;
  const note = document.getElementById("loading-note");
  if (note) note.textContent = text;
}

async function render(name, args) {
  root.classList.toggle("wide", Boolean(screens[name].wide));
  const waiting = h("p", { class: "loading", text: "Loading..." });
  root.replaceChildren(waiting);
  loadingText = "";
  // Most screens are ready at once. One that takes longer (a file opening beside its
  // review) gets the llama running while it loads, so a short wait has something to see.
  const slow = setTimeout(() => {
    if (!waiting.isConnected) return;
    const text = name === "doc" || name === "review" ? "Opening your file" : "Loading";
    waiting.replaceWith(h("div", { class: "loading" },
      h("p", { id: "loading-note", class: "loading-note", text: loadingText }), Game.runner(text)));
  }, 300);
  try {
    const node = await screens[name](...args);
    clearTimeout(slow);
    // A screen can also ask for the full width itself, for one layout and not another.
    root.classList.toggle("wide", Boolean(screens[name].wide) || node.dataset.wide === "1");
    root.replaceChildren(node);
    const heading = root.querySelector("h1");
    if (heading) { heading.tabIndex = -1; heading.focus(); }
  } catch (err) {
    clearTimeout(slow);
    root.replaceChildren(card("Something went wrong", null,
      h("p", { class: "error", text: err.message }),
      h("div", { class: "actions" },
        h("button", { type: "button", onclick: () => render(name, args) }, "Try again"),
        backButton())));
  }
}

function mayLeave() {
  if (S.unsaved && S.unsaved() && !confirm("This page has changes you have not saved. Leave without saving them?")) return false;
  S.unsaved = null;
  return true;
}
function show(name, ...args) {
  if (!mayLeave()) return undefined;
  S.history.push([name, args]);
  return render(name, args);
}
function replace(name, ...args) { S.history[S.history.length - 1] = [name, args]; return render(name, args); }
function back() {
  if (!mayLeave()) return undefined;
  if (S.history.length > 1) S.history.pop();
  const [name, args] = S.history[S.history.length - 1];
  return render(name, args);
}
function backButton() {
  return S.history.length > 1 ? h("button", { type: "button", class: "link", onclick: back }, "Back") : null;
}

function card(title, intro, ...body) {
  return h("section", { class: "card" },
    h("h1", { text: title }),
    intro ? h("p", { class: "intro", text: intro }) : null,
    ...body);
}

// Shown in "assisted" mode only: "automatic" keeps screens short.
function explain(text) { return automatic() ? null : h("p", { class: "explain", text }); }

function choices(list) {
  return h("div", { class: "choices" }, list.map((c) =>
    h("button", { type: "button", class: "choice" + (c.recommended ? " recommended" : ""), onclick: c.onclick },
      h("strong", { text: c.label }),
      c.detail ? h("span", { text: c.detail }) : null,
      c.recommended ? h("em", { text: "Recommended" }) : null)));
}

function actions(...buttons) { return h("div", { class: "actions" }, ...buttons, backButton()); }

function providerSelect(selected, onchange) {
  const select = h("select", { id: "provider", onchange: () => onchange(select.value) },
    keyProviders().map((p) => h("option", { value: p.id, selected: p.id === selected }, p.name)));
  return select;
}

// --- the questions ------------------------------------------------------------------

screens.welcome = () => card("Welcome to BetterMarkItDown",
  "Turns PDFs, Word and PowerPoint files into Markdown, including what is in their pictures.",
  h("div", { class: "notice" },
    h("p", {}, h("strong", { text: "Why did a browser open? " }),
      "This page is how BetterMarkItDown shows its controls. It runs only on this computer: it is " +
      "not a website, and nothing on it is sent anywhere."),
    h("p", {}, h("strong", { text: "Internet: " }),
      "needed during setup, and whenever you use an online AI service. With a model on this " +
      "computer, it works offline once setup is done.")),
  h("div", { class: "actions" },
    h("button", { type: "button", class: "primary", onclick: () => show("audience") },
      S.state.settings.setup_done ? "Run setup again" : "Start setup"),
    S.state.settings.setup_done
      ? h("button", { type: "button", onclick: () => show("settings") }, "Go to settings") : null));

screens.audience = () => card("Who will use BetterMarkItDown?", null,
  explain("This decides what the last step sets up. You can change it later."),
  choices([
    { label: "Me, in this browser", detail: "Add files, convert them, check and edit the result.",
      onclick: async () => { await save({ audience: "human" }); show("help"); } },
    { label: "An AI agent", detail: "Claude Code, Codex, Gemini CLI or another agent will run it for you.",
      onclick: async () => { await save({ audience: "agent", help_level: "assisted" }); show("haskey"); } },
    { label: "Both", detail: "You in the browser, and an agent from the command line.",
      onclick: async () => { await save({ audience: "both" }); show("help"); } },
  ]),
  actions());

screens.help = () => card("How much help would you like?", null,
  choices([
    { label: "Assisted", detail: "Explain each choice and let me decide.",
      onclick: async () => { await save({ help_level: "assisted" }); show("haskey"); } },
    { label: "Automatic", detail: "Pick the recommended option at each step. Only ask before installing, downloading or spending.",
      onclick: async () => { await save({ help_level: "automatic" }); show("haskey"); } },
  ]),
  actions());

screens.haskey = () => card("Do you have an API key from an AI company?", null,
  h("p", { class: "notice", text:
    "A ChatGPT Plus, Claude Pro or Gemini subscription is not an API key: each company bills " +
    "its API separately, on its developer website." }),
  choices([
    { label: "Yes", detail: "I have a key, or an account on a developer website.", onclick: () => show("knows") },
    { label: "No", detail: "Show me the free ways to start.", onclick: () => show("nokey") },
  ]),
  actions());

screens.knows = () => card("Are you familiar with API keys?", null,
  choices([
    { label: "Yes", detail: "I have my key ready to paste.", onclick: () => show("keyform") },
    { label: "No", detail: "Show me where to get it, step by step.", onclick: () => show("keyguide") },
  ]),
  actions());

screens.nokey = () => card("No problem. There are two free ways to start", null,
  explain("You can add a paid service later from Settings."),
  choices([
    { label: "Get a free Gemini key", recommended: true,
      detail: "Fast, and good with graphs and maths. The free tier has daily limits, and Google may use " +
              "free-tier documents to improve its products.",
      onclick: () => show("keyguide", "gemini") },
    { label: "Use a model on this computer",
      detail: "Private and offline, but slower, and weaker on graphs. The next step finds a model that " +
              "fits this computer.",
      onclick: () => show("localcheck") },
  ]),
  actions());

screens.keyguide = (pid) => {
  const p = provider(pid || "gemini");
  return card(`Get an API key: ${p.name}`, null,
    h("label", { for: "provider", text: "Company" }),
    providerSelect(p.id, (id) => replace("keyguide", id)),
    h("ol", {}, p.key_steps.map((step) => h("li", { text: step }))),
    h("p", {}, h("a", { href: p.key_url, target: "_blank", rel: "noopener noreferrer" },
      `Open the ${p.name} key page`), " (opens in a new tab)."),
    explain("Keep the key private, like a password. Anyone with it can spend on your account."),
    actions(h("button", { type: "button", class: "primary", onclick: () => show("keyform", p.id) },
      "I have my key")));
};

screens.keyform = (pid) => {
  const p = provider(pid || "gemini");
  const input = h("input", { type: "password", id: "key", autocomplete: "off", spellcheck: "false" });
  const status = h("p", { role: "status" });
  const submit = h("button", { type: "button", class: "primary" }, "Check and save");
  submit.addEventListener("click", async () => {
    submit.disabled = true;
    status.className = "";
    status.textContent = "Checking the key with a free request...";
    try {
      const out = await api("/api/key", { provider: p.id, key: input.value });
      input.value = "";
      await refresh();
      show("keydone", p.id, out.hint);
    } catch (err) {
      status.className = "error";
      status.textContent = err.message;
      submit.disabled = false;
    }
  });
  return card("Add your API key", null,
    h("label", { for: "provider", text: "Company" }),
    providerSelect(p.id, (id) => replace("keyform", id)),
    !p.ready ? h("p", { class: "warn", text: `${p.name} needs an add-on that is not installed yet.` }) : null,
    h("label", { for: "key", text: "Key" }), input,
    fromEnvironment(p)
      ? h("p", { class: "warn", text: `A key is already set in the ${p.key_source} environment variable, ` +
          "and it takes precedence over a key saved here. Change or remove that variable to use this one." })
      : p.key_hint ? h("p", { class: "explain", text: `A key is already saved (${p.key_hint}); saving replaces it.` }) : null,
    explain("The key is checked with a free request, then kept in this computer's password vault. " +
            "It is never shown in full again."),
    status,
    actions(submit, h("button", { type: "button", class: "link", onclick: () => show("keyguide", p.id) },
      "Where do I get one?")));
};

screens.keydone = (pid, hint) => {
  const p = provider(pid);
  return card(`Key saved for ${p.name}`, `${hint} is in this computer's password vault.`,
    h("p", { text: "What would you like to use?" }),
    choices([
      { label: `Use ${p.name}`, recommended: true, detail: p.summary, onclick: () => show("pickmodel", p.id) },
      { label: "Set up a model on this computer instead",
        detail: "Private and offline, but slower. Your key stays saved for later.",
        onclick: () => show("localcheck") },
    ]),
    actions());
};

screens.pickmodel = async (pid) => {
  const p = provider(pid);
  let picker;
  let selected = () => "";
  if (p.models.length) {
    picker = h("div", { class: "options" }, p.models.map((m) =>
      h("label", { class: "option" },
        h("input", { type: "radio", name: "model", value: m.id, checked: m.id === p.default_model }),
        h("span", { class: "name", text: m.id + (m.id === p.default_model ? "  (suggested)" : "") }),
        h("span", { class: "meta", text: `about ${money(m.per_page)} a page (rough), $${m.price_in} / $${m.price_out} per million tokens` }),
        m.note ? h("span", { class: "note", text: m.note }) : null)));
    selected = () => (picker.querySelector("input:checked") || {}).value || "";
  } else {
    const live = await api(`/api/models?provider=${encodeURIComponent(pid)}`);
    picker = h("select", { id: "model" }, live.models.map((m) => h("option", { value: m }, m)));
    selected = () => picker.value;
  }
  const status = h("p", { role: "status" });
  return card(`Choose a model: ${p.name}`, p.summary,
    p.models.length ? null : h("label", { for: "model", text: "Model (pick one that accepts images)" }),
    picker,
    explain("Prices are the company's list prices; pages full of pictures cost more. You can switch " +
            "models any time in Settings."),
    status,
    actions(h("button", { type: "button", class: "primary", onclick: async () => {
      const model = selected();
      if (!model) { status.className = "error"; status.textContent = "Choose a model first."; return; }
      await save({ provider: p.id, model });
      finish();
    } }, "Use this model")));
};

// --- a model on this computer ---------------------------------------------------------

screens.localcheck = async () => {
  S.system = await api("/api/system");
  const { system, recommendation: rec, ollama } = S.system;
  const graphics = system.gpus.length
    ? system.gpus.map((g) => g.integrated ? `${g.name} (built-in, borrows main memory)` : `${g.name} (${g.dedicated_gb} GB of its own)`).join(", ")
    : "none found";
  const facts = h("table", { class: "facts" },
    [["Processor", system.cpu || "unknown"], ["Memory", `${system.ram_gb} GB`], ["Graphics", graphics],
     ["Free disk", `${system.disk_free_gb} GB`], ["Ollama", ollama.running ? `running (${ollama.running})` : ollama.program ? "installed, not running" : "not installed yet"]]
      .map(([k, v]) => h("tr", {}, h("th", { text: k }), h("td", { text: v }))));

  if (!rec.model) {
    return card("This computer is too small for a local model", null, facts,
      rec.reasons.map((r) => h("p", { text: r })),
      actions(h("button", { type: "button", class: "primary", onclick: () => show("keyguide", "gemini") },
        "Get a free Gemini key")));
  }

  const options = h("div", { class: "options" }, rec.options.map((o) =>
    h("label", { class: "option" + (o.fits ? "" : " disabled") },
      h("input", { type: "radio", name: "local", value: o.model.tag, disabled: !o.fits,
                   checked: o.model.tag === rec.model.tag }),
      h("span", { class: "name", text: `${o.model.name}, ${o.model.download_gb} GB` +
        (o.model.tag === rec.model.tag ? "  (suggested)" : "") + (o.fits ? "" : "  (too big for this computer)") }),
      h("span", { class: "meta", text: `Good at: ${o.model.good_at}` }),
      h("span", { class: "note", text: `Limits: ${o.model.limits}` }))));
  const list = automatic() ? h("details", {}, h("summary", { text: "See all options" }), options) : options;

  return card("A model for this computer", null, facts,
    h("h2", { text: `Suggested: ${rec.model.name}, running on the ${rec.runs_on}` }),
    rec.reasons.map((r) => h("p", { text: r })),
    rec.warnings.map((w) => h("p", { class: "warn", text: w })),
    h("h2", { text: "You choose" }), list,
    actions(h("button", { type: "button", class: "primary", onclick: () => {
      S.localModel = (options.querySelector("input:checked") || {}).value || rec.model.tag;
      show("localinstall");
    } }, "Continue")));
};

function progressArea() {
  const bar = h("progress", { max: 1 });
  bar.removeAttribute("value");               // no value: an "in progress" stripe
  const text = h("p", { class: "explain", role: "status" });
  return { node: h("div", {}, bar, text), bar, text };
}

screens.localinstall = () => {
  const o = S.system.ollama;
  if (o.running) return screens.localpull();
  const progress = progressArea();
  progress.node.hidden = true;
  const go = h("button", { type: "button", class: "primary" }, o.program ? "Start Ollama" : "Install Ollama");
  go.addEventListener("click", async () => {
    go.disabled = true;
    progress.node.hidden = false;
    try {
      const job = await api("/api/local/install", {});
      await follow(job, (j) => { progress.text.textContent = j.message; });
      S.system = await api("/api/system");
      show("localpull");
    } catch (err) {
      progress.text.className = "error";
      progress.text.textContent = err.message;
      go.disabled = false;
    }
  });
  const manual = !o.program && !o.can_install;
  return card(o.program ? "Start Ollama" : "Install Ollama",
    "Ollama is the free program that runs AI models on this computer.",
    manual
      ? h("p", {}, "Install it from ", h("a", { href: "https://ollama.com/download", target: "_blank", rel: "noopener noreferrer" }, "ollama.com/download"),
          ", then press Check again.")
      : explain("It comes from Ollama's official package (about 1 GB). Windows may ask for permission."),
    progress.node,
    manual
      ? actions(h("button", { type: "button", class: "primary", onclick: () => replace("localcheck") }, "Check again"))
      : actions(go));
};

screens.localpull = () => {
  const model = S.system.catalog.find((m) => m.tag === S.localModel);
  if (S.system.ollama.models.includes(model.tag)) return screens.localtest();
  const progress = progressArea();
  progress.node.hidden = true;
  const go = h("button", { type: "button", class: "primary" }, `Download ${model.name}`);
  go.addEventListener("click", async () => {
    go.disabled = true;
    progress.node.hidden = false;
    try {
      const job = await api("/api/local/pull", { model: model.tag });
      await follow(job, (j) => {
        if (j.total) {
          progress.bar.max = j.total;
          progress.bar.value = j.done;
          progress.text.textContent = `${gb(j.done)} of ${gb(j.total)} GB`;
        } else {
          progress.text.textContent = j.message;
        }
      });
      show("localtest");
    } catch (err) {
      progress.text.className = "error";
      progress.text.textContent = err.message;
      go.disabled = false;
    }
  });
  return card(`Download ${model.name}`, `${model.download_gb} GB, once.`,
    explain("On a slow connection this takes a while. You can keep using your computer, and if it " +
            "stops, pressing Download again continues where it left off."),
    progress.node, actions(go));
};

screens.localtest = () => {
  const model = S.system.catalog.find((m) => m.tag === S.localModel);
  const progress = progressArea();
  progress.node.hidden = true;
  const result = h("div");
  const go = h("button", { type: "button", class: "primary" }, "Run the speed test");
  const done = h("button", { type: "button", class: "primary", hidden: true }, "Finish");
  done.addEventListener("click", finish);
  const run = async () => {
    go.disabled = true;
    progress.node.hidden = false;
    try {
      const job = await api("/api/local/test", { model: model.tag });
      const r = await follow(job, (j) => { progress.text.textContent = j.message; });
      progress.node.hidden = true;
      result.replaceChildren(
        h("p", { class: r.read_ok ? "ok" : "warn", text: r.read_ok ? "It read the test page correctly." : "It did not read the test page correctly: check its output on your own files." }),
        h("p", { text: r.verdict }),
        h("p", { class: "explain", text: `Loading took ${r.load_seconds} s (once per session).` }));
      await save({ provider: "ollama", model: model.tag });
      go.hidden = true;
      done.hidden = false;
    } catch (err) {
      progress.text.className = "error";
      progress.text.textContent = err.message;
      go.disabled = false;
    }
  };
  go.addEventListener("click", run);
  if (automatic()) setTimeout(run, 0);
  return card("Speed test", `One made-up page, to see how fast ${model.name} is on this computer.`,
    explain("The first run loads the model into memory, so it takes longer than later pages."),
    progress.node, result, actions(go, done));
};

// --- the end, and settings ---------------------------------------------------------------

async function finish() {
  await save({ setup_done: true });
  await refresh();
  show("done");
}

function commandLine() {
  return h("pre", { text: 'bettermarkitdown "C:\\path\\to\\your file.pdf"' });
}

screens.done = async () => {
  await refresh();
  const { audience } = S.state.settings;
  const active = S.state.active;
  const p = provider(active.provider);
  const human = audience !== "agent";
  const agent = audience === "agent" || audience === "both";
  return card("You're set up",
    p ? `Using ${p.name}${active.model ? ", " + active.model : ""}.` : null,
    human ? [
      h("h2", { text: "Convert a document" }),
      h("p", { text: "Add files in your library, convert them, and check and edit the result " +
        "beside the original." }),
      h("div", { class: "actions" },
        h("button", { type: "button", class: "primary", onclick: () => show("library") }, "Open your library")),
      explain("From a terminal, the same conversion is:"),
      automatic() ? null : commandLine(),
    ] : null,
    agent ? [h("h2", { text: "For your AI agent" }), await agentPanel()] : null,
    h("div", { class: "actions" },
      h("button", { type: "button", onclick: () => show("settings") }, "Settings"),
      h("button", { type: "button", onclick: quit }, "Quit")));
};

screens.settings = async () => {
  await refresh();
  const active = S.state.active;
  const rows = S.state.providers.map((p) => {
    const ready = !p.needs_key || p.key_source;
    return h("tr", {},
      h("td", {}, h("strong", { text: p.name })),
      h("td", { text: p.id === "custom" ? "set it up from the command line, with --base-url"
        : !p.needs_key ? "no key needed"
        : fromEnvironment(p) ? `key set in the ${p.key_source} environment variable (change it there)`
        : p.key_source ? `key saved (${p.key_hint})` : "no key" }),
      h("td", {},
        p.needs_key && p.key_url && !fromEnvironment(p) ? h("button", { type: "button", class: "link", onclick: () => show("keyform", p.id) }, p.key_source ? "Replace key" : "Add key") : null,
        p.key_source === "password store" ? h("button", { type: "button", class: "link", onclick: async () => {
          await api("/api/key/forget", { provider: p.id });
          replace("settings");
        } }, "Forget") : null,
        ready && p.id !== "custom" ? h("button", { type: "button", class: "link", onclick: () => p.local ? show("localcheck") : show("pickmodel", p.id) },
          active.provider === p.id ? "Change model" : "Use") : null));
  });

  const office = S.state.office;
  const officeLine = office.word || office.powerpoint
    ? "Microsoft Office is installed: old .doc and .ppt files will open."
    : office.libreoffice ? "LibreOffice is installed: old .doc and .ppt files will open."
    : "Neither Microsoft Office nor LibreOffice is installed, so old .doc and .ppt files cannot be opened. New .docx, .pptx and PDF files work regardless.";
  const officeStatus = h("p", { role: "status" });
  const installOffice = !office.word && !office.powerpoint && !office.libreoffice && office.can_install_libreoffice
    ? h("button", { type: "button", onclick: async (ev) => {
        ev.target.disabled = true;
        try {
          const job = await api("/api/office/install", {});
          await follow(job, (j) => { officeStatus.textContent = j.message; });
          replace("settings");
        } catch (err) { officeStatus.className = "error"; officeStatus.textContent = err.message; ev.target.disabled = false; }
      } }, "Install LibreOffice (free)") : null;

  const help = h("select", { id: "help", onchange: async () => { await save({ help_level: help.value }); } },
    [["assisted", "Assisted: explain each choice"], ["automatic", "Automatic: recommended choices, ask before installing or spending"]]
      .map(([v, label]) => h("option", { value: v, selected: S.state.settings.help_level === v }, label)));

  const agentsPart = S.state.settings.audience === "human" ? null
    : [h("h2", { text: "AI agents" }), await agentPanel()];
  const game = h("input", { type: "checkbox", id: "game", checked: S.state.settings.offer_game,
    onchange: async () => { await save({ offer_game: game.checked }); } });

  return card("Settings", `In use: ${provider(active.provider)?.name || "nothing yet"}${active.model ? ", " + active.model : ""}.`,
    h("h2", { text: "AI services" }),
    h("table", { class: "keys" }, rows),
    h("h2", { text: "Old Word and PowerPoint files" }),
    h("p", { text: officeLine }), installOffice, officeStatus,
    h("h2", { text: "Help" }),
    h("label", { for: "help", text: "How much help the setup gives" }), help,
    agentsPart,
    h("h2", { text: "While you wait" }),
    h("label", { class: "check" }, game, " Offer a small game during conversions longer than 2 minutes"),
    h("div", { class: "actions" },
      h("button", { type: "button", onclick: () => show("audience") }, "Run setup again"),
      backButton()));
};

// The skill that teaches AI agents to use this tool: where each agent on this computer
// looks for it, an install button for each (the click is the yes), and how to register
// the MCP server, which is optional.
async function agentPanel() {
  const data = await api("/api/agents");
  const status = h("p", { role: "status" });
  const rows = data.agents.map((a) => {
    const installed = a.folders.some((f) => f.installed);
    const foreign = a.folders.some((f) => f.installed === "");
    const button = h("button", { type: "button", class: "link" },
      installed ? "Update the skill" : "Install the skill");
    const state = h("td", { text: a.detected ? (installed ? "found, skill installed" : "found on this computer")
                                             : installed ? "skill installed" : "not found" });
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        const out = await api("/api/agents/install", { agents: [a.id] });
        const skipped = out.results.find((r) => r.result === "skipped");
        status.className = skipped ? "warn" : "ok";
        if (!skipped) { state.textContent = a.detected ? "found, skill installed" : "skill installed"; button.textContent = "Update the skill"; }
        status.textContent = skipped ? `${a.name}: ${skipped.why}.`
          : `${a.name}: ${out.results.map((r) => `${r.result} in ${r.folder}`).join("; ")}. Restart it to pick it up.`;
      } catch (err) { status.className = "error"; status.textContent = err.message; }
      button.disabled = false;
    });
    return h("tr", {},
      h("td", {}, h("strong", { text: a.name })),
      state,
      h("td", {}, foreign ? h("span", { class: "warn", text: "another skill has this name" })
                          : a.detected || installed ? button : null));
  });
  const mcp = h("details", {},
    h("summary", { text: "Also give agents tools directly (MCP, optional)" }),
    h("p", { class: "explain", text: "Agents that speak the Model Context Protocol can call BetterMarkItDown as " +
      "tools instead of commands. Register it once, with the command shown for your agent:" }),
    data.agents.map((a) => [h("h3", { text: a.name }), h("pre", { text: data.mcp_instructions[a.id] })]));
  return h("div", {},
    h("p", { text: "A skill is a short guide an AI agent reads to use this tool well: look first, ask " +
      "before spending, check the result against the PDF. It is copied into the folder each agent reads." }),
    h("table", { class: "keys" }, rows), status,
    h("p", { class: "explain", text: "Agents can check the setup with: bettermarkitdown setup --json" }),
    mcp);
}

async function quit() {
  try { await api("/api/quit", {}); } catch (_) { /* already stopping */ }
  clearInterval(keepAlive);
  root.replaceChildren(card("BetterMarkItDown has stopped", "You can close this tab. Open it again from its icon, or with: bettermarkitdown app"));
}

// --- start ------------------------------------------------------------------------------

document.getElementById("nav-library").addEventListener("click", () => show("library"));
document.getElementById("nav-settings").addEventListener("click", () => show("settings"));
document.getElementById("nav-theme").addEventListener("click", async () => {
  const theme = THEMES[(THEMES.indexOf(S.state.settings.theme) + 1) % THEMES.length];
  applyTheme(theme);
  S.state.settings.theme = theme;
  try { await save({ theme }); } catch (_) { /* this page keeps it; the next launch may not */ }
});
window.addEventListener("beforeunload", (ev) => {
  if (S.unsaved && S.unsaved()) { ev.preventDefault(); ev.returnValue = ""; }
});
document.getElementById("nav-quit").addEventListener("click", quit);
// Tell the server the page is still open; it stops on its own a while after the tab closes.
const keepAlive = setInterval(() => { api("/api/ping").catch(() => {}); }, 20000);

// "#screen=keyguide&arg=openai" opens one screen directly, for screenshots and checks;
// "&arg=" may repeat. Once set up, the page opens on the library.
function startScreen() {
  const params = new URLSearchParams(location.hash.slice(1));
  const name = params.get("screen");
  const home = S.state.settings.setup_done ? "library" : "welcome";
  show(home);
  if (name && name !== home && Object.hasOwn(screens, name)) show(name, ...params.getAll("arg"));
}

refresh().then(startScreen).catch((err) => {
  root.replaceChildren(card("BetterMarkItDown could not start", null, h("p", { class: "error", text: err.message })));
});
