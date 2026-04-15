# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

This repo produces **standalone CLI executables** for the Xpoz service, built with PyInstaller. The end goal is per-platform binaries (Windows, Linux x64, Linux arm64, macOS) distributed through native package managers (apt, Homebrew, winget, etc.). The repo therefore holds both:

1. The CLI source (`xpoz_cli.py`), and
2. The build/packaging tooling for each target platform (to be added — currently only an ad-hoc Linux x64 binary exists in `dist/`).

When adding features, keep the runtime dependency surface minimal: the only third-party import allowed is `xpoz` itself. Everything else must be stdlib so PyInstaller output stays small and reproducible across targets.

## Upstream SDK

This CLI wraps the Xpoz Python SDK: https://github.com/XPOZpublic/xpoz-python-sdk (`pip install xpoz`). When SDK behavior is unclear, read that repo — this CLI adds no logic of its own beyond argparse generation and result rendering.

## Repository layout

Currently a single-file project: `xpoz_cli.py` is the entire source. `dist/xpoz-cli` is a PyInstaller-built Linux x64 binary (not checked into a package manager yet). Build scripts, CI workflows for cross-platform builds, and packaging manifests (Homebrew formula, winget manifest, .deb control files, etc.) are expected to land here as the project grows.

## Run / build

```bash
# Run from source (requires: pip install xpoz)
python3 xpoz_cli.py <platform> <method> [--arg value ...]

# Rebuild the standalone binary
pyinstaller --onefile --name xpoz-cli xpoz_cli.py
```

Auth is via `--api-key` or `XPOZ_API_KEY`; optional `--server-url` / `XPOZ_SERVER_URL` overrides the MCP server.

## Architecture

The CLI is a **dynamic reflection wrapper** around the `xpoz` Python SDK. It does not hardcode subcommands — it introspects the SDK's namespace classes at startup and generates an argparse tree from them. Understanding this is essential before editing:

- `PLATFORMS` maps each CLI platform name to an SDK namespace class (`TwitterNamespace`, `InstagramNamespace`, `RedditNamespace`, `TiktokNamespace`, `TrackingNamespace`). Adding a platform = adding an entry here.
- `build_parser()` walks `dir(ns_cls)` for each namespace and calls `_add_method()` for every public callable. Every SDK method becomes a subcommand automatically — no manual registration.
- `_add_param()` converts a Python parameter's type hint into an argparse argument: `Enum` → `choices`, `bool` → `store_true` (with `default=None` so "not set" is distinguishable from "False"), `list[...]` → `nargs="+"`, `int`/`float`/`str` → typed scalar. Underscores in parameter names become dashes in flags.
- At invocation, `_collect_kwargs()` rebuilds the kwargs dict from the parsed `Namespace`, deliberately **dropping `None` and `False`** so the SDK sees only explicitly-set arguments (this is why bool defaults must be `None`, not `False`).
- `_coerce_enums()` converts the `--response-type` string back into the SDK's `ResponseType` enum before the call.
- `_render_result()` handles four result shapes the SDK can return: CSV export shortcut (`--export-csv-url`), paginated walk (`--all-pages` + optional `--max-pages`), jump-to-page (`--page N`), and plain `PaginatedResult` (data + pagination metadata). Non-paginated results fall through `_dump()`, which unwraps pydantic models via `model_dump(mode="json")`.
- `_flatten_error()` exists because the SDK raises `BaseExceptionGroup` (anyio/taskgroup), which must be walked recursively to produce readable single-line error output.

## Things that look like bugs but aren't

- `_add_param` silently swallows `argparse.ArgumentError` on duplicate flags — this is intentional because different SDK methods can share parameter names and argparse will complain on the second `add_argument` call within the same subparser only if truly duplicated.
- Bool args default to `None` (not `False`) so `_collect_kwargs` can tell the user never passed the flag vs. passed it explicitly — don't "fix" this.
- `_collect_kwargs` drops `False` values for the same reason: the SDK's own defaults should win when the user didn't pass the flag.

## Editing guidance

Because the CLI surface is generated from the installed SDK, behavior changes between SDK versions without any code change here. If a subcommand disappears or a flag changes type, look at the installed `xpoz` package first, not this file.
