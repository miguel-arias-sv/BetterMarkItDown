// Render formulas with KaTeX and report the ones that fail. Called by mathcheck.py.
//
// stdin:  {"paths": [dirs to look for katex in], "items": [{"id": 0, "tex": "...", "display": true}]}
// stdout: {"version": "0.19.0", "failures": [{"id": 0, "message": "..."}]}
//     or  {"error": "katex not found"} when no search path has katex installed.
"use strict";

let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => { input += chunk; });
process.stdin.on("end", () => {
  const { paths = [], items = [] } = JSON.parse(input);

  let katex;
  try {
    katex = require(require.resolve("katex", { paths: [...paths, process.cwd()] }));
  } catch {
    process.stdout.write(JSON.stringify({ error: "katex not found" }));
    return;
  }

  const failures = [];
  for (const { id, tex, display } of items) {
    try {
      // strict: "ignore" -- unicode or deprecated syntax still renders; only real
      // parse errors (unknown macro, unbalanced braces) count as failures.
      katex.renderToString(tex, { displayMode: display, throwOnError: true, strict: "ignore" });
    } catch (err) {
      failures.push({ id, message: String(err.message || err).split("\n")[0] });
    }
  }
  process.stdout.write(JSON.stringify({ version: katex.version, failures }));
});
