"""
sysenv.py
=================================
OCR 周辺の実行環境チェック用ヘルパ。

機能概要
--------
- ocrmypdf (Python API) の import 可否を確認
- ocrmypdf (CLI) の存在確認
- tesseract の存在確認

公開関数一覧
------------
- env_checks() -> dict[str, bool]  
    OCR 実行に必要なツール群の有無を返す。
"""

from __future__ import annotations
import shutil

__all__ = ["env_checks"]

def env_checks() -> dict[str, bool]:
    """OCR 実行に必要なツール群の有無を返す。

    Returns
    -------
    dict
        {"ocrmypdf_py": bool, "ocrmypdf_cli": bool, "tesseract": bool}
    """
    ok_cli = shutil.which("ocrmypdf") is not None
    ok_tess = shutil.which("tesseract") is not None
    try:
        import ocrmypdf as _m  # noqa: F401
        ok_py = True
    except Exception:
        ok_py = False
    return {"ocrmypdf_py": ok_py, "ocrmypdf_cli": ok_cli, "tesseract": ok_tess}
