# lib/viewer/signatures.py
from __future__ import annotations
from pathlib import Path
from typing import Tuple
from functools import lru_cache

from lib.viewer.files import list_pdfs
from lib.pdf.info import quick_pdf_info

def make_sig_from_dir(dir_path: Path) -> Tuple[Tuple[str, int], ...]:
    """フォルダ直下のPDFを (path, mtime_ns) の一覧に。"""
    pdfs = list_pdfs(dir_path)
    return tuple(sorted([(str(p), p.stat().st_mtime_ns) for p in pdfs],
                        key=lambda t: t[0].lower()))

@lru_cache(maxsize=8192)
def pdf_kind_counts(sig: Tuple[Tuple[str, int], ...]) -> Tuple[int, int, int]:
    """
    quick_pdf_info によりフォルダ直下PDFの種別を集計。
    戻り値: (画像PDF数, テキストPDF数, 総数)
    """
    img = txt = 0
    for path_str, mtime_ns in sig:
        info = quick_pdf_info(path_str, mtime_ns)
        kind = (info.get("kind") or "").strip()
        if kind == "テキストPDF":
            txt += 1
        elif kind == "画像PDF":
            img += 1
    return img, txt, len(sig)
