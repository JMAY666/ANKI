"""Check that a static SvelteKit fallback and its reachable modules agree."""

import re
import sys
from pathlib import Path


def verify(root: Path) -> int:
    root = root.resolve()
    page = (root / "index.html").read_text(encoding="utf8")
    expected = set(re.findall(r"__sveltekit_[a-z0-9]+", page))
    if len(expected) != 1:
        raise ValueError("Static HTML has no unique SvelteKit runtime identifier")
    pending = [root / value for value in re.findall(r"_app/[A-Za-z0-9/_.-]+\.mjs", page)]
    if not pending:
        raise ValueError("Static HTML has no client entry modules")
    visited = set()
    observed = set()
    while pending:
        path = pending.pop().resolve()
        if path in visited:
            continue
        if not path.is_relative_to(root):
            raise ValueError("Client import escapes the static asset directory")
        visited.add(path)
        text = path.read_text(encoding="utf8")
        observed.update(re.findall(r"globalThis\.(__sveltekit_[a-z0-9]+)", text))
        for relative in re.findall(r'''(?:from|import)\s*(?:\(\s*)?["']([^"']+)["']''', text):
            if relative.startswith(".") and relative.endswith((".mjs", ".js")):
                pending.append(path.parent / relative)
    if observed != expected:
        raise ValueError(f"HTML/client runtime mismatch: {expected} != {observed}")
    return len(visited)


if __name__ == "__main__":
    print("Verified reachable client modules:", verify(Path(sys.argv[1])))
