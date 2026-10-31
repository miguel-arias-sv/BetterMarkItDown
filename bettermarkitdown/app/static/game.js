// LlamaGame, "play while you wait": a llama hops over stacks of paper, ducks under flying
// staplers and collects files, while a long conversion runs. Opt-in, never
// started by itself. Our own characters and rules; every sprite is drawn here from
// a few rows of text, so nothing is downloaded.
//
// Three ways to show it: a panel in a corner of the page (drag it to another one),
// full screen, and, in Chrome and Edge, a pop-out window that stays on top of other
// programs (Document Picture-in-Picture). The progress bar is always on its top edge.
"use strict";

const Game = (() => {
  const W = 160, H = 90, GROUND = 78;          // drawn at 2x and up, with crisp pixels
  const COLORS = { o: "#4a3020", c: "#f4e9cf", b: "#c99a6b", e: "#1b1b1b", p: "#e9a3a8",
                   w: "#ffffff", l: "#9db7d6", g: "#b8b8b8", r: "#b8322c", k: "#2b2b2b",
                   y: "#f5d76e" };
  const SPRITES = {
    run1: [
      "...........oo...",
      "..........ocpo..",
      "..........occo..",
      ".........occeco.",
      ".........occcccoo",
      ".........occcco..",
      ".........occo....",
      ".........occo....",
      ".........occo....",
      ".oooooooobcco....",
      "ocbcbcbcbcccco...",
      "occcccccccccco...",
      "occcccccccccco...",
      ".occcccccccco....",
      "..oco....oco.....",
      "..oco.....oco....",
      "..oo.......oo....",
    ],
    run2: [
      "...........oo...",
      "..........ocpo..",
      "..........occo..",
      ".........occeco.",
      ".........occcccoo",
      ".........occcco..",
      ".........occo....",
      ".........occo....",
      ".........occo....",
      ".oooooooobcco....",
      "ocbcbcbcbcccco...",
      "occcccccccccco...",
      "occcccccccccco...",
      ".occcccccccco....",
      "...oco..oco......",
      "..oco....oco.....",
      ".oo.......oo.....",
    ],
    duck: [
      "...............oo..",
      "..............ocpo.",
      ".oooooooooooooccco.",
      "ocbcbcbcbcbcccceco.",
      "occcccccccccccccccoo",
      "occcccccccccccccco..",
      ".occcccccccccccoo...",
      "..oco....oco........",
      "..oco.....oco.......",
      "..oo.......oo.......",
    ],
    stapler: [
      "..kkkkkkkkkk..",
      ".krrrrrrrrrrk.",
      "krrrrrrrrrrrrk",
      ".kkkkkkkkkkkk.",
      "kggggggggggggk",
      ".kkkkkkkkkkkk.",
    ],
  };
  const images = {};

  function sprite(name) {
    if (images[name]) return images[name];
    const rows = SPRITES[name];
    const c = document.createElement("canvas");
    c.width = Math.max(...rows.map((r) => r.length));
    c.height = rows.length;
    const x = c.getContext("2d");
    rows.forEach((row, y) => [...row].forEach((ch, i) => {
      if (ch !== ".") { x.fillStyle = COLORS[ch]; x.fillRect(i, y, 1, 1); }
    }));
    return (images[name] = c);
  }

  const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Words go on a see-through layer over the pixel canvas, drawn at the screen's own
  // resolution: the pixel art stays blocky and the text stays sharp at any size, full
  // screen included. begin() fits the layer to the screen, clears it and returns its
  // context, measured in game pixels like the canvas under it. onResize redraws a scene
  // that stands still (a paused game) when the layer changes size, as on full screen.
  function textLayer(pixels, onResize) {
    const layer = document.createElement("canvas");
    layer.className = "text-layer";
    layer.setAttribute("aria-hidden", "true");
    const t = layer.getContext("2d");
    const begin = () => {
      const view = layer.ownerDocument.defaultView || window;
      const ratio = view.devicePixelRatio || 1;
      const w = Math.max(1, Math.round(layer.clientWidth * ratio));
      const hh = Math.max(1, Math.round(layer.clientHeight * ratio));
      if (layer.width !== w || layer.height !== hh) { layer.width = w; layer.height = hh; }
      t.setTransform(w / pixels.width, 0, 0, hh / pixels.height, 0, 0);
      t.clearRect(0, 0, pixels.width, pixels.height);
      return t;
    };
    if (onResize && "ResizeObserver" in window) new ResizeObserver(onResize).observe(layer);
    return { node: layer, begin };
  }

  // --- the pixel font: our own letters, drawn from a few rows of text like the sprites ---
  // Each glyph is rows of "#" (ink) and "." split by "/", top row first: 7 rows to the
  // baseline, 2 more for descenders. Every font pixel is a whole number of screen pixels,
  // so the letters are sharp at any size. A text with a character not here is written in
  // the system font instead, so nothing is ever lost.
  const GLYPHS = {
    A: ".###./#...#/#...#/#####/#...#/#...#/#...#", B: "####./#...#/#...#/####./#...#/#...#/####.",
    C: ".###./#...#/#..../#..../#..../#...#/.###.", D: "####./#...#/#...#/#...#/#...#/#...#/####.",
    E: "#####/#..../#..../####./#..../#..../#####", F: "#####/#..../#..../####./#..../#..../#....",
    G: ".###./#...#/#..../#.###/#...#/#...#/.###.", H: "#...#/#...#/#...#/#####/#...#/#...#/#...#",
    I: "###/.#./.#./.#./.#./.#./###", J: "..###/...#./...#./...#./#..#./#..#./.##..",
    K: "#...#/#..#./#.#../##.../#.#../#..#./#...#", L: "#..../#..../#..../#..../#..../#..../#####",
    M: "#...#/##.##/#.#.#/#.#.#/#...#/#...#/#...#", N: "#...#/##..#/#.#.#/#..##/#...#/#...#/#...#",
    O: ".###./#...#/#...#/#...#/#...#/#...#/.###.", P: "####./#...#/#...#/####./#..../#..../#....",
    Q: ".###./#...#/#...#/#...#/#.#.#/#..#./.##.#", R: "####./#...#/#...#/####./#.#../#..#./#...#",
    S: ".####/#..../#..../.###./....#/....#/####.", T: "#####/..#../..#../..#../..#../..#../..#..",
    U: "#...#/#...#/#...#/#...#/#...#/#...#/.###.", V: "#...#/#...#/#...#/#...#/#...#/.#.#./..#..",
    W: "#...#/#...#/#...#/#.#.#/#.#.#/#.#.#/.#.#.", X: "#...#/#...#/.#.#./..#../.#.#./#...#/#...#",
    Y: "#...#/#...#/.#.#./..#../..#../..#../..#..", Z: "#####/....#/...#./..#../.#.../#..../#####",
    a: "...../...../.###./....#/.####/#...#/.####", b: "#..../#..../####./#...#/#...#/#...#/####.",
    c: "..../..../.###/#.../#.../#.../.###", d: "....#/....#/.####/#...#/#...#/#...#/.####",
    e: "...../...../.###./#...#/#####/#..../.###.", f: "..##/.#../.#../####/.#../.#../.#..",
    g: "...../...../.####/#...#/#...#/#...#/.####/....#/.###.", h: "#..../#..../####./#...#/#...#/#...#/#...#",
    i: "#/./#/#/#/#/#", j: "..#/.../..#/..#/..#/..#/..#/#.#/.#.",
    k: "#.../#.../#..#/#.#./##../#.#./#..#", l: "#./#./#./#./#./#./.#",
    m: "...../...../##.#./#.#.#/#.#.#/#.#.#/#.#.#", n: "...../...../####./#...#/#...#/#...#/#...#",
    o: "...../...../.###./#...#/#...#/#...#/.###.", p: "...../...../####./#...#/#...#/#...#/####./#..../#....",
    q: "...../...../.####/#...#/#...#/#...#/.####/....#/....#", r: "..../..../#.##/##../#.../#.../#...",
    s: "..../..../.###/#.../.##./...#/###.", t: ".#../.#../####/.#../.#../.#../..##",
    u: "...../...../#...#/#...#/#...#/#...#/.####", v: "...../...../#...#/#...#/#...#/.#.#./..#..",
    w: "...../...../#...#/#...#/#.#.#/#.#.#/.#.#.", x: "...../...../#...#/.#.#./..#../.#.#./#...#",
    y: "...../...../#...#/#...#/#...#/#...#/.####/....#/.###.", z: "...../...../#####/...#./..#../.#.../#####",
    0: ".##./#..#/#..#/#..#/#..#/#..#/.##.", 1: ".#./##./.#./.#./.#./.#./###",
    2: ".###./#...#/....#/...#./..#../.#.../#####", 3: "####./....#/....#/.###./....#/....#/####.",
    4: "...#./..##./.#.#./#..#./#####/...#./...#.", 5: "#####/#..../####./....#/....#/#...#/.###.",
    6: ".###./#..../#..../####./#...#/#...#/.###.", 7: "#####/....#/...#./..#../.#.../.#.../.#...",
    8: ".###./#...#/#...#/.###./#...#/#...#/.###.", 9: ".###./#...#/#...#/.####/....#/....#/.###.",
    ".": "././././././#", ",": "../../../../../.#/.#/#.", ":": "././#/./././#",
    "!": "#/#/#/#/#/./#", "?": ".###./#...#/....#/...#./..#../...../..#..", "'": "#/#", '"': "#.#/#.#",
    "-": ".../.../.../###", "+": ".../.../.#./###/.#.", "/": "..#/..#/.#./.#./.#./#../#..",
    "(": ".#/#./#./#./#./#./.#", ")": "#./.#/.#/.#/.#/.#/#.", "·": "./././#", "=": "..../..../####/..../####",
    "%": "##..#/##.#./..#../..#../.#.../#.##./...##",
  };
  const font = {};
  for (const [ch, rows] of Object.entries(GLYPHS)) {
    const lines = rows.split("/");
    const ink = [];
    lines.forEach((row, r) => [...row].forEach((c, i) => { if (c === "#") ink.push([i, r]); }));
    font[ch] = { w: Math.max(...lines.map((row) => row.length)), ink };
  }
  font[" "] = { w: 3, ink: [] };

  // Writes `text` with its baseline at game-pixel y, left, centred or right of x. `size`
  // is one font pixel in game pixels (0.7 makes capitals 4.9 game pixels tall).
  function pixelText(t, text, x, y, size, align = "center") {
    text = String(text).replace(/…/g, "...");
    const glyphs = [...text].map((ch) => font[ch]);
    if (glyphs.some((g) => !g)) {                       // not in the font: the system's
      t.font = `600 ${Math.round(size * 10)}px system-ui, sans-serif`;
      t.textAlign = align;
      t.fillText(text, x, y);
      return;
    }
    const scale = t.getTransform().a;                    // screen pixels per game pixel
    const dot = Math.max(1, Math.round(size * scale));   // one font pixel, on the screen
    const width = (glyphs.reduce((n, g) => n + g.w + 1, 0) - 1) * dot;
    let left = Math.round(x * scale - (align === "center" ? width / 2 : align === "right" ? width : 0));
    const top = Math.round(y * scale) - 7 * dot;
    t.save();
    t.setTransform(1, 0, 0, 1, 0, 0);
    for (const g of glyphs) {
      for (const [i, r] of g.ink) t.fillRect(left + i * dot, top + r * dot, dot, dot);
      left += (g.w + 1) * dot;
    }
    t.restore();
  }

  // --- the record: files collected and the best score, in every form of the game ------------
  // The llama collects files in four colours, in LlamaGame and in every wait alike, and
  // Markdown files on a LlamaRun and as LlamaGame's rewards. The record lives in the settings (app.js keeps it),
  // so it carries from one launch to the next: the browser's own storage is new at every
  // launch, since the port is.
  const FILE_KINDS = [
    { id: "pdf", label: "PDF", color: "#d93a2b" },
    { id: "docx", label: "DOCX", color: "#2b6cd9" },
    { id: "xlsx", label: "XLSX", color: "#1f8f4a" },
    { id: "pptx", label: "PPTX", color: "#e8772e" },
  ];
  const MD = { id: "md", label: "MD", color: "#6f42c1" };
  const ALL_KINDS = [...FILE_KINDS, MD];
  const haul = {};
  let bestEver = 0;
  let runBest = 0;                               // the longest LlamaRun, in metres
  let tries = 0;                                 // LlamaGame's tries: every third gives an MD
  const shown = new Set();                       // tally lines on the page, kept current

  // From the saved settings. The larger count wins: a file collected a moment ago may not
  // have reached the settings yet when the page reads them again.
  function setRecord(settings) {
    for (const k of ALL_KINDS) haul[k.id] = Math.max(haul[k.id] || 0, (settings.haul || {})[k.id] || 0);
    bestEver = Math.max(bestEver, settings.game_best || 0);
    runBest = Math.max(runBest, settings.run_best || 0);
    tries = Math.max(tries, settings.game_tries || 0);
    refreshTallies();
  }

  function collect(kind, count = 1) {
    haul[kind.id] = (haul[kind.id] || 0) + count;
    keepRecord();
    refreshTallies();
  }

  function keepRecord() {
    if (typeof keepGameRecord === "function") {
      keepGameRecord({ haul: { ...haul }, game_best: bestEver, run_best: runBest, game_tries: tries });
    }
  }

  function refreshTallies() {
    for (const node of [...shown]) {
      if (node.isConnected || !node.dataset.seen) showHaul(node);
      else shown.delete(node);
    }
  }

  function tally() {
    const node = document.createElement("p");
    node.className = "haul";
    shown.add(node);
    showHaul(node);
    return node;
  }

  function showHaul(node) {
    if (node.isConnected) node.dataset.seen = "1";
    const total = ALL_KINDS.reduce((n, k) => n + (haul[k.id] || 0), 0);
    const types = ALL_KINDS.filter((k) => haul[k.id]).length;
    const lead = document.createElement("span");
    lead.textContent = `Collected so far: ${total} file${total === 1 ? "" : "s"} from ${types} of ${ALL_KINDS.length} types`;
    node.replaceChildren(lead, ...ALL_KINDS.map((k) => {
      const chip = document.createElement("span");
      chip.className = `chip ${k.id}`;
      chip.textContent = `${k.label} ${haul[k.id] || 0}`;
      if (k === MD) chip.title = "Markdown files: on a LlamaRun, 5 at each LlamaGame signpost, and 1 for every three tries";
      return chip;
    }));
  }

  // --- state -------------------------------------------------------------------------
  let box = null, canvas, ctx, words, bar, label, scoreText, banner, bannerText, hint, gameTally;
  let win = window;                            // the window the game is in (page or pop-out)
  let state = "ready";                         // ready | running | paused | over | done
  let llama, things, posts, pops, speed, distance, pages, best, obstacleIn, fileIn, nextMark;
  let lastTime, frame, raf;
  let overNote = "";
  let corner = "br";
  let closing = false;                         // Close was pressed in the pop-out window

  function reset() {
    llama = { y: GROUND, vy: 0, ducking: false };
    things = [];
    posts = [];
    pops = [];
    speed = 50;
    distance = 0;
    pages = 0;
    obstacleIn = 1.8;
    fileIn = 0.9;
    nextMark = MARK_FIRST;
    best = bestEver;
  }

  // --- the window around it ---------------------------------------------------------------
  function build() {
    const h = (tag, cls, text) => { const el = document.createElement(tag); if (cls) el.className = cls; if (text) el.textContent = text; return el; };
    box = h("section", "game corner-br");
    box.setAttribute("aria-label", "A game to play while you wait");
    const tools = h("div", "game-tools");
    const title = h("span", "game-title", "LlamaGame");
    const full = h("button", "link", "Full screen");
    const pop = h("button", "link", "Pop out");
    const close = h("button", "link", "Close");
    for (const b of [full, pop, close]) b.type = "button";
    full.addEventListener("click", fullScreen);
    document.addEventListener("fullscreenchange", () => {
      full.textContent = document.fullscreenElement === box ? "Exit full screen" : "Full screen";
      canvas.focus();
    });
    pop.addEventListener("click", popOut);
    close.addEventListener("click", closeGame);
    if (!("documentPictureInPicture" in window)) pop.hidden = true;
    tools.append(title, full, pop, close);
    tools.addEventListener("pointerdown", startDrag);

    const stage = h("div", "game-stage");
    bar = h("progress", "game-bar");
    bar.max = 1;
    label = h("p", "game-label", "Converting...");
    scoreText = h("p", "game-score", "");
    canvas = h("canvas", "game-canvas");
    canvas.width = W;
    canvas.height = H;
    canvas.tabIndex = 0;
    canvas.setAttribute("aria-label", "Game: press Space to jump, Down arrow to duck, P to pause");
    canvas.addEventListener("pointerdown", (ev) => { ev.preventDefault(); canvas.focus(); press("jump"); });
    hint = h("p", "game-hint", "Space or tap: jump. Down arrow: duck. P: pause. Each signpost: +5 MD. Every third try: +1 MD.");
    banner = h("div", "game-banner");
    banner.hidden = true;
    bannerText = h("p", "", "Your file is ready");
    banner.append(bannerText);
    words = textLayer(canvas, () => { if (state !== "running") draw(); });
    stage.append(canvas, words.node, bar, label, scoreText, banner);
    gameTally = tally();
    box.append(tools, stage, gameTally, hint);
    ctx = canvas.getContext("2d");
    ctx.imageSmoothingEnabled = false;
  }

  function listen(target, on) {
    const fn = on ? "addEventListener" : "removeEventListener";
    target[fn]("keydown", onKey);
    target[fn]("keyup", onKeyUp);
    target.document[fn]("visibilitychange", onVisibility);
  }

  function open() {
    if (!box) build();
    if (!box.isConnected) {
      document.body.append(box);
      listen(window, true);
    }
    shown.add(gameTally);                        // dropped while the game was closed
    showHaul(gameTally);
    if (state === "done" || state === "over") state = "ready";
    if (state === "ready") reset();
    banner.hidden = true;
    canvas.focus();
    loop();
  }

  function closeGame() {
    if (!box) return;
    if (win !== window) { closing = true; win.close(); return; }   // see pagehide
    if (document.fullscreenElement === box) document.exitFullscreen();
    if (raf) cancelAnimationFrame(raf);
    raf = null;
    listen(window, false);
    box.remove();
    if (state === "running") state = "paused";
  }

  function fullScreen() {
    if (win !== window) return;
    if (document.fullscreenElement) document.exitFullscreen();
    else box.requestFullscreen().catch(() => {});
    canvas.focus();
  }

  async function popOut() {
    if (!("documentPictureInPicture" in window) || win !== window) return;
    let pip;
    try {
      pip = await documentPictureInPicture.requestWindow({ width: 520, height: 340 });
    } catch (_) { return; }                     // refused, or not from a click
    for (const link of document.querySelectorAll('link[rel="stylesheet"]')) {
      const copy = pip.document.createElement("link");
      copy.rel = "stylesheet";
      copy.href = link.href;
      pip.document.head.append(copy);
    }
    pip.document.body.className = "game-pip";
    listen(window, false);
    box.classList.add("popped");
    pip.document.body.append(box);
    win = pip;
    listen(pip, true);
    pip.addEventListener("pagehide", () => {
      listen(pip, false);
      win = window;
      raf = null;                               // the closed window's frame never comes
      box.classList.remove("popped");
      document.body.append(box);
      listen(window, true);
      if (closing) { closing = false; closeGame(); return; }
      loop();
    });
    canvas.focus();
    loop();
  }

  // Drag the title bar; let go and it settles in the nearest corner.
  function startDrag(ev) {
    if (ev.target.tagName === "BUTTON" || win !== window || document.fullscreenElement) return;
    ev.preventDefault();
    const up = (e) => {
      window.removeEventListener("pointerup", up);
      corner = (e.clientY < innerHeight / 2 ? "t" : "b") + (e.clientX < innerWidth / 2 ? "l" : "r");
      box.className = `game corner-${corner}`;
    };
    window.addEventListener("pointerup", up);
  }

  // --- controls ---------------------------------------------------------------------------
  function press(action) {
    if (state === "done") return;
    if (state === "ready" || state === "over") { reset(); state = "running"; lastTime = 0; loop(); return; }
    if (state === "paused") { state = "running"; lastTime = 0; loop(); return; }
    if (action === "jump" && llama.y >= GROUND && !llama.ducking) llama.vy = -JUMP;
  }

  function onKey(ev) {
    if (ev.target !== canvas && ev.target !== win.document.body && !box.contains(ev.target)) return;
    if (ev.target.tagName === "BUTTON" && (ev.key === " " || ev.key === "Enter")) return;
    if ([" ", "ArrowUp", "w", "W"].includes(ev.key)) { ev.preventDefault(); press("jump"); }
    else if (["ArrowDown", "s", "S"].includes(ev.key)) { ev.preventDefault(); if (state === "running") llama.ducking = true; }
    else if (ev.key === "p" || ev.key === "P") { state = state === "running" ? "paused" : state; if (state === "paused") draw(); }
  }

  function onKeyUp(ev) {
    if (["ArrowDown", "s", "S"].includes(ev.key) && llama) llama.ducking = false;
  }

  function onVisibility() {
    if (win.document.hidden && state === "running") { state = "paused"; draw(); }
  }

  // --- the game ----------------------------------------------------------------------------
  // Gentle at first, harder slowly: the speed rises over about a minute; the gaps between
  // obstacles shrink over about 500 m but always leave room to land and jump again; two-
  // and three-ream stacks come later, and staplers from 150 m. Files come on a timer of
  // their own, so they never crowd the obstacles. Obstacles hit a pixel inside their
  // drawing, so a near miss is a miss.
  //
  // Markdown files: each signpost (100 m, 300 m, 500 m...) gives 5 at once as the llama
  // passes it, and every third try gives 1, so they are never out of reach.
  const JUMP = 150, GRAVITY = 420;
  const AIRTIME = (2 * JUMP) / GRAVITY;          // seconds off the ground in a jump
  const MARK_FIRST = 100, MARK_GAP = 200;        // signposts, in metres (10 game pixels each)

  function spawnObstacle() {
    const metres = distance / 10;
    if (metres > 150 && Math.random() < Math.min(0.3, 0.1 + (metres - 150) / 2000)) {
      things.push({ kind: "stapler", x: W + 4, y: GROUND - 18, w: 14, h: 6, vx: 14 });
    } else {
      const tallest = metres < 80 ? 1 : metres < 250 ? 2 : 3;
      const reams = 1 + Math.floor(Math.random() * tallest);
      things.push({ kind: "stack", x: W + 4, y: GROUND - reams * 5, w: 10 + Math.round(Math.random() * 4), h: reams * 5, vx: 0 });
    }
    obstacleIn = Math.max(AIRTIME + 30 / speed, 2.0 - metres / 500) + Math.random() * 0.8;
  }

  function spawnFile() {
    things.push({ kind: "file", file: FILE_KINDS[Math.floor(Math.random() * FILE_KINDS.length)],
                  x: W + 4, y: GROUND - 22 - Math.round(Math.random() * 14), w: 7, h: 9, vx: 0 });
    fileIn = 1.3 + Math.random() * 1.4;
  }

  function llamaBox() {
    const tall = llama.ducking ? 10 : 17;
    return { x: 15, y: llama.y - tall + 2, w: llama.ducking ? 16 : 11, h: tall - 3 };
  }

  const hit = (a, b) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
  const solid = (o) => ({ x: o.x + 1, y: o.y + 1, w: o.w - 2, h: o.h - 1 });
  const score = () => Math.floor(distance / 10) + pages * 10;
  const triesLeft = () => {
    const left = 3 - (tries % 3);
    return `${left} more ${left === 1 ? "try" : "tries"} to win 1 MD`;
  };

  function update(dt) {
    speed = Math.min(105, speed + dt * 0.8);
    distance += speed * dt;
    llama.vy += GRAVITY * dt;
    llama.y = Math.min(GROUND, llama.y + llama.vy * dt);
    if (llama.y >= GROUND) llama.vy = 0;
    if (llama.y < GROUND) llama.ducking = false;
    obstacleIn -= dt;
    fileIn -= dt;
    if (obstacleIn <= 0) spawnObstacle();
    if (fileIn <= 0) spawnFile();
    if (distance / 10 >= nextMark) {
      posts.push({ x: W + 4, mark: nextMark });
      nextMark += MARK_GAP;
    }
    for (const p of posts) {
      p.x -= speed * dt;
      if (!p.passed && p.x + 10 < 14) {
        p.passed = true;
        collect(MD, 5);
        pops.push({ x: 22, y: llama.y - 20, t: 0, text: "+5 MD", color: MD.color });
      }
    }
    posts = posts.filter((p) => p.x > -22);
    pops = pops.filter((p) => (p.t += dt) < 1.2);
    const me = llamaBox();
    for (const o of things) {
      o.x -= (speed + o.vx) * dt;
      if (o.gone) continue;
      if (o.kind === "file") {
        if (!hit(me, o)) continue;
        o.gone = true;
        pages += 1;
        collect(o.file);
        pops.push({ x: o.x + 3, y: o.y - 2, t: 0, text: `+1 ${o.file.label}`, color: o.file.color });
      } else if (hit(me, solid(o))) {
        over();
        break;
      }
    }
    things = things.filter((o) => o.x + o.w > -2 && !o.gone);
  }

  function over() {
    state = "over";
    if (score() > best) best = bestEver = score();
    tries += 1;
    if (tries % 3 === 0) {
      collect(MD, 1);
      overNote = "+1 MD for three tries!";
    } else {
      overNote = triesLeft();
    }
    keepRecord();
  }

  function draw() {
    const tx = words.begin();
    ctx.fillStyle = "#eef3f7";
    ctx.fillRect(0, 0, W, H);
    // Shelves of folders in the distance: still when motion is reduced.
    const drift = reduced() ? 0 : (distance * 0.25) % 40;
    ctx.fillStyle = "#d5dfe8";
    for (let x = -drift; x < W; x += 40) { ctx.fillRect(x, 40, 22, 30); ctx.fillRect(x + 25, 50, 10, 20); }
    ctx.fillStyle = "#8a6f55";
    ctx.fillRect(0, GROUND + 1, W, 1);
    ctx.fillStyle = "#c7b299";
    const dash = reduced() ? 0 : distance % 12;
    for (let x = -dash; x < W; x += 12) ctx.fillRect(x, GROUND + 4, 5, 1);

    for (const p of posts) drawPost(ctx, tx, p.x, `${p.mark} m`, GROUND, 0.8);
    for (const o of things) {
      if (o.kind === "file") drawFile(ctx, o.x, o.y, o.file.color);
      else if (o.kind === "stapler") ctx.drawImage(sprite("stapler"), Math.round(o.x), Math.round(o.y));
      else {
        for (let i = 0; i < o.h / 5; i++) {
          const y = Math.round(o.y + i * 5);
          ctx.fillStyle = "#ffffff"; ctx.fillRect(Math.round(o.x), y, o.w, 5);
          ctx.fillStyle = "#9db7d6"; ctx.fillRect(Math.round(o.x), y + 4, o.w, 1);
          ctx.fillStyle = "#b8b8b8"; ctx.fillRect(Math.round(o.x) + o.w - 1, y, 1, 5);
        }
      }
    }
    const pose = llama.ducking ? "duck" : (llama.y < GROUND || state !== "running") ? "run1"
      : (Math.floor(distance / 9) % 2 ? "run1" : "run2");
    const img = sprite(pose);
    ctx.drawImage(img, 12, Math.round(llama.y - img.height + 1));
    for (const p of pops) {
      tx.fillStyle = p.color;
      pixelText(tx, p.text, p.x, p.y - p.t * 14, 0.8);
    }

    const coming = (posts.find((p) => !p.passed) || { mark: nextMark }).mark;
    scoreText.textContent = `Score ${score()}  ·  ${Math.floor(distance / 10)} m  ·  files ${pages}  ·  ` +
      `+5 MD at ${coming} m  ·  best ${best}`;
    const message = { ready: "Press Space to start", paused: "Paused: Space to go on",
                      over: "Oops! Space to try again" }[state];
    if (message) {
      const note = state === "over" ? overNote : state === "ready" ? triesLeft() : "";
      ctx.fillStyle = "rgba(20, 30, 45, 0.78)";
      ctx.fillRect(0, 28, W, note ? 27 : 20);
      tx.fillStyle = "#ffffff";
      pixelText(tx, message, W / 2, note ? 40 : 41, 0.8);
      if (note) {
        tx.fillStyle = "#d9c8ff";
        pixelText(tx, note, W / 2, 50, 0.8);
      }
    }
  }

  function loop() {
    if (raf || !box || !box.isConnected) return;
    const tick = (now) => {
      raf = null;
      if (!box.isConnected) return;
      if (state === "running") {
        const dt = lastTime ? Math.min(0.05, (now - lastTime) / 1000) : 0;
        if (!lastTime || now - lastTime >= 15) {       // about 60 frames a second, at most
          lastTime = now;
          update(dt);
        }
        draw();
        raf = win.requestAnimationFrame(tick);
      } else {
        draw();
      }
    };
    raf = win.requestAnimationFrame(tick);
  }

  // --- every wait: the llama with nothing in its way, and files to collect -----------------
  // Left and Right walk, Space, Up or a tap jumps, Down ducks. Files drift past in four
  // colours, added to the same record as LlamaGame's, so each wait carries on from the
  // last. Nothing to hit and no way to lose. It stops by itself once the wait is over.
  //
  // A wait that goes on becomes a LlamaRun: the metres count, and at every landmark (each
  // 100 m) a signpost comes with a folder of files, a bigger one each time. Markdown files
  // turn up here too (and in LlamaGame, as rewards). Waits one straight after another (a file added, then
  // looked through) are one wait: a runner that starts as another ends carries on from it.
  const RUN_AFTER = 15;                              // seconds of waiting before a LlamaRun
  const MARK_EVERY = 100;                            // metres between landmarks
  let wait = null;                                   // the wait in progress, shared
  let runners = 0;

  function drawFile(x, px, py, color) {
    px = Math.round(px);
    py = Math.round(py);
    x.fillStyle = color;
    x.fillRect(px, py, 7, 9);
    x.fillStyle = "#ffffff";
    x.fillRect(px + 5, py, 2, 2);                      // the folded corner
    x.fillRect(px + 1, py + 4, 5, 1);                  // two lines of "text"
    x.fillRect(px + 1, py + 6, 4, 1);
  }

  // A landmark's folder: its files' colour on the tab, and how many it holds.
  function drawFolder(x, t, px, py, color, count) {
    px = Math.round(px);
    py = Math.round(py);
    x.fillStyle = color;
    x.fillRect(px, py, 5, 2);
    x.fillStyle = "#d9b36c";
    x.fillRect(px, py + 2, 13, 9);
    t.fillStyle = "#4a3020";
    pixelText(t, count, px + 6.5, py + 9, 0.7);
  }

  function drawPost(x, t, px, label, floor = 48, size = 0.6) {
    px = Math.round(px);
    const wide = Math.max(20, Math.ceil(label.length * 6 * size) + 4);   // the board fits its label
    x.fillStyle = "#8a6f55";
    x.fillRect(px + Math.round(wide / 2) - 1, floor - 18, 2, 19);
    x.fillRect(px, floor - 24, wide, 8);
    t.fillStyle = "#ffffff";
    pixelText(t, label, px + wide / 2, floor - 18, size);
  }

  function runner(text) {
    const RW = 160, RH = 56, FLOOR = 48, PACE = 40, RUN_PACE = 50, WALK = 70, PX_PER_M = 10;
    const say = typeof text === "function" ? text : () => text;
    const id = (runners += 1);
    const c = document.createElement("canvas");
    c.className = "runner";
    c.width = RW;
    c.height = RH;
    c.tabIndex = 0;
    c.setAttribute("aria-label", `${say()}. Left and Right arrows: walk. Space: jump. Down arrow: duck.`);
    const x = c.getContext("2d");
    x.imageSmoothingEnabled = false;
    const words = textLayer(c);
    const screen = document.createElement("div");
    screen.className = "runner-screen";
    screen.append(c, words.node);
    const line = document.createElement("p");
    line.className = "run-line";
    const counter = tally();
    const hint = document.createElement("p");
    hint.className = "explain";
    hint.textContent = "Left and Right arrows: walk. Space or tap: jump. Down arrow: duck.";
    const wrap = document.createElement("div");
    wrap.className = "runner-box";
    wrap.append(screen, line, counter, hint);

    const me = { x: 22, y: FLOOR, vy: 0, ducking: false, left: false, right: false, facing: 1 };
    let files = [], posts = [], pops = [], spawnIn = 0.3, travelled = 0, stride = 0, flash = 0;
    let last = 0, seen = false, frames = 0, said = "";
    const gameOpen = () => Boolean(box && box.isConnected);   // LlamaGame on top: the llama waits
    const jump = () => { if (me.y >= FLOOR) { me.vy = -130; me.ducking = false; } };
    const keys = {
      jump: [" ", "ArrowUp", "w", "W"], duck: ["ArrowDown", "s", "S"],
      left: ["ArrowLeft", "a", "A"], right: ["ArrowRight", "d", "D"],
    };
    const onKey = (ev) => {
      if ((ev.target !== c && ev.target !== document.body) || gameOpen()) return;
      if (keys.jump.includes(ev.key)) { ev.preventDefault(); jump(); }
      else if (keys.duck.includes(ev.key)) { ev.preventDefault(); me.ducking = me.y >= FLOOR; }
      else if (keys.left.includes(ev.key)) { ev.preventDefault(); me.left = true; }
      else if (keys.right.includes(ev.key)) { ev.preventDefault(); me.right = true; }
    };
    const onKeyUp = (ev) => {
      if (keys.duck.includes(ev.key)) me.ducking = false;
      if (keys.left.includes(ev.key)) me.left = false;
      if (keys.right.includes(ev.key)) me.right = false;
    };
    c.addEventListener("pointerdown", (ev) => { ev.preventDefault(); c.focus({ preventScroll: true }); jump(); });
    window.addEventListener("keydown", onKey);
    window.addEventListener("keyup", onKeyUp);

    // The longest run is saved at each landmark and when the wait ends, not every metre.
    const noteRun = () => {
      const metres = Math.floor(wait.metres);
      if (metres > runBest) { runBest = metres; keepRecord(); }
    };
    const s = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
    const tell = () => {
      const run = wait.waited >= RUN_AFTER;
      const metres = Math.floor(wait.metres);
      const text = run
        ? `LlamaRun: ${metres} m · ${s(wait.marks, "landmark")} · next at ${wait.next} m · ` +
          `this wait: ${s(wait.caught, "file")} · longest run: ${Math.max(runBest, metres)} m`
        : `This wait: ${s(wait.caught, "file")} · LlamaRun in ${Math.ceil(RUN_AFTER - wait.waited)} s` +
          (runBest ? ` · longest run: ${runBest} m` : "");
      if (text !== said) line.textContent = said = text;
    };

    const tick = (now) => {
      frames += 1;
      if (!c.isConnected) {
        // Not on the page yet, or gone: wait a moment for it, then stop listening.
        if (seen || frames > 120) {
          window.removeEventListener("keydown", onKey);
          window.removeEventListener("keyup", onKeyUp);
          if (seen && wait.owner === id) { wait.ended = now; noteRun(); }
          return;
        }
        requestAnimationFrame(tick);
        return;
      }
      if (!c.getClientRects().length) {                // hidden: the wait is not counted
        last = 0;
        requestAnimationFrame(tick);
        return;
      }
      if (!seen) {
        seen = true;
        // Straight after another wait (within 3 seconds): the same wait, the same run.
        if (!wait || (wait.ended && now - wait.ended > 3000)) {
          wait = { waited: 0, metres: 0, caught: 0, marks: 0, next: MARK_EVERY, x: 22 };
        }
        wait.owner = id;
        wait.ended = 0;
        me.x = wait.x;
      }
      const paused = gameOpen() || wait.owner !== id;
      const dt = last && !paused ? Math.min(0.05, (now - last) / 1000) : 0;
      last = now;
      const wasRun = wait.waited >= RUN_AFTER;
      wait.waited += dt;
      const run = wait.waited >= RUN_AFTER;
      if (run && !wasRun) flash = 2;
      flash = Math.max(0, flash - dt);
      const still = reduced();                           // nothing drifts; the llama still walks
      const pace = still || paused ? 0 : run ? RUN_PACE : PACE;
      const walk = paused ? 0 : (me.right ? 1 : 0) - (me.left ? 1 : 0);
      if (walk) me.facing = walk;
      me.x = Math.max(2, Math.min(RW - 18, me.x + walk * WALK * dt));
      wait.x = me.x;
      travelled += pace * dt;
      stride += (pace + Math.abs(walk) * WALK) * dt;
      if (run) wait.metres += (RUN_PACE * dt) / PX_PER_M;
      me.vy += 420 * dt;
      me.y = Math.min(FLOOR, me.y + me.vy * dt);
      if (me.y >= FLOOR) me.vy = 0;
      if (me.y < FLOOR) me.ducking = false;

      // Files: some on the ground, some only reached by jumping; on a LlamaRun, Markdown too.
      spawnIn -= dt;
      if (spawnIn <= 0 && files.length < 4) {
        const kind = run && Math.random() < 0.2 ? MD : FILE_KINDS[Math.floor(Math.random() * FILE_KINDS.length)];
        const high = Math.random() < 0.45;
        files.push({ kind, count: 1, born: now, w: 7, h: 9,
                     x: still ? 20 + Math.random() * (RW - 40) : RW + 2,
                     y: high ? FLOOR - 32 + Math.round(Math.random() * 4) : FLOOR - 10 - Math.round(Math.random() * 3) });
        spawnIn = 0.7 + Math.random() * 0.9;
      }
      // A landmark: its signpost, then a folder of files on the ground, more at each one.
      if (run && wait.metres >= wait.next) {
        wait.marks += 1;
        const kind = Math.random() < 0.35 ? MD : FILE_KINDS[Math.floor(Math.random() * FILE_KINDS.length)];
        posts.push({ label: `${wait.next} m`, x: still ? RW / 2 - 30 : RW + 2, born: now });
        files.push({ kind, count: Math.min(12, 2 + wait.marks), born: now, w: 13, h: 11,
                     x: still ? RW / 2 : RW + 26, y: FLOOR - 10 });
        wait.next += MARK_EVERY;
        noteRun();
      }
      const body = me.ducking ? { x: me.x, y: me.y - 9, w: 18, h: 9 } : { x: me.x + 1, y: me.y - 16, w: 13, h: 16 };
      for (const f of files) {
        f.x -= pace * dt;
        if (!paused && body.x < f.x + f.w && body.x + body.w > f.x && body.y < f.y + f.h && body.y + body.h > f.y) {
          f.gone = true;
          collect(f.kind, f.count);
          wait.caught += f.count;
          pops.push({ x: f.x, y: f.y, t: 0, text: `+${f.count} ${f.kind.label}`, color: f.kind.color });
        }
      }
      for (const p of posts) p.x -= pace * dt;
      const fresh = (o) => !still || now - o.born < 6000;
      files = files.filter((f) => !f.gone && f.x > -14 && fresh(f));
      posts = posts.filter((p) => p.x > -22 && fresh(p));
      pops = pops.filter((p) => (p.t += dt) < 0.9);

      const t = words.begin();
      x.fillStyle = "#eef3f7";
      x.fillRect(0, 0, RW, RH);
      x.fillStyle = "#d5dfe8";
      const drift = (travelled * 0.25) % 40;
      for (let sx = -drift; sx < RW; sx += 40) { x.fillRect(sx, 16, 22, 30); x.fillRect(sx + 25, 26, 10, 20); }
      t.fillStyle = "#3f5670";
      const dots = still ? 3 : 1 + Math.floor(now / 400) % 3;
      pixelText(t, say().replace(/[.…]+$/, "") + ".".repeat(dots), RW / 2 + 12, 10, 0.9);
      if (run) {
        pixelText(t, `LlamaRun ${Math.floor(wait.metres)} m`, 3, 20, 0.7, "left");
        pixelText(t, `next ${wait.next} m`, RW - 3, 20, 0.7, "right");
      }
      x.fillStyle = "#8a6f55";
      x.fillRect(0, FLOOR + 1, RW, 1);
      x.fillStyle = "#c7b299";
      for (let sx = -(travelled % 12); sx < RW; sx += 12) x.fillRect(sx, FLOOR + 4, 5, 1);
      for (const p of posts) drawPost(x, t, p.x, p.label);
      for (const f of files) {
        if (f.count > 1) drawFolder(x, t, f.x, f.y - 1, f.kind.color, f.count);
        else drawFile(x, f.x, f.y, f.kind.color);
      }

      const moving = pace || walk;
      const pose = me.ducking ? "duck" : me.y < FLOOR || !moving ? "run1"
        : (Math.floor(stride / 9) % 2 ? "run1" : "run2");
      const img = sprite(pose);
      const top = Math.round(me.y - img.height + 1);
      if (me.facing < 0) {
        x.save();
        x.scale(-1, 1);
        x.drawImage(img, -Math.round(me.x) - img.width, top);
        x.restore();
      } else {
        x.drawImage(img, Math.round(me.x), top);
      }
      for (const p of pops) {
        t.fillStyle = p.color;
        pixelText(t, p.text, p.x + 3, p.y - 2 - p.t * 14, 0.7);
      }
      const banner = gameOpen() ? "Paused while LlamaGame is open" : flash ? "LlamaRun! Folders of files ahead" : "";
      if (banner) {
        x.fillStyle = "rgba(20, 30, 45, 0.78)";
        x.fillRect(0, 22, RW, 13);
        t.fillStyle = "#ffffff";
        pixelText(t, banner, RW / 2, 31, 0.7);
      }
      tell();
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    return wrap;
  }

  // --- what the page tells it ---------------------------------------------------------------
  // Opened from the header with nothing converting: no bar, no progress line.
  function idle() {
    if (!box) return;
    bar.hidden = true;
    label.textContent = "";
  }

  function progress(fraction, text) {
    if (!box) return;
    bar.hidden = false;
    if (fraction === null) bar.removeAttribute("value");
    else bar.value = Math.max(0, Math.min(1, fraction));
    label.textContent = text;
  }

  function finish(text, onOpen) {
    if (!box || !box.isConnected) return;
    state = "done";                              // stops the game where it is
    bar.value = 1;
    bannerText.textContent = text;
    banner.replaceChildren(bannerText);
    if (onOpen) {
      const go = document.createElement("button");
      go.type = "button";
      go.className = "primary";
      go.textContent = "Open it";
      go.addEventListener("click", () => { closeGame(); onOpen(); });
      banner.append(go);
    }
    banner.hidden = false;
    draw();
  }

  return { open, close: closeGame, idle, progress, finish, runner, setRecord,
           isOpen: () => Boolean(box && box.isConnected) };
})();
