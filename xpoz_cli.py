#!/usr/bin/env python3
"""
xpoz-cli — standalone CLI wrapper around the xpoz Python SDK.

Only external dependency: the `xpoz` package itself (pip install xpoz).
All other functionality uses the Python stdlib.

Platform namespaces and their methods are discovered dynamically from the
installed SDK, so every method the SDK exposes becomes a CLI subcommand
automatically.

Usage:
    xpoz_cli.py [global-opts] <platform> <method> [--arg value ...]

Platforms:
    twitter | instagram | reddit | tiktok

Discovery:
    xpoz_cli.py --help
    xpoz_cli.py twitter --help
    xpoz_cli.py twitter search_posts --help

Examples:
    xpoz_cli.py twitter get_user --identifier elonmusk
    xpoz_cli.py twitter search_posts --query '"AI" AND ethics' \
        --start-date 2025-01-01 --limit 20 --fields id text like_count
    xpoz_cli.py reddit search_posts --query "python tutorial" \
        --subreddit learnpython --sort top --time month --all-pages
    xpoz_cli.py twitter search_posts --query bitcoin \
        --response-type csv --export-csv-url

Auth:
    --api-key KEY   (or env: XPOZ_API_KEY)
    --server-url U  (or env: XPOZ_SERVER_URL)
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import re
import sys
import types
import typing
from enum import Enum

try:
    from xpoz import XpozClient, ResponseType  # type: ignore
    from xpoz.namespaces import (  # type: ignore
        TwitterNamespace,
        InstagramNamespace,
        RedditNamespace,
        TiktokNamespace,
        TrackingNamespace,
    )
except ImportError as _e:
    sys.stderr.write(f"xpoz SDK import failed: {_e}\nRun: pip install xpoz\n")
    sys.exit(2)

PLATFORMS: dict = {
    "twitter": TwitterNamespace,
    "instagram": InstagramNamespace,
    "reddit": RedditNamespace,
    "tiktok": TiktokNamespace,
    "tracking": TrackingNamespace,
}


# ---------- typing helpers ----------

def _unwrap_optional(ann):
    origin = typing.get_origin(ann)
    if origin is typing.Union or origin is types.UnionType:
        args = [a for a in typing.get_args(ann) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return ann


def _is_list(ann):
    base = _unwrap_optional(ann)
    return typing.get_origin(base) in (list, typing.List)  # noqa: UP006


def _first_doc_line(obj) -> str:
    doc = inspect.getdoc(obj) or ""
    return doc.strip().split("\n", 1)[0]


# ---------- example synthesis ----------

_DOC_SECTION_RE = re.compile(
    r"^\s*(Args|Arguments|Parameters|Returns?|Raises|Yields|Examples?|Notes?|See Also)\s*:\s*$"
)


def _extract_doc_examples(obj) -> str:
    """Pull an 'Examples:' block out of a docstring, if present."""
    doc = inspect.getdoc(obj) or ""
    lines = doc.splitlines()
    start = None
    for i, line in enumerate(lines):
        m = _DOC_SECTION_RE.match(line)
        if m and m.group(1).lower().startswith("example"):
            start = i + 1
            break
    if start is None:
        return ""
    end = len(lines)
    for j in range(start, len(lines)):
        m = _DOC_SECTION_RE.match(lines[j])
        if m and not m.group(1).lower().startswith("example"):
            end = j
            break
    block = "\n".join(lines[start:end]).strip("\n")
    if not block.strip():
        return ""
    # Strip common leading whitespace so output isn't doubly indented.
    return inspect.cleandoc(block)


def _placeholder(name: str, ann) -> str:
    base = _unwrap_optional(ann)
    if inspect.isclass(base) and issubclass(base, Enum):
        first = next(iter(base), None)
        return first.name.lower() if first else "VALUE"
    if base is bool:
        return ""  # bool flag takes no value
    if _is_list(ann):
        return f"<{name}1> <{name}2>"
    if base is int:
        return "<N>"
    if base is float:
        return "<x>"
    return f"<{name}>"


def _synth_example(platform: str, method_name: str, sig: inspect.Signature, hints: dict) -> str:
    """Build a synthesized invocation line from a method's required params."""
    parts = [f"xpoz-cli {platform} {method_name}"]
    for pname, param in sig.parameters.items():
        if pname == "self":
            continue
        if param.default is not inspect.Parameter.empty:
            continue  # skip optional — keep the example minimal
        ann = hints.get(pname, str)
        flag = f"--{pname.replace('_', '-')}"
        ph = _placeholder(pname, ann)
        parts.append(f"{flag} {ph}".rstrip())
    return " ".join(parts)


