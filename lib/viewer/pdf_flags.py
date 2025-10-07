# lib/viewer/pdf_flags.py
from __future__ import annotations
from pathlib import Path

def is_pdf_locked(p: Path) -> bool:
    """
    PyMuPDF を用いて PDF がパスワード保護かを簡易判定。
    失敗時は False（未ロック扱い）
    """
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(p))
        locked = bool(getattr(doc, "needs_pass", False))
        doc.close()
        return locked
    except Exception:
        return False
