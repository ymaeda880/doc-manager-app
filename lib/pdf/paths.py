"""
lib/pdf/paths.py
=================================
パス関連ユーティリティを集約（相対パス化、列挙（rglob）、派生パス生成）。

目的
----
- I/O ルールを一箇所で定義し、UI/業務ロジックから切り離す。

公開関数一覧
------------
- rel_from(path: Path, base: Path) -> str  
    `base` からの相対パス文字列（無理なら名前）。

- iter_pdfs(root: Path) -> List[Path]  
    `root` 以下の全 PDF（*.pdf）を再帰列挙。

- make_converted_path(src_path: Path, src_root: Path, dst_root: Path) -> Path  
    OCR 後の出力先パス（*_converted.pdf）を計算。

- make_text_path(source_pdf: Path, src_root: Path, dst_root: Path, txt_root: Path) -> Path  
    テキスト出力の *.txt パスを計算（src/dst どちらからでも）。
"""

from __future__ import annotations
from pathlib import Path
from typing import List

__all__ = [
    "rel_from",
    "iter_pdfs",
    "make_converted_path",
    "make_text_path",
]


def rel_from(path: Path, base: Path) -> str:
    """基準 `base` からの相対パス文字列を返す。相対化できなければファイル名のみ。

    Parameters
    ----------
    path : Path
        対象パス
    base : Path
        基準ディレクトリ

    Returns
    -------
    str
        相対パス文字列またはファイル名
    """
    try:
        return str(path.relative_to(base))
    except Exception:
        return path.name


def iter_pdfs(root: Path) -> List[Path]:
    """`root` 以下の PDF を再帰的に列挙して返す。

    Notes
    -----
    - 存在しない `root` の場合は空リスト。
    """
    if not root.exists():
        return []
    return sorted(root.rglob("*.pdf"))


def make_converted_path(src_path: Path, src_root: Path, dst_root: Path) -> Path:
    """元 PDF に対応する OCR 変換後 PDF の出力先パスを作る。

    ルール:
    - `src_root` 以下の相対構造を `dst_root` に引き継ぐ。
    - ファイル名は `<stem>_converted.pdf`。

    例:
    - src: data/pdf/2025/a/b/c.pdf
    - dst: data/converted_pdf/2025/a/b/c_converted.pdf
    """
    try:
        rel = src_path.relative_to(src_root)
    except Exception:
        rel = Path(src_path.name)
    return (dst_root / rel).with_name(f"{src_path.stem}_converted.pdf")


def make_text_path(source_pdf: Path, src_root: Path, dst_root: Path, txt_root: Path) -> Path:
    """テキスト保存先の *.txt パスを決める。

    優先順:
    1) source_pdf が `src_root` 配下なら、その構造で txt_root 配下に。
    2) そうでなく、`dst_root` 配下なら、その構造で txt_root 配下に。
    3) どちらでもないなら、txt_root 直下にファイル名.txt を置く。
    """
    try:
        rel = source_pdf.relative_to(src_root)
        base = txt_root / rel
    except Exception:
        try:
            rel = source_pdf.relative_to(dst_root)
            base = txt_root / rel
        except Exception:
            base = txt_root / source_pdf.name
    return base.with_suffix(".txt")
