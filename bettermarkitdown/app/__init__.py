"""The setup page in the browser: `bettermarkitdown app`.

The desktop icon (a windowless launcher, see pyproject's gui-scripts) runs
`launch()` too, so the explanation of why a browser opened is also on the page.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
import webbrowser

INTRO = """\
Opening BetterMarkItDown in your web browser.

It runs only on this computer: the page is not a website, and nothing on it is sent
anywhere. Internet is needed during setup and when you use an online AI service;
with a model on this computer it works offline afterwards.

If the browser does not open, paste this address into it:
  {url}

Keep this window open while you use the page. Press Ctrl+C here, or Quit on the
page, to stop.
"""


def launch(argv: list[str] | None = None) -> int:
    from .server import App

    parser = argparse.ArgumentParser(prog="bettermarkitdown app",
                                     description="Open the setup page in your browser.")
    parser.add_argument("--port", type=int, default=0, help="default: any free port")
    parser.add_argument("--no-browser", action="store_true",
                        help="print the address instead of opening a browser")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    app = App(port=args.port)
    print(INTRO.format(url=app.url), flush=True)
    if not args.no_browser:
        webbrowser.open(app.url)
    with contextlib.suppress(KeyboardInterrupt):
        app.serve()
    print("BetterMarkItDown stopped.")
    return 0
