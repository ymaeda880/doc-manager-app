# lib/viewer/files.py
from __future__ import annotations
from pathlib import Path
from typing import List

def list_dirs(p: Path) -> List[Path]:
    """隠しフォルダを除外して直下のディレクトリを列挙。"""
    try:
        return sorted(
            [c for c in p.iterdir() if c.is_dir() and not c.name.startswith(".")],
            key=lambda x: x.name.lower(),
        )
    except Exception:
        return []

def list_pdfs(p: Path) -> List[Path]:
    """隠しファイルを除外して直下の .pdf を列挙。"""
    if not p.exists():
        return []
    res: List[Path] = []
    for c in p.iterdir():
        if c.is_file() and not c.name.startswith(".") and c.suffix.lower() == ".pdf":
            res.append(c)
    return sorted(res, key=lambda x: x.name.lower())

def is_ocr_name(p: Path) -> bool:
    """ファイル名が *_ocr.pdf かどうか（大文字小文字は区別）"""
    return p.suffix.lower() == ".pdf" and p.stem.endswith("_ocr")

def dest_ocr_path(src: Path) -> Path:
    """入力PDFの出力先パス（*_ocr.pdf）"""
    return src.with_name(src.stem + "_ocr.pdf")
