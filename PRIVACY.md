# Privacy

BetterMarkItDown runs on your own computer. It sends no usage statistics, crash reports or
update checks, and it has no account or server of its own. Information leaves your computer
only in the cases below, each of which you start yourself.

## When you convert with an online AI service

If you choose an online service (Google Gemini, OpenAI, Anthropic, Moonshot Kimi,
OpenRouter, or another server you set up), the pages and pictures that need the AI are sent
to that service, as images, together with the instructions for transcribing them. Pages
with a text layer and no figures are read on your computer and not sent. The service's own
terms and privacy policy then apply; some free tiers (Gemini's, for one) may use what you
send to improve their products. The setup page says so when you choose.

To send nothing: use a model on your own computer (Ollama), or convert text only
(`--no-vision`, or "Text only" on the setup page). Both work offline.

## Your API keys

A key you save is kept in your computer's own password store (Windows Credential Manager,
the macOS Keychain, or the Secret Service on Linux), never in a plain file, and is sent only
to the service it belongs to. The program never shows a key in full.

## Downloads you ask for

- **The Windows installer** downloads Python (from the
  [python-build-standalone](https://github.com/astral-sh/python-build-standalone) releases on
  GitHub) and the program's libraries (from [PyPI](https://pypi.org)), through
  [uv](https://github.com/astral-sh/uv). Those sites see an ordinary download request.
- **A model on your computer**: when you click to install Ollama or download a model, they
  come from Ollama's and Microsoft's (winget) servers.
- **LibreOffice**, for old `.doc` / `.ppt` files: only if you click to install it (winget).

## The setup page

`bettermarkitdown app` opens a page in your browser that is served by the program itself, on
your computer only (127.0.0.1); it is not a website, and no other computer can reach it. Its
files, including the libraries that draw formulas, are part of the program: nothing is
loaded from the internet.

## What stays on your computer

Your library (copies of the files you add, and their work folders) is in
`%LOCALAPPDATA%\BetterMarkItDown` on Windows; your settings are in
`%APPDATA%\BetterMarkItDown`; results go to `Documents\BetterMarkItDown`. Uninstalling asks
whether to delete the library, settings and keys; converted files are never deleted.

## AI agents

If you let an AI agent (Claude Code, Codex, Gemini CLI, Antigravity) use BetterMarkItDown,
the agent's own terms apply to what it reads and does; BetterMarkItDown itself behaves as
described above.

Questions: [open an issue](https://github.com/miguel-arias-sv/BetterMarkItDown/issues).
