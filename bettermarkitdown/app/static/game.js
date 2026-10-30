// "Play while you wait": a llama hops over stacks of paper, ducks under flying
// staplers and collects loose pages, while a long conversion runs. Opt-in, never
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
    page: [
      "wwwwwg",
      "wllllw",
      "wwwwww",
      "wllllw",
      "wwwwww",
      "wllllw",
      "gwwwwg",
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
  const store = {
    get() { try { return Number(localStorage.getItem("bmid-game-best")) || 0; } catch (_) { return 0; } },
    set(v) { try { localStorage.setItem("bmid-game-best", String(v)); } catch (_) { /* private window */ } },
  };

  // --- state -------------------------------------------------------------------------
  let box = null, canvas, ctx, bar, label, scoreText, banner, bannerText, hint;
  let win = window;                            // the window the game is in (page or pop-out)
  let state = "ready";                         // ready | running | paused | over | done
  let llama, things, speed, distance, pages, best, spawnIn, lastTime, frame, raf;
  let corner = "br";
  let closing = false;                         // Close was pressed in the pop-out window

  function reset() {
    llama = { y: GROUND, vy: 0, ducking: false };
    things = [];
    speed = 55;
    distance = 0;
    pages = 0;
    spawnIn = 1.2;
    best = store.get();
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
    hint = h("p", "game-hint", "Space or tap: jump. Down arrow: duck. P: pause.");
    banner = h("div", "game-banner");
    banner.hidden = true;
    bannerText = h("p", "", "Your file is ready");
    banner.append(bannerText);
    stage.append(bar, label, scoreText, canvas, banner);
    box.append(tools, stage, hint);
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
    if (action === "jump" && llama.y >= GROUND && !llama.ducking) llama.vy = -150;
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
  function spawn() {
    const roll = Math.random();
    if (distance > 400 && roll < 0.28) {
      things.push({ kind: "stapler", x: W + 4, y: GROUND - 18, w: 14, h: 6, vx: 18 });
    } else if (roll < 0.5) {
      things.push({ kind: "page", x: W + 4, y: GROUND - 22 - Math.round(Math.random() * 14), w: 6, h: 7, vx: 0 });
    } else {
      const reams = 1 + Math.floor(Math.random() * Math.min(3, 1 + distance / 500));
      things.push({ kind: "stack", x: W + 4, y: GROUND - reams * 5, w: 10 + Math.round(Math.random() * 4), h: reams * 5, vx: 0 });
    }
    spawnIn = Math.max(0.55, 1.5 - distance / 2500) + Math.random() * 0.7;
  }

  function llamaBox() {
    const tall = llama.ducking ? 10 : 17;
    return { x: 14, y: llama.y - tall + 1, w: llama.ducking ? 18 : 13, h: tall - 2 };
  }

  const hit = (a, b) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;

  function update(dt) {
    speed = Math.min(115, speed + dt * 1.5);
    distance += speed * dt;
    llama.vy += 420 * dt;
    llama.y = Math.min(GROUND, llama.y + llama.vy * dt);
    if (llama.y >= GROUND) llama.vy = 0;
    if (llama.y < GROUND) llama.ducking = false;
    spawnIn -= dt;
    if (spawnIn <= 0) spawn();
    const me = llamaBox();
    for (const t of things) {
      t.x -= (speed + t.vx) * dt;
      if (t.gone || !hit(me, t)) continue;
      if (t.kind === "page") { t.gone = true; pages += 1; continue; }
      state = "over";
      const score = Math.floor(distance / 10) + pages * 10;
      if (score > best) { best = score; store.set(best); }
    }
    things = things.filter((t) => t.x + t.w > -2 && !t.gone);
  }

  function draw() {
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

    for (const t of things) {
      if (t.kind === "page") ctx.drawImage(sprite("page"), Math.round(t.x), Math.round(t.y));
      else if (t.kind === "stapler") ctx.drawImage(sprite("stapler"), Math.round(t.x), Math.round(t.y));
      else {
        for (let i = 0; i < t.h / 5; i++) {
          const y = Math.round(t.y + i * 5);
          ctx.fillStyle = "#ffffff"; ctx.fillRect(Math.round(t.x), y, t.w, 5);
          ctx.fillStyle = "#9db7d6"; ctx.fillRect(Math.round(t.x), y + 4, t.w, 1);
          ctx.fillStyle = "#b8b8b8"; ctx.fillRect(Math.round(t.x) + t.w - 1, y, 1, 5);
        }
      }
    }
    const pose = llama.ducking ? "duck" : (llama.y < GROUND || state !== "running") ? "run1"
      : (Math.floor(distance / 9) % 2 ? "run1" : "run2");
    const img = sprite(pose);
    ctx.drawImage(img, 12, Math.round(llama.y - img.height + 1));

    const score = Math.floor(distance / 10) + pages * 10;
    scoreText.textContent = `Score ${score}  ·  pages ${pages}  ·  best ${best}`;
    ctx.fillStyle = "rgba(20, 30, 45, 0.78)";
    const message = { ready: "Press Space to start", paused: "Paused: Space to go on",
                      over: "Oops! Space to try again" }[state];
    if (message) {
      ctx.fillRect(0, 30, W, 20);
      ctx.fillStyle = "#ffffff";
      ctx.font = "8px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(message, W / 2, 43);
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

  // --- while a screen loads: the same llama, running with nothing in its way ---------------
  // Space, Up or a tap jumps; Down ducks. No obstacles and no score; the message runs
  // behind it. It stops by itself once the screen takes its place.
  function runner(text) {
    const RW = 160, RH = 56, FLOOR = 48, X = 22;
    const c = document.createElement("canvas");
    c.className = "runner";
    c.width = RW;
    c.height = RH;
    c.tabIndex = 0;
    c.setAttribute("aria-label", `${text}. Space: jump, Down arrow: duck.`);
    const x = c.getContext("2d");
    x.imageSmoothingEnabled = false;
    const me = { y: FLOOR, vy: 0, ducking: false };
    let travelled = 0, last = 0, seen = false, frames = 0;
    const jump = () => { if (me.y >= FLOOR) { me.vy = -130; me.ducking = false; } };
    const onKey = (ev) => {
      if (ev.target !== c && ev.target !== document.body) return;
      if ([" ", "ArrowUp"].includes(ev.key)) { ev.preventDefault(); jump(); }
      else if (ev.key === "ArrowDown") { ev.preventDefault(); me.ducking = me.y >= FLOOR; }
    };
    const onKeyUp = (ev) => { if (ev.key === "ArrowDown") me.ducking = false; };
    c.addEventListener("pointerdown", (ev) => { ev.preventDefault(); jump(); });
    window.addEventListener("keydown", onKey);
    window.addEventListener("keyup", onKeyUp);

    const tick = (now) => {
      frames += 1;
      if (!c.isConnected) {
        // Not on the page yet, or gone: wait a moment for it, then stop listening.
        if (seen || frames > 120) {
          window.removeEventListener("keydown", onKey);
          window.removeEventListener("keyup", onKeyUp);
          return;
        }
        requestAnimationFrame(tick);
        return;
      }
      seen = true;
      const dt = last ? Math.min(0.05, (now - last) / 1000) : 0;
      last = now;
      const still = reduced();
      if (!still) travelled += 50 * dt;
      me.vy += 420 * dt;
      me.y = Math.min(FLOOR, me.y + me.vy * dt);
      if (me.y >= FLOOR) me.vy = 0;

      x.fillStyle = "#eef3f7";
      x.fillRect(0, 0, RW, RH);
      x.fillStyle = "#d5dfe8";
      const drift = (travelled * 0.25) % 40;
      for (let sx = -drift; sx < RW; sx += 40) { x.fillRect(sx, 16, 22, 30); x.fillRect(sx + 25, 26, 10, 20); }
      x.fillStyle = "#5b7390";
      x.font = "9px system-ui, sans-serif";
      x.textAlign = "center";
      const dots = still ? 3 : 1 + Math.floor(now / 400) % 3;
      x.fillText(text.replace(/[.…]+$/, "") + ".".repeat(dots), RW / 2 + 12, 14);
      x.fillStyle = "#8a6f55";
      x.fillRect(0, FLOOR + 1, RW, 1);
      x.fillStyle = "#c7b299";
      for (let sx = -(travelled % 12); sx < RW; sx += 12) x.fillRect(sx, FLOOR + 4, 5, 1);
      const pose = me.ducking ? "duck" : me.y < FLOOR || still ? "run1"
        : (Math.floor(travelled / 9) % 2 ? "run1" : "run2");
      const img = sprite(pose);
      x.drawImage(img, X, Math.round(me.y - img.height + 1));
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    return c;
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

  return { open, close: closeGame, idle, progress, finish, runner,
           isOpen: () => Boolean(box && box.isConnected) };
})();
