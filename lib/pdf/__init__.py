"""
lib.pdf (facade)
=================================
PDF ユーティリティの公開 API を一箇所に集約した“ファサード”モジュール。

- 利用側はここだけ import すれば OK（内部の分割は意識不要）
- 互換: 旧 `lib.pdf_tools` からの移行も簡単（同じ API 名を公開）

主な関数（抜粋）:
- quick_pdf_info
- run_ocr
- extract_text_pdf, analyze_pdf_texts, write_text_file
- analyze_pdf_images, extract_embedded_images
- render_thumb_png, read_pdf_bytes, read_pdf_b64
- rel_from, iter_pdfs, make_converted_path, make_text_path
"""

from .paths import rel_from, iter_pdfs, make_converted_path, make_text_path
from .info import quick_pdf_info
from .ocr import run_ocr
from .text import extract_text_pdf, write_text_file, analyze_pdf_texts
from .images import analyze_pdf_images, extract_embedded_images
from .io import render_thumb_png, read_pdf_bytes, read_pdf_b64
from .sysenv import env_checks

__all__ = [
    "rel_from", "iter_pdfs", "make_converted_path", "make_text_path",
    "quick_pdf_info",
    "run_ocr",
    "extract_text_pdf", "write_text_file", "analyze_pdf_texts",
    "analyze_pdf_images", "extract_embedded_images",
    "render_thumb_png", "read_pdf_bytes", "read_pdf_b64",
    "env_checks",                       # ← 追加
]

