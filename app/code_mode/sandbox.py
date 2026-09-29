"""Scoped filesystem access for Code mode — confines every read/write to one chosen
root folder, so a tool call can never escape it via '..' or an absolute path."""

from pathlib import Path

SKIP_DIR_NAMES = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".mypy_cache", ".pytest_cache", "dist", "build",
}


class SandboxViolation(Exception):
    """Raised when a requested relative path would resolve outside the sandboxed root."""


class FolderSandbox:
    def __init__(self, root: str):
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise NotADirectoryError(f"'{root}' is not a directory")

    def resolve(self, relative_path: str) -> Path:
        candidate = (self.root / (relative_path or ".")).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError:
            raise SandboxViolation(
                f"'{relative_path}' resolves outside the selected folder."
            ) from None
        return candidate

    def list_files(self, relative_dir: str = ".", max_entries: int = 500) -> list[str]:
        base = self.resolve(relative_dir)
        if not base.is_dir():
            raise NotADirectoryError(f"'{relative_dir}' is not a directory")

        entries: list[str] = []
        for path in sorted(base.rglob("*")):
            rel_parts = path.relative_to(self.root).parts
            if any(part in SKIP_DIR_NAMES or part.startswith(".") for part in rel_parts):
                continue
            suffix = "/" if path.is_dir() else ""
            entries.append(str(path.relative_to(self.root)) + suffix)
            if len(entries) >= max_entries:
                entries.append(f"... (truncated at {max_entries} entries)")
                break
        return entries

    def read_file(self, relative_path: str, max_chars: int = 20_000) -> str:
        path = self.resolve(relative_path)
        if not path.is_file():
            raise FileNotFoundError(f"'{relative_path}' is not a file")
        text = path.read_text(errors="replace")
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n... [truncated, {len(text)} chars total]"
        return text

    def read_file_raw(self, relative_path: str) -> str:
        """Full, untruncated contents for diffing — '' if the file doesn't exist yet."""
        path = self.resolve(relative_path)
        return path.read_text(errors="replace") if path.is_file() else ""

    def write_file(self, relative_path: str, content: str) -> None:
        path = self.resolve(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
