# pages/50_一括探索ビューア.py
# ============================================
# 📁 docs_root 一括探索ビューワ
# - PATHS.docs_root を起点に再帰走査
# - ファイル一覧（相対パス / サイズ / 形式 / 更新日時）
# - 形式別サマリ、フォルダ別サマリ
# - CSV ダウンロード
# ============================================

from __future__ import annotations
from pathlib import Path
from typing import Iterator, Dict, Any, List, Tuple
import os
import sys
import traceback
import datetime as dt

import streamlit as st
import pandas as pd

# 標準パス
from lib.app_paths import PATHS  # PATHS.docs_root を使用

# docsパス
docs_root = Path(st.text_input("docs_root", value=str(PATHS.docs_root))).expanduser().resolve()

# ---------- ユーティリティ ----------

def _format_bytes(n: int) -> str:
    # ヒューマンリーダブル表記
    units = ["B", "KB", "MB", "GB", "TB"]
    s = float(n)
    for u in units:
        if s < 1024.0 or u == units[-1]:
            return f"{s:.2f} {u}"
        s /= 1024.0
    return f"{n} B"

def _iter_files(root: Path, ignore_hidden: bool = True) -> Iterator[Path]:
    """root 配下の全ファイルを yield（シンボリックリンクは辿らない）"""
    # root が存在しない場合は空
    if not root.exists():
        return
    for p in root.rglob("*"):
        try:
            if p.is_symlink():
                continue
            if ignore_hidden and any(part.startswith(".") for part in p.relative_to(root).parts):
                continue
            if p.is_file():
                yield p
        except Exception:
            # アクセス不可などはスキップ
            continue

def _safe_stat(p: Path) -> Tuple[int, float]:
    """サイズと mtime を返す（失敗時は 0, 0.0）"""
    try:
        st_ = p.stat()
        return int(st_.st_size), float(st_.st_mtime)
    except Exception:
        return 0, 0.0

def _ext_of(p: Path) -> str:
    e = p.suffix.lower().strip()
    return e[1:] if e.startswith(".") else e  # ".PDF" -> "pdf"

# ---------- Streamlit UI ----------

st.set_page_config(page_title="Docs Explorer", page_icon="📁", layout="wide")
st.title("📁 Docs Explorer — docs_root 配下の一括一覧")

with st.sidebar:
    st.header("設定")
    
    st.caption(f"実パス: `{docs_root}`")

    col = st.columns(2)
    with col[0]:
        ignore_hidden = st.checkbox("隠しファイル/フォルダを除外", value=True)
    with col[1]:
        max_rows = st.number_input("表示件数（先頭N）", min_value=100, max_value=200_000, value=10_000, step=100)

    st.divider()
    st.subheader("フィルタ")
    name_filter = st.text_input("ファイル名に含む文字（部分一致）", value="").strip()
    ext_filter  = st.text_input("拡張子フィルタ（例: pdf,docx,xlsx をカンマ区切り）", value="").strip()
    folder_filter = st.text_input("相対フォルダに含む文字（例: 2025/reports）", value="").strip()

    st.divider()
    st.subheader("並び順")
    sort_by = st.selectbox("ソートキー", ["path", "size", "mtime", "ext"], index=0)
    ascending = st.checkbox("昇順", value=True)

# ---------- データ収集 ----------

if not docs_root.exists():
    st.error("docs_root が存在しません。設定またはマウントを確認してください。")
    st.stop()

rows: List[Dict[str, Any]] = []
root = docs_root