def _build_method_epilog(platform: str, method_name: str, method, sig: inspect.Signature, hints: dict) -> str:
    synth = _synth_example(platform, method_name, sig, hints)
    doc_examples = _extract_doc_examples(method)
    blocks = [f"Examples:\n  {synth}"]
    if doc_examples:
        indented = "\n".join("  " + ln if ln else "" for ln in doc_examples.splitlines())
        blocks.append(f"From SDK docstring:\n{indented}")
    return "\n\n".join(blocks)


def _build_platform_epilog(platform: str, ns_cls) -> str:
    """Synthesize up to 2 example invocations drawn from the namespace's own methods."""
    examples: list[str] = []
    for mname in sorted(dir(ns_cls)):
        if mname.startswith("_") or len(examples) >= 2:
            continue
        method = getattr(ns_cls, mname)
        if not callable(method):
            continue
        try:
            sig = inspect.signature(method)
            hints = typing.get_type_hints(method)
        except Exception:
            continue
        examples.append("  " + _synth_example(platform, mname, sig, hints))
    if not examples:
        return ""
    return "Examples:\n" + "\n".join(examples) + "\n\nRun `xpoz-cli " + platform + " <method> --help` for per-method details."


# ---------- argparse construction ----------

def _add_param(parser: argparse.ArgumentParser, name: str, param, hints: dict) -> None:
    ann = hints.get(name, str)
    base = _unwrap_optional(ann)
    required = param.default is inspect.Parameter.empty
    flag = f"--{name.replace('_', '-')}"
    kwargs: dict = {"dest": name}

    if inspect.isclass(base) and issubclass(base, Enum):
        kwargs["choices"] = [e.name.lower() for e in base]
        kwargs["type"] = str
        if required:
            kwargs["required"] = True
    elif base is bool:
        kwargs["action"] = "store_true"
        kwargs["default"] = None  # None = "not set"
    elif _is_list(ann):
        kwargs["nargs"] = "+"
        if required:
            kwargs["required"] = True
    elif base is int:
        kwargs["type"] = int
        if required:
            kwargs["required"] = True
    elif base is float:
        kwargs["type"] = float
        if required:
            kwargs["required"] = True
    else:
        kwargs["type"] = str
        if required:
            kwargs["required"] = True

    if not required and param.default not in (inspect.Parameter.empty, None):
        kwargs["help"] = f"(default: {param.default!r})"

    try:
        parser.add_argument(flag, **kwargs)
    except argparse.ArgumentError:
        pass  # duplicate or unsupported — skip silently


