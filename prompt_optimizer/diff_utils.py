from __future__ import annotations

import re
from pathlib import Path


DIFF_FILE_PATTERNS = (
    re.compile(r"^\+\+\+ [ab]/(.+)$"),
    re.compile(r"^diff --git a/(.+?) b/(.+)$"),
    re.compile(r"^rename to (.+)$"),
)


def extract_changed_paths(diff_text: str) -> list[str]:
    """Extract changed file paths from a unified diff."""
    if not diff_text.strip():
        return []

    paths: list[str] = []
    seen: set[str] = set()

    for raw_line in diff_text.splitlines():
        line = raw_line.strip()
        if line.startswith("+++ /dev/null") or line.startswith("--- /dev/null"):
            continue

        match = DIFF_FILE_PATTERNS[0].match(line)
        if match:
            path = match.group(1)
            if path not in seen:
                seen.add(path)
                paths.append(path)
            continue

        match = DIFF_FILE_PATTERNS[1].match(line)
        if match:
            for path in match.groups():
                if path not in seen:
                    seen.add(path)
                    paths.append(path)
            continue

        match = DIFF_FILE_PATTERNS[2].match(line)
        if match:
            path = match.group(1)
            if path not in seen:
                seen.add(path)
                paths.append(path)

    return [path for path in paths if path and not path.endswith("/dev/null")]


def combine_diff_sources(manual_diff: str, uploaded_diffs: list[tuple[str, str]]) -> str:
    """Combine manual and uploaded diff content into one analysis payload."""
    chunks: list[str] = []

    if manual_diff.strip():
        chunks.append(manual_diff.strip())

    for filename, content in uploaded_diffs:
        text = content.strip()
        if not text:
            continue
        chunks.append(f"# Uploaded diff: {filename}\n{text}")

    return "\n\n".join(chunks)


def looks_like_binary_diff(content: bytes, filename: str) -> bool:
    if b"\x00" in content:
        return True
    suffix = Path(filename).suffix.lower()
    return suffix in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".exe"}

