#!/usr/bin/env python3
"""Print a blank .env template, generated from config.py.

WHY GENERATED AND NOT STORED. A checked-in `.env.example` carried a real Gemini API
key and secret from the brain commit until 2026-08-05 — tracked, pushed, and left in
git history (STATE §4.18). It was invisible because a template is a file nobody reads
the values of, and because I allow-listed it in .gitignore without opening it.

A template that is PRINTED cannot hold a secret. Every value here is empty by
construction: there is nowhere for one to be pasted and committed. The defaults live
in config.py, which is where they were always authoritative anyway.

    python3 scripts/env_template.py            # print
    python3 scripts/env_template.py > .env     # create (never overwrites via setup.sh)
"""
from __future__ import annotations

import ast
import pathlib
import sys

CONFIG = pathlib.Path(__file__).resolve().parents[1] / "engine" / "ai_investing" / "config.py"

# EVERY LINE IS COMMENTED OUT. Two reasons, both learned by getting it wrong:
#
#  1. An EMPTY assignment is worse than an absent one. `APPROVAL_TTL_HOURS=` makes
#     _get return "", and config.py does float(_get(...)) — so the engine died with
#     `could not convert string to float: ''` on a template that looked fine. A
#     commented line falls through to the real default in config.py.
#  2. A commented template cannot carry a secret into a shell that sources it.
#
# So this documents the whole configuration surface while setting nothing.


PKG = CONFIG.parent


def _from_config() -> dict[str, str]:
    """{variable: default} for everything config.py reads, in declaration order.

    The default is captured so the template can SHOW it without SETTING it — the
    documentation value without the failure mode.
    """
    tree = ast.parse(CONFIG.read_text())
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in ("_get", "_get_bool", "_get_int", "_get_float",
                                     "_get_list")
                and node.args and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            n = node.args[0].value
            if n in found:
                continue
            d = ""
            if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                v = node.args[1].value
                d = "" if v is None else ("true" if v is True else
                                          "false" if v is False else str(v))
            found[n] = d
    return found


def _from_os_environ() -> list[str]:
    """Variables read straight from os.environ anywhere in the package.

    Not optional: the BROKER CREDENTIALS live here, not in config.py —
    `os.environ["LONGPORT_APP_KEY"]` in brokers/live.py, and
    `os.environ.get(f"{prefix}KEY")` for the crypto keys. A template generated only
    from config.py would omit every credential a live setup needs, which is the
    quiet kind of wrong: it looks complete.
    """
    names: list[str] = []
    for path in sorted(PKG.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            key = None
            # os.environ["X"]
            if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute)
                    and node.value.attr == "environ"
                    and isinstance(node.slice, ast.Constant)
                    and isinstance(node.slice.value, str)):
                key = node.slice.value
            # os.environ.get("X", ...)
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and node.func.attr == "get"
                  and isinstance(node.func.value, ast.Attribute)
                  and node.func.value.attr == "environ"
                  and node.args and isinstance(node.args[0], ast.Constant)
                  and isinstance(node.args[0].value, str)):
                key = node.args[0].value
            if key and key.isupper() and key not in names:
                names.append(key)
    return names


# Credentials the crypto adapter builds by string concatenation
# (`os.environ.get(f"{prefix}KEY")`), so no AST literal exists to find.
_CONCATENATED = [
    "CRYPTO_API_KEY_NAME", "CRYPTO_API_KEY", "CRYPTO_API_SECRET", "CRYPTO_API_PASSWORD",
    "CRYPTO_SANDBOX_API_KEY_NAME", "CRYPTO_SANDBOX_API_KEY",
    "CRYPTO_SANDBOX_API_SECRET", "CRYPTO_SANDBOX_API_PASSWORD",
]


def env_names() -> dict[str, str]:
    """{variable: default}. Credentials read straight from os.environ have no
    literal default, so they render blank — which is correct for a secret."""
    found = _from_config()
    for n in _from_os_environ() + _CONCATENATED:
        found.setdefault(n, "")
    return found


def render() -> str:
    out = [
        "# AI-Investing configuration — GENERATED, do not commit a filled copy.",
        "#",
        "# Regenerate:  python3 scripts/env_template.py",
        "# Every line is commented out, so this sets nothing and cannot break the",
        "# engine. Uncomment only what you need. Not tracked in git, so a real value",
        "# can never be committed to it again (see STATE_OF_THE_SYSTEM.md §4.18).",
        "#",
        "# Paper mode runs with no keys at all. Defaults for anything omitted are in",
        "# engine/ai_investing/config.py, which is authoritative.",
        "",
    ]
    for n, default in env_names().items():
        out.append(f"# {n}={default}")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    sys.stdout.write(render())
