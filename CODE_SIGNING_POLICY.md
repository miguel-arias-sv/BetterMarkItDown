# Code signing policy

Free code signing provided by [SignPath.io](https://about.signpath.io/), certificate by
[SignPath Foundation](https://signpath.org/).

> **Status:** applied for. Until the application is accepted, releases are not signed, and
> Windows SmartScreen warns about the installer (the [README](README.md#install) says what to
> do). This page will say from which version on releases are signed.

## What is signed

Only the Windows installer, `BetterMarkItDown-Setup-<version>.exe`, attached to the
[GitHub Releases](https://github.com/miguel-arias-sv/BetterMarkItDown/releases) of this
repository. It is built by the [release workflow](.github/workflows/release.yml) on
GitHub-hosted machines, from the source of the tagged version, and nowhere else: no release
binary is ever built on a personal computer. Every signing request is approved by hand.

Not signed: the Python package (`.whl`), which is not a program; and the
`bettermarkitdown.exe` commands that the installer's copy of
[uv](https://github.com/astral-sh/uv) creates on the person's own computer during setup.

The installer's file details name the product **BetterMarkItDown** and give the release's
version. A signed installer shows **SignPath Foundation** as its publisher.

## Team roles

The project currently has a single maintainer, who holds every role:

| Role | Who | What it means |
|---|---|---|
| Committers and reviewers | [Miguel Arias](https://github.com/miguel-arias-sv) | May change the source without further review; reviews every contribution from anyone else (pull requests, see [CONTRIBUTING.md](CONTRIBUTING.md)) before it is merged |
| Approvers | [Miguel Arias](https://github.com/miguel-arias-sv) | Approves each signing request, by hand, for every release |

Build scripts and CI configuration (`.github/`, `installer/`) are source code too: they are
reviewed the same way, and [CODEOWNERS](.github/CODEOWNERS) requires the maintainer's review
for them. Every team member uses multi-factor authentication for GitHub and for SignPath.
This page is updated whenever the team changes.

## Privacy

This program will not transfer any information to other networked systems unless
specifically requested by the user or the person installing or operating it.

In practice, that means: page images and pictures from a document go only to the online AI
service the person has chosen and set up with their own key, and only when they convert;
with a model on their own computer, or text only, nothing leaves it. During setup, the
installer downloads Python and the program's libraries, which the person asks for by
running it. The program sends no usage statistics, no crash reports and no update checks.
The full details, including the third-party services involved, are in
[PRIVACY.md](PRIVACY.md).
