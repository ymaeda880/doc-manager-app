"""
io.py
=================================
PDF のバイナリ/BASE64 読み込み、およびサムネイル（1ページ目 PNG）の生成。

機能
----
- サムネイル生成: ページ幅に対して `thumb_px` を基準にズームを計算（過大/過小はクリップ）。
- バイナリ / Base64 形式での PDF 読み込み。
- すべてキャッシュ可能（Streamlit 環境では `st.cache_data`）。

注意
----
- サムネ生成は 1 ページ目のみ。性能・用途次第で拡張可。

公開関数一覧
------------
- render_thumb_png(pdf_path: str, thumb_px: int, mtime_ns: int) -> bytes  
    先頭ページのサムネイル PNG を返す。

- read_pdf_bytes(pdf_path: str, mtime_ns: int) -> bytes  
    PDF をバイト列で返す（viewer/embed 用）。

- read_pdf_b64(pdf_path: str, mtime_ns: int) -> str  
    PDF を Base64 文字列で返す（<object> 埋め込みなどに便利）。
"""

from __future__ import annotations
import base64
from .cache import cache_data

__all__ = ["render_thumb_png", "read_pdf_bytes", "read_pdf_b64"]


@cache_data()(show_spinner=False)
def render_thumb_png(pdf_path: str, thumb_px: int, mtime_ns: int) -> bytes:
    """先頭ページのサムネイル PNG を返す。"""
    import fitz
    doc = fitz.open(pdf_path)
    try:
        page = doc.load_page(0)
        w = page.rect.width
        zoom = max(0.5, min(5.0, float(thumb_px) / max(w, 1.0)))
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()


@cache_data()(show_spinner=False)
def read_pdf_bytes(pdf_path: str, mtime_ns: int) -> bytes:
    """PDF をバイト列で返す（viewer/embed 用）。"""
    from pathlib import Path
    return Path(pdf_path).read_bytes()


@cache_data()(show_spinner=False)
def read_pdf_b64(pdf_path: str, mtime_ns: int) -> str:
    """PDF を Base64 文字列で返す（<object> 埋め込みなどに便利）。"""
    from pathlib import Path
    return base64.b64encode(Path(pdf_path).read_bytes()).decode("ascii")