try:
    for p in _iter_files(root, ignore_hidden=ignore_hidden):
        size, mtime = _safe_stat(p)
        rel = str(p.relative_to(root))
        ext = _ext_of(p)
        if name_filter and (name_filter.lower() not in p.name.lower()):
            continue
        if folder_filter and (folder_filter.lower() not in rel.lower()):
            continue
        if ext_filter:
            allow = {e.strip().lower() for e in ext_filter.split(",") if e.strip()}
            if ext not in allow:
                continue
        rows.append({
            "path": rel,
            "name": p.name,
            "ext": ext or "(none)",
            "size": size,
            "size_hr": _format_bytes(size),
            "mtime": mtime,
            "modified": dt.datetime.fromtimestamp(mtime) if mtime else None,
            "parent": str(p.parent.relative_to(root)) if p.parent != root else "",
            "depth": len(p.relative_to(root).parts) - 1,
        })
        if len(rows) >= int(max_rows):
            # 取りすぎ防止（表示用）
            break
except Exception as e:
    st.error(f"走査中にエラーが発生しました: {e}")
    with st.expander("エラートレース"):
        st.code(traceback.format_exc())

if not rows:
    st.info("条件に一致するファイルが見つかりません。")
    st.stop()

df = pd.DataFrame(rows)

# ソート
if sort_by == "path":
    df = df.sort_values("path", ascending=ascending, kind="mergesort")
elif sort_by == "size":
    df = df.sort_values("size", ascending=ascending, kind="mergesort")
elif sort_by == "mtime":
    df = df.sort_values("mtime", ascending=ascending, kind="mergesort")
elif sort_by == "ext":
    df = df.sort_values(["ext", "path"], ascending=[ascending, True], kind="mergesort")

# ---------- サマリ ----------

st.subheader("📊 サマリ")
c1, c2, c3, c4 = st.columns(4)
c1.metric("ファイル数", f"{len(df):,}")
c2.metric("総サイズ", _format_bytes(int(df["size"].sum())))
unique_exts = df["ext"].nunique()
c3.metric("形式（拡張子）数", f"{unique_exts:,}")
top_ext = df["ext"].value_counts().head(1)
c4.metric("最多形式", f"{top_ext.index[0]}（{top_ext.iloc[0]:,}件）" if not top_ext.empty else "-")

with st.expander("拡張子別サマリ（件数・合計サイズ）", expanded=True):
    ext_summary = (
        df.groupby("ext")
          .agg(count=("path", "count"), total_size=("size", "sum"))
          .reset_index()
          .sort_values(["count", "ext"], ascending=[False, True])
    )
    ext_summary["total_size_hr"] = ext_summary["total_size"].map(lambda x: _format_bytes(int(x)))
    st.dataframe(ext_summary, width="stretch")
    st.download_button(
        "⬇️ 拡張子サマリをCSVで保存",
        data=ext_summary.to_csv(index=False).encode("utf-8"),
        file_name="ext_summary.csv",
        mime="text/csv",
    )

with st.expander("フォルダ別サマリ（直上親フォルダ単位）", expanded=False):
    folder_summary = (
        df.groupby("parent")
          .agg(count=("path", "count"), total_size=("size", "sum"))
          .reset_index()
          .sort_values(["count", "parent"], ascending=[False, True])
    )
    folder_summary["total_size_hr"] = folder_summary["total_size"].map(lambda x: _format_bytes(int(x)))
    st.dataframe(folder_summary, width="stretch")
    st.download_button(
        "⬇️ フォルダサマリをCSVで保存",
        data=folder_summary.to_csv(index=False).encode("utf-8"),
        file_name="folder_summary.csv",
        mime="text/csv",
    )

st.divider()

# ---------- ファイル一覧 ----------

st.subheader("🗂 ファイル一覧")
show_cols = ["path", "name", "ext", "size_hr", "modified", "parent", "depth"]
st.dataframe(df[show_cols], width="stretch", height=520)

# ダウンロード（フルデータ）
st.download_button(
    "⬇️ ファイル一覧をCSVで保存（全列）",
    data=df.to_csv(index=False).encode("utf-8"),
    file_name="docs_files.csv",
    mime="text/csv",
)

st.caption("※ 表示件数が多い場合はサイドバーの「表示件数（先頭N）」を調整してください。")
