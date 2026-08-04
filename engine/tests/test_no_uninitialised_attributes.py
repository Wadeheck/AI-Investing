"""Static guard against the bug that crash-looped the live engine.

On 2026-08-05 `self._flagged_symbols` was READ in run_cycle() while the line that
initialised it was missing — the patch that added it died before writing the file.
The engine raised AttributeError every cycle, systemd restarted it 18 times, and 27
suites stayed green because none ran the main loop (STATE §4.16).

THE RULE HAD TO BE CHOSEN CAREFULLY. The obvious one — "assigned somewhere in the
class" — does NOT catch it: `_flagged_symbols` is assigned near the END of the same
method that reads it at the start, so it looks assigned and still crashes on the
first pass. The rule that matches the actual failure is stricter:

    an attribute READ by any method must be assigned in __init__

Reads guarded by `getattr(self, "x", default)` are exempt, since those cannot
raise. Across the whole package that leaves zero offenders, so it is enforceable
rather than aspirational.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "ai_investing"
sys.path.insert(0, str(ROOT.parent))


def _is_self_attr(node) -> bool:
    return (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id == "self")


def _assigned(node) -> set[str]:
    """`self.x` names written anywhere under `node`."""
    out: set[str] = set()
    for n in ast.walk(node):
        targets = (n.targets if isinstance(n, ast.Assign)
                   else [n.target] if isinstance(n, (ast.AnnAssign, ast.AugAssign))
                   else [n.target] if isinstance(n, ast.For)
                   else [])
        for t in targets:
            for sub in ast.walk(t):
                if _is_self_attr(sub):
                    out.add(sub.attr)
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "setattr" and len(n.args) >= 2
                and isinstance(n.args[0], ast.Name) and n.args[0].id == "self"
                and isinstance(n.args[1], ast.Constant)):
            out.add(str(n.args[1].value))
    return out


def _getattr_guarded(cls: ast.ClassDef) -> set[str]:
    """Names only ever reached through `getattr(self, "x", default)` cannot raise."""
    out: set[str] = set()
    for n in ast.walk(cls):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "getattr" and len(n.args) >= 3
                and isinstance(n.args[0], ast.Name) and n.args[0].id == "self"
                and isinstance(n.args[1], ast.Constant)):
            out.add(str(n.args[1].value))
    return out


def offenders() -> list[str]:
    found: list[str] = []
    for path in sorted(ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            init = next((f for f in cls.body
                         if isinstance(f, ast.FunctionDef) and f.name == "__init__"), None)
            if init is None:
                continue            # no constructor: nothing to promise
            in_init = _assigned(init)
            methods = {f.name for f in ast.walk(cls)
                       if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))}
            classvars: set[str] = set()
            for stmt in cls.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    classvars.add(stmt.target.id)
                elif isinstance(stmt, ast.Assign):
                    classvars |= {t.id for t in stmt.targets if isinstance(t, ast.Name)}
            read: set[str] = set()
            for f in cls.body:
                if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and f.name != "__init__":
                    for n in ast.walk(f):
                        if _is_self_attr(n) and isinstance(n.ctx, ast.Load):
                            read.add(n.attr)
            missing = read - in_init - methods - classvars - _getattr_guarded(cls)
            for name in sorted(missing):
                found.append(f"{path.relative_to(ROOT.parent)}:{cls.name}.{name}")
    return found


def test_every_attribute_a_method_reads_is_set_in_init():
    found = offenders()
    assert not found, (
        "read by a method but never assigned in __init__ — this is precisely the "
        "AttributeError that crash-looped the engine 18 times:\n  " + "\n  ".join(found))


def test_the_guard_catches_the_bug_that_actually_shipped():
    """A guard nobody has watched fail is a guard nobody should trust. This is the
    real shape: assigned LATE in the same method that reads it early — which the
    obvious 'assigned somewhere' rule waves through."""
    src = ("class C:\n"
           "    def __init__(self):\n"
           "        self.ok = 1\n"
           "    def cycle(self, new):\n"
           "        delta = new - self.flagged\n"   # read...
           "        self.flagged = new\n"           # ...assigned only afterwards
           "        return delta\n")
    cls = ast.parse(src).body[0]
    init = cls.body[0]
    read = {n.attr for f in cls.body[1:] for n in ast.walk(f)
            if _is_self_attr(n) and isinstance(n.ctx, ast.Load)}
    assert "flagged" in read
    assert "flagged" not in _assigned(init), "the whole point: not in __init__"
    assert "flagged" in _assigned(cls), \
        "and it IS assigned in the class — which is why the loose rule missed it"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} attribute-init tests passed.")
