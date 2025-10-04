"""
ocr.py
=================================
OCRmyPDF を用いた OCR 変換（Python API を優先、失敗時は CLI へフォールバック）。

目的
----
- 画像PDFを「テキスト層付きPDF」に変換（force_ocr=True）

設計
----
1. Python API（高速・同一プロセス）
2. 失敗時は CLI 実行（環境差異への保険）

依存
----
- OCRmyPDF（Python/CLI）
- OS にインストール済みの Tesseract（jpn+eng など）

公開関数一覧
------------
- run_ocr(src: Path, dst: Path, *, lang: str, optimize: int = 1,
          jobs: int = 2, rotate_pages: bool = True,
          sidecar_path: Optional[Path] = None) -> None  
    OCR を実行（Python API → 失敗時は CLI）。
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional
import shutil
import subprocess

__all__ = ["run_ocr"]

def run_ocr(
    src: Path,
    dst: Path,
    *,
    lang: str,
    optimize: int = 1,
    jobs: int = 2,
    rotate_pages: bool = True,
    sidecar_path: Optional[Path] = None
) -> None:
    """OCR を実行（Python API → CLI）。

    Parameters
    ----------
    src, dst : Path
        入力/出力 PDF
    lang : str
        Tesseract 言語（例: "jpn+eng"）
    optimize : int, default 1
        圧縮レベル（0-3）
    jobs : int, default 2
        並列ジョブ数
    rotate_pages : bool, default True
        自動回転補正
    sidecar_path : Optional[Path]
        テキストを sidecar(.txt) として保存する場合のパス
    """
    try:
        _run_python(src, dst, lang=lang, optimize=optimize, jobs=jobs,
                    rotate_pages=rotate_pages, sidecar_path=sidecar_path)
    except Exception:
        _run_cli(src, dst, lang=lang, optimize=optimize, jobs=jobs,
                 rotate_pages=rotate_pages, sidecar_path=sidecar_path)


def _run_python(
    src: Path,
    dst: Path,
    *,
    lang: str,
    optimize: int,
    jobs: int,
    rotate_pages: bool,
    sidecar_path: Optional[Path]
) -> None:
    """OCRmyPDF の Python API を用いる実体処理。"""
    import ocrmypdf
    kwargs = dict(
        language=lang,
        output_type="pdf",
        optimize=optimize,
        deskew=True,
        clean=True,
        progress_bar=False,
        jobs=jobs,
        force_ocr=True,
        skip_text=False,
    )
    if rotate_pages:
        kwargs["rotate_pages"] = True
    if sidecar_path is not None:
        kwargs["sidecar"] = str(sidecar_path)
    ocrmypdf.ocr(str(src), str(dst), **kwargs)


def _run_cli(
    src: Path,
    dst: Path,
    *,
    lang: str,
    optimize: int,
    jobs: int,
    rotate_pages: bool,
    sidecar_path: Optional[Path]
) -> None:
    """OCRmyPDF の CLI をサブプロセスで実行（フォールバック）。"""
    exe = shutil.which("ocrmypdf")
    if not exe:
        raise RuntimeError("ocrmypdf が見つかりません。")
    cmd = [
        exe, "--language", lang, "--output-type", "pdf",
        "--deskew", "--clean", "--optimize", str(optimize),
        "--jobs", str(jobs), "--force-ocr",
    ]
    if rotate_pages:
        cmd.append("--rotate-pages")
    if sidecar_path is not None:
        cmd.extend(["--sidecar", str(sidecar_path)])
    cmd.extend([str(src), str(dst)])

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr or res.stdout or "ocrmypdf 実行に失敗しました。")
