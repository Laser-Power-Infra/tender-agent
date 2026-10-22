"""Self-check for package boundaries: an agent imports only itself + lib, lib never imports agents.

Run: uv run python -m tests.test_boundaries
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def imports(path: Path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            yield from (a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            yield node.module


def violations():
    bad = []
    for path in (ROOT / "agents").rglob("*.py"):
        own = path.relative_to(ROOT / "agents").parts[0]
        for mod in imports(path):
            parts = mod.split(".")
            if parts[0] == "agents" and len(parts) > 1 and parts[1] != own:
                bad.append(f"{path.relative_to(ROOT)} imports {mod}")
    for path in (ROOT / "lib").rglob("*.py"):
        bad += [f"{path.relative_to(ROOT)} imports {m}" for m in imports(path) if m.split(".")[0] == "agents"]
    return bad


def test_boundaries():
    bad = violations()
    assert not bad, "\n".join(bad)


if __name__ == "__main__":
    test_boundaries()
    print("boundaries ok")
