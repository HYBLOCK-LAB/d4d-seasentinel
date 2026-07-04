from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    for candidate in (Path(__file__).resolve(), *Path(__file__).resolve().parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise FileNotFoundError("pyproject.toml not found in any parent directory")


def data_dir(*parts: str) -> Path:
    return repo_root().joinpath("data", *parts)
