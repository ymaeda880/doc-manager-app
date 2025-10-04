"""
text.py
=================================
テキスト抽出（get_text）と、ページ単位の軽量解析（プレビュー用）、
および .txt 書き出しを提供。

注意
----
- ここでの抽出は OCR を行いません。すでにテキスト層のある PDF を対象とします。
- OCR 後の PDF や sidecar(.txt) を使う場合は呼び出し側で制御してください。

公開関数一覧
------------
- extract_text_pdf(p_pdf: Path, sidecar: Optional[Path] = None) -> str  
    PDF 全ページからテキストを抽出して結合して返す。

- analyze_pdf_texts(pdf_path: str, mtime_ns: int, mode="all", sample_pages=6) -> dict  
    ページ単位のテキスト抽出（プレビュー/UI向け）。

- write_text_file(txt_path: Path, content: str) -> None  
    テキストを UTF-8 で保存する。
"""

from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Any, Optional
from .cache import cache_data

__all__ = ["extract_text_pdf", "analyze_pdf_texts", "write_text_file"]

def extract_text_pdf(p_pdf: Path, sidecar: Optional[Path] = None) -> str:
    """PDF 全ページからテキストを抽出し結合して返す。

    Notes
    -----
    - テキストがまったく得られない場合、`sidecar` があればフォールバックして読みます。
    """
    import fitz
    text = ""
    try:
        doc = fitz.open(str(p_pdf))
        parts: List[str] = []
        for i in range(doc.page_count):
            try:
                parts.append(doc.load_page(i).get_text("text") or "")
            except Exception:
                parts.append("")
        text = "\n".join(parts).strip()
    except Exception:
        text = ""
    finally:
        try:
            doc.close()
        except Exception:
            pass

    if not text and sidecar and sidecar.exists():
        try:
            text = sidecar.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            pass
    return text


@cache_data()(show_spinner=True)
def analyze_pdf_texts(
    pdf_path: str,
    mtime_ns: int,
    mode: str = "all",
    sample_pages: int = 6
) -> Dict[str, Any]:
    """ページ単位のテキスト抽出（プレビュー/UI向け）。

    Parameters
    ----------
    mode : {"all", "sample"}
        全ページ or 先頭Nページ
    sample_pages : int
        mode="sample" のときの N
    """
    import fitz
    doc = fitz.open(pdf_path)
    try:
        total_pages = doc.page_count
        if total_pages <= 0:
            return {"scanned_pages": 0, "total_pages": 0, "pages": []}
        page_range = range(0, min(sample_pages, total_pages)) if mode == "sample" else range(0, total_pages)
        pages_info = [{"page": i + 1, "text": (doc.load_page(i).get_text("text") or "").strip()} for i in page_range]
        return {"scanned_pages": len(pages_info), "total_pages": total_pages, "pages": pages_info}
    finally:
        doc.close()


def write_text_file(txt_path: Path, content: str) -> None:
    """テキストを UTF-8 で保存（親ディレクトリは自動生成）。"""
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    txt_path.write_text(content, encoding="utf-8")