def _add_method(sub, platform: str, name: str, method) -> None:
    try:
        sig = inspect.signature(method)
    except (TypeError, ValueError):
        return
    try:
        hints = typing.get_type_hints(method)
    except Exception:
        hints = {}

    p = sub.add_parser(
        name,
        help=_first_doc_line(method) or None,
        epilog=_build_method_epilog(platform, name, method, sig, hints),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    for pname, param in sig.parameters.items():
        if pname == "self":
            continue
        _add_param(p, pname, param, hints)
    p.set_defaults(_platform=platform, _method=name)


_TOP_LEVEL_EPILOG = """\
Examples:
  xpoz-cli twitter get_user --identifier elonmusk
  xpoz-cli twitter search_posts --query bitcoin --limit 20 --all-pages
  xpoz-cli reddit search_posts --query "python tutorial" --subreddit learnpython
  xpoz-cli twitter search_posts --query bitcoin --export-csv-url

Auth:
  --api-key KEY    (or env XPOZ_API_KEY)
  --server-url URL (or env XPOZ_SERVER_URL)

Discovery:
  xpoz-cli <platform> --help
  xpoz-cli <platform> <method> --help
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xpoz-cli",
        description="Standalone CLI wrapper around the xpoz Python SDK.",
        epilog=_TOP_LEVEL_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--api-key", help="Xpoz API key (or env XPOZ_API_KEY)")
    parser.add_argument("--server-url", help="Custom MCP server URL")
    parser.add_argument("--timeout", type=int, default=300, help="Operation timeout seconds (default 300)")
    parser.add_argument("--output", choices=["json", "pretty"], default="json")
    parser.add_argument("--all-pages", action="store_true",
                        help="Paginated results: walk every page and concatenate .data")
    parser.add_argument("--max-pages", type=int, default=None,
                        help="Cap for --all-pages (safety limit)")
    parser.add_argument("--page", type=int, default=None,
                        help="Paginated results: jump to this page number")
    parser.add_argument("--export-csv-url", action="store_true",
                        help="Call .export_csv() on the result and print the download URL")

    plat_sub = parser.add_subparsers(dest="platform", required=True, metavar="PLATFORM")
    for platform, ns_cls in PLATFORMS.items():
        pparser = plat_sub.add_parser(
            platform,
            help=f"{platform} methods",
            epilog=_build_platform_epilog(platform, ns_cls),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        msub = pparser.add_subparsers(dest="method", required=True, metavar="METHOD")
        for mname in sorted(dir(ns_cls)):
            if mname.startswith("_"):
                continue
            method = getattr(ns_cls, mname)
            if not callable(method):
                continue
            _add_method(msub, platform, mname, method)
    return parser


# ---------- invocation ----------

def _collect_kwargs(args: argparse.Namespace, sig: inspect.Signature) -> dict:
    out: dict = {}
    for pname, param in sig.parameters.items():
        if pname == "self":
            continue
        if not hasattr(args, pname):
            continue
        val = getattr(args, pname)
        if val is None:
            continue
        if isinstance(val, bool) and val is False:
            continue
        out[pname] = val
    return out


def _flatten_error(exc: BaseException) -> str:
    parts: list[str] = []
    seen: set[int] = set()

    def visit(e: BaseException) -> None:
        if id(e) in seen:
            return
        seen.add(id(e))
        if isinstance(e, BaseExceptionGroup):
            for sub in e.exceptions:
                visit(sub)
            return
        parts.append(f"{type(e).__name__}: {e}")

    visit(exc)
    return " | ".join(parts) if parts else f"{type(exc).__name__}: {exc}"


def _coerce_enums(kwargs: dict) -> None:
    if "response_type" in kwargs and isinstance(kwargs["response_type"], str):
        key = kwargs["response_type"].upper()
        if key in ResponseType.__members__:
            kwargs["response_type"] = ResponseType[key]


def _dump(obj):
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(mode="json")
        except Exception:
            return obj.model_dump()
    if isinstance(obj, dict):
        return {k: _dump(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_dump(x) for x in obj]
    if isinstance(obj, Enum):
        return obj.value
    return str(obj)


def _render_result(result, args) -> dict | list | str:
    # CSV export shortcut
    if args.export_csv_url and hasattr(result, "export_csv"):
        return {"csv_url": result.export_csv()}

    # Jump to a specific page
    if args.page is not None and hasattr(result, "get_page"):
        result = result.get_page(args.page)

    # Walk all pages
    if args.all_pages and hasattr(result, "data") and hasattr(result, "has_next_page"):
        items = list(result.data)
        fetched = 1
        cur = result
        while cur.has_next_page():
            if args.max_pages and fetched >= args.max_pages:
                break
            cur = cur.next_page()
            items.extend(cur.data)
            fetched += 1
        return {
            "data": [_dump(x) for x in items],
            "pages_fetched": fetched,
            "total_rows": getattr(getattr(result, "pagination", None), "total_rows", None),
        }

    # PaginatedResult → data + pagination metadata
    if hasattr(result, "data") and hasattr(result, "pagination"):
        return {
            "data": [_dump(x) for x in result.data],
            "pagination": _dump(result.pagination) if result.pagination else None,
        }

    return _dump(result)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("XPOZ_API_KEY")
    if not api_key:
        sys.stderr.write("Missing API key. Pass --api-key or set XPOZ_API_KEY.\n")
        sys.exit(2)

    client_kwargs: dict = {"timeout": args.timeout}
    server_url = args.server_url or os.environ.get("XPOZ_SERVER_URL")
    if server_url:
        client_kwargs["server_url"] = server_url

    try:
        client = XpozClient(api_key, **client_kwargs)
    except BaseException as e:
        sys.stderr.write(f"Failed to connect to Xpoz: {_flatten_error(e)}\n")
        sys.exit(1)

    try:
        ns = getattr(client, args.platform)
        method = getattr(ns, args.method)
        sig = inspect.signature(method)
        call_kwargs = _collect_kwargs(args, sig)
        _coerce_enums(call_kwargs)

        try:
            result = method(**call_kwargs)
        except BaseException as e:
            sys.stderr.write(f"{_flatten_error(e)}\n")
            sys.exit(1)

        payload = _render_result(result, args)
    finally:
        try:
            client.close()
        except Exception:
            pass

    indent = 2 if args.output == "pretty" else None
    json.dump(payload, sys.stdout, indent=indent, ensure_ascii=False, default=str)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
