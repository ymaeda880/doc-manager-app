"""
pages/10_フォルダービュア.py
============================================
📂 フォルダービュア（original_docs_root / organized_docs_root 配下の一覧）

モジュール概要（module docstring）
---------------------------------
- 本ページは、`lib.app_paths.PATHS` に定義された 2 種の基点ルート
  - `original_docs_root` …… 収集直後などの“原本”ツリー（original）
  - `organized_docs_root` …… 整理・加工後の“整備済み”ツリー（organized）
 からフォルダ・ファイルを探索（scan）し、結果をインタラクティブに表示・CSV ダウンロードします。

- 大規模環境（数十万ファイル）でも UI が固まらないよう、
  - 深さ（depth）の上限指定、
  - 表示行（folders + files）の総数に上限（early stop）を設ける設計です。

依存関係（dependencies）
-------------------------
- `lib.app_paths.PATHS`: ルートパス設定（path manager）。
- `lib.fsnav.scan`:
  - `is_hidden_rel(path: Path, root: Path) -> bool`
  - `safe_stat_mtime(path: Path) -> Optional[float]`
  - `listdir_counts(dir: Path) -> tuple[int, int]`
  - `iter_dirs(root: Path, max_depth: int, ignore_hidden: bool) -> Iterator[Path]`
  - `ext_key(path: Path) -> str`（拡張子の正規化 key、先頭にドット）
  - `walk_tree_collect(...) -> tuple[dirs_rows, files_rows, filetype_counts, total_rows, max_depth_found]`

UI の主な構成（user interface）
-------------------------------
1. 基点ルートの選択（original / organized）と手動上書き入力欄。
2. サイドバーに共通設定：
   - 隠しフォルダ除外（pruning）、
   - 直下件数の計算（I/O コスト注意）、
   - 名前フィルタ（部分一致）。
3. 深さ 1 のフォルダ一覧（起点候補を俯瞰）。
4. 任意の階層までのフォルダ & ファイル一覧：
   - 深さ上限、総表示行上限、（深さ ≥ 2 のとき）ルート直下の特定フォルダからの探索、
   - 拡張子別の総数、
   - フォルダとファイルの一覧（並べ替え・フィルタ・CSV）。

設計メモ（design notes）
------------------------
- `walk_tree_collect` は探索と同時に早期停止（上限到達時点で break）に対応している想定。
- DataFrame は空でも列を先に定義して UI の安定性（列順・型の変動抑制）を重視。
- ファイルタブの既定フィルタは `.pdf` のみ（大量環境での初期負荷軽減）。

想定する DataFrame スキーマ（schemas）
------------------------------------
- フォルダ行（dirs_rows）: `{"kind": "dir", "path", "name", "depth", "parent", "modified", "files_direct", "dirs_direct"}`
- ファイル行（files_rows）: `{"kind": "file", "path", "name", "depth", "parent", "modified", "size_bytes", "ext"}`

注意事項（notes）
-----------------
- `直下件数の計算` は *非再帰*。ディレクトリの直下のみをカウント。I/O が増えるため必要時のみ有効化。
- ネットワーク越しのマウント（NAS/NFS/SMB）では mtime/size 取得が相対的に遅くなる点に注意。
"""

from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, List
import datetime as dt

import streamlit as st
import pandas as pd

# 標準パス（original_docs_root / organized_docs_root を使用）
from lib.app_paths import PATHS

# 走査ユーティリティ（共通モジュール）
from lib.fsnav.scan import (
    is_hidden_rel,
    safe_stat_mtime,
    listdir_counts,
    iter_dirs,
    ext_key,
    walk_tree_collect,
)

# ---------------------------------------------------------------------
# ページ設定（最初に 1 回だけ）
# - タイトル・アイコン・レイアウトなどの基本設定。
# - Streamlit の `set_page_config` はページロード直後に呼び出すのが推奨。
# ---------------------------------------------------------------------
st.set_page_config(page_title="Folder Viewer", page_icon="📂", layout="wide")
st.title("📂 Folder Viewer — original / organized 配下のフォルダ・ファイル一覧")

# ---------------------------------------------------------------------
# 基点ルート選択（original / organized） + 手動上書き
# - PATHS から取得できる利用可能なルートを列挙（存在しない属性はスキップ）。
# - ラジオボタンでどちらかを選び、必要に応じてテキスト入力で上書き可能。
# - `~` 展開・相対パスの絶対化（resolve）も行い、I/O 操作前に確認。
# ---------------------------------------------------------------------
_ORG = getattr(PATHS, "original_docs_root", None)
_ORZ = getattr(PATHS, "organized_docs_root", None)

root_options = []
if _ORG is not None:
    root_options.append(("original_docs_root", str(_ORG)))
if _ORZ is not None:
    root_options.append(("organized_docs_root", str(_ORZ)))

if not root_options:
    st.error("PATHS.original_docs_root / PATHS.organized_docs_root のいずれも見つかりません。設定を確認してください。")
    st.stop()

selected_key = st.radio(
    "基点ルートを選択",
    options=[k for k, _ in root_options],
    index=0,
    help="organized_docs_root を選ぶと、整理済みツリーを基点に列挙します。",
    horizontal=True,
)
# 選択されたキーに対応する既定パス文字列
default_str = dict(root_options)[selected_key]

# 手動上書き可能な入力欄（`~` 展開・相対→絶対変換を行う）
root_text = st.text_input(
    selected_key,
    value=default_str,
    help="必要に応じて手動でパスを上書きできます（~ 展開・相対→絶対変換あり）。",
)
# 入力値を Path に変換し、ホームチルダ展開 → 絶対パス解決
ROOT = Path(root_text).expanduser().resolve()

# ルート存在チェック：存在しなければ明示的に中断
if not ROOT.exists():
    st.error(f"{selected_key} が存在しません。設定またはマウントを確認してください。実パス: {ROOT}")
    st.stop()

# =====================================================================
# サイドバー（共通設定 UI）
# - 隠しフォルダ除外（'.' 始まりを pruning）
# - 直下件数（非再帰）を計算するかどうか
# - 名前フィルタ（部分一致）
# =====================================================================
with st.sidebar:
    st.header("設定")
    st.caption(f"実パス: `{ROOT}`（{selected_key}）")

    col = st.columns(2)
    with col[0]:
        # 隠しフォルダの除外フラグ（'.' 始まりのディレクトリに潜らない）
        ignore_hidden = st.checkbox("隠しフォルダを除外", value=True, help="'.' 始まりを除外。配下にも潜りません。")
    with col[1]:
        # 各フォルダ直下（非再帰）の files/dirs 件数を算出（I/O 負荷に注意）
        compute_counts = st.checkbox(
            "直下の件数を計算",
            value=False,
            help="各フォルダ直下の files/dirs を非再帰で計算（I/Oコストに注意）。",
        )

    st.divider()
    st.subheader("① フィルタ")
    # フォルダ名に対する部分一致フィルタ（大文字小文字は無視）
    name_filter = st.text_input("フォルダ名に含む文字（部分一致）", value="").strip()

# =====================================================================
# （1）深さ 1 のフォルダ一覧（起点候補の把握も兼ねる）
# - まずは ROOT 直下のディレクトリを列挙し、俯瞰用の DataFrame を作成。
# - ここで得られたフォルダを「起点候補（SUBROOT）」として（2）で利用可能に。
# =====================================================================
st.subheader("① 深さ1のフォルダ一覧")
rows_lvl1: List[Dict[str, Any]] = []
level1_paths: List[Path] = []

for d in iter_dirs(ROOT, max_depth=1, ignore_hidden=ignore_hidden):
    level1_paths.append(d)
    name = d.name

    # 名前フィルタ（部分一致）を適用（未入力ならスキップ）
    if name_filter and (name_filter.lower() not in name.lower()):
        continue

    # mtime（float epoch）を安全に取得（失敗時は None）
    mtime = safe_stat_mtime(d)
    # 非再帰の直下件数（I/O 負荷のためオプション）
    files_cnt, dirs_cnt = listdir_counts(d) if compute_counts else (None, None)

    # DataFrame 用の行を構築
    rows_lvl1.append(
        {
            "path": str(d.relative_to(ROOT)),  # ROOT からの相対表示
            "name": name,
            "depth": 1,
            "parent": "" if d.parent == ROOT else str(d.parent.relative_to(ROOT)),
            "modified": dt.datetime.fromtimestamp(mtime) if mtime else None,
            "files_direct": files_cnt,
            "dirs_direct": dirs_cnt,
        }
    )

# 結果表示と CSV ダウンロード（行が 1 件以上ある場合）
if rows_lvl1:
    # 安定ソート（mergesort）で path 昇順に整列
    df1 = pd.DataFrame(rows_lvl1).sort_values("path", kind="mergesort")
    st.dataframe(df1, width="stretch", height=360)
    st.download_button(
        "⬇️ 深さ1フォルダ一覧をCSVで保存",
        data=df1.to_csv(index=False).encode("utf-8-sig"),
        file_name="folders_depth1.csv",
        mime="text/csv",
    )
else:
    st.info("深さ1で条件に一致するフォルダは見つかりませんでした。")

st.divider()

# =====================================================================
# （2）任意深さのフォルダ & ファイル一覧
# - 深さ（max_depth）、表示行上限（max_rows_total）を指定し、必要なら
#   深さ 2 以上のときに ROOT 直下の任意フォルダ（SUBROOT）を探索起点に選択可能。
# - 実行ボタンで探索実施、クリアボタンで結果をリセット。
# =====================================================================
st.subheader("② 指定の階層までのフォルダ & ファイル一覧")

with st.sidebar:
    st.subheader("② 任意の階層一覧（詳細設定）")

    # 探索する最大深さ（1〜10）を UI から指定
    max_depth = int(st.number_input("深さ（1〜10）", min_value=1, max_value=10, value=3, step=1))

    # 一覧に表示する総行数（dirs + files）の上限：到達時に探索を早期停止
    max_rows_total = int(
        st.number_input(
            "表示するフォルダ+ファイルの総数上限",
            min_value=100,
            max_value=200_000,
            value=10_000,
            step=100,
            help="列挙の早期停止に利用。上限到達時点で探索を打ち切ります。",
        )
    )

    # 深さ 2 以上のときに有効となる、起点フォルダ（SUBROOT）選択
    level1_labels = ["（すべて / ルート直下から探索）"] + [str(p.relative_to(ROOT)) for p in sorted(level1_paths)]
    disable_selector = (max_depth <= 1) or (len(level1_paths) == 0)

    selected_label = st.selectbox(
        "起点フォルダ（深さ2以上で有効）",
        options=level1_labels,
        index=0,
        disabled=disable_selector,
        help="深さ2以上を選ぶと、ここで選択した直下フォルダを“起点”にして探索できます。",
    )

    # 実行ボタン：押されたときにのみ探索実施
    run_btn = st.button("この設定で一覧表示")

# セッション状態（session_state）で実行フラグを管理
# - 値を保持して無駄な再計算（オートリラン）を防ぐ。
if "fv_run" not in st.session_state:
    st.session_state["fv_run"] = False
if run_btn:
    st.session_state["fv_run"] = True

# クリアボタン：結果表示をリセット
if st.button("結果をクリア"):
    st.session_state["fv_run"] = False

run = st.session_state["fv_run"]

# SUBROOT の決定：
# - 深さ 2 以上かつ選択がデフォルト以外であれば `ROOT / selected_label` を SUBROOT として利用。
# - それ以外は ROOT 自体を探索起点（BASE_ROOT）とする。
if (not disable_selector) and selected_label != "（すべて / ルート直下から探索）":
    SUBROOT = ROOT / selected_label
    BASE_ROOT = SUBROOT
else:
    SUBROOT = None
    BASE_ROOT = ROOT

# =====================================================================
# 実行時のみツリー探索（walk_tree_collect を使用）
# - 結果はフォルダ行とファイル行に分け、拡張子別総数・最大深さなども受け取る。
# - total_rows は early stop の到達確認に利用（UI へ露出）。
# =====================================================================
rows_dirs: List[Dict[str, Any]] = []
rows_files: List[Dict[str, Any]] = []
filetype_counts: Dict[str, int] = {}
total_rows: int = 0
max_depth_found: int = 0

if run:
    (
        rows_dirs,
        rows_files,
        filetype_counts,
        total_rows,
        max_depth_found,
    ) = walk_tree_collect(
        BASE_ROOT,
        max_depth=max_depth,
        ignore_hidden=ignore_hidden,
        name_filter=name_filter,
        compute_counts=compute_counts,
        max_rows_total=max_rows_total,
    )

    total_dirs = len(rows_dirs)
    total_files = len(rows_files)

    # -----------------------------
    # DataFrame 構築（空でも列を定義）
    # - 空のときにも列を明示しておくと、UI の列順が安定する（回避策）。
    # -----------------------------
    df_dirs = pd.DataFrame(rows_dirs) if rows_dirs else pd.DataFrame(
        columns=["kind", "path", "name", "depth", "parent", "modified", "files_direct", "dirs_direct"]
    )
    df_files = pd.DataFrame(rows_files) if rows_files else pd.DataFrame(
        columns=["kind", "path", "name", "depth", "parent", "modified", "size_bytes", "ext"]
    )

    # -----------------------------
    # KPI メトリクス表示
    # -----------------------------
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("フォルダ数", f"{total_dirs:,}")
    c2.metric("ファイル数", f"{total_files:,}")
    c3.metric("合計表示行（上限）", f"{total_rows:,} / {max_rows_total:,}")
    c4.metric("最大深さ", f"{max_depth_found:,}")

    # -----------------------------
    # 拡張子別の総数テーブル（ファイルタイプ集計）
    # -----------------------------
    if filetype_counts:
        st.markdown("#### ファイルタイプ（拡張子）ごとの総数")
        df_ft = pd.DataFrame(
            sorted(filetype_counts.items(), key=lambda x: x[1], reverse=True),
            columns=["ext", "count"],
        )
        st.dataframe(df_ft, width="stretch", height=280)
        st.download_button(
            "⬇️ 拡張子別集計をCSVで保存",
            data=df_ft.to_csv(index=False).encode("utf-8-sig"),
            file_name="filetype_counts.csv",
            mime="text/csv",
        )

    # -----------------------------
    # 結果一覧（タブ切替：フォルダ / ファイル）
    # -----------------------------
    st.markdown("#### 結果一覧")
    t1, t2 = st.tabs(["フォルダ", "ファイル"])

    # --- フォルダタブ ---
    with t1:
        if len(df_dirs):
            # 並べ替え UI（multiselect で優先順位の高い順に選択）
            with st.expander("並べ替え（フォルダ）", expanded=False):
                dir_cols = df_dirs.columns.tolist()
                sort_cols_dir = st.multiselect(
                    "ソート列（上から優先）",
                    options=dir_cols,
                    default=[c for c in ["depth", "path"] if c in dir_cols],
                    key="sort_cols_dir",
                    help="複数選択可。上にある列ほど優先度が高くなります。",
                )
                asc_dir = st.checkbox("昇順（全列一括）", value=True, key="asc_dir")
            # 指定がなければ（安全側で）depth→path の順で安定ソート
            df_dir_show = df_dirs.sort_values(
                sort_cols_dir or [c for c in ["depth", "path"] if c in df_dirs.columns],
                ascending=asc_dir,
                kind="mergesort",
            )
            st.dataframe(df_dir_show, width="stretch", height=420)
            st.download_button(
                "⬇️ フォルダ一覧をCSVで保存",
                data=df_dir_show.to_csv(index=False).encode("utf-8-sig"),
                file_name=(
                    f"folders_depth_upto_{max_depth}.csv"
                    if SUBROOT is None
                    else f"folders_from_{str(SUBROOT.relative_to(ROOT)).replace('/', '__')}_depth_upto_{max_depth}.csv"
                ),
                mime="text/csv",
            )
        else:
            st.info("条件に一致するフォルダは見つかりませんでした。")

    # --- ファイルタブ ---
    with t2:
        if len(df_files):
            # フィルタ UI（拡張子）
            # - 既定では `.pdf` のみを選択し、初期負荷と視認性を確保。
            with st.expander("フィルタ（ファイル）", expanded=False):
                exts_all = sorted([e for e in df_files.get("ext", pd.Series(dtype=str)).dropna().unique()])
                selected_exts = st.multiselect(
                    "拡張子でフィルタ（未選択なら全件）",
                    options=exts_all,
                    # 既定を .pdf のみに
                    default=[e for e in exts_all if e == ".pdf"],
                    key="ext_filter",
                )
            # 拡張子フィルタの適用
            if selected_exts:
                df_files_filtered = df_files[df_files["ext"].isin(selected_exts)]
            else:
                df_files_filtered = df_files

            # 並べ替え UI（ファイル）
            with st.expander("並べ替え（ファイル）", expanded=False):
                file_cols = df_files_filtered.columns.tolist()
                default_file_cols = [c for c in ["ext", "name", "depth", "path"] if c in file_cols]
                sort_cols_file = st.multiselect(
                    "ソート列（上から優先）",
                    options=file_cols,
                    default=default_file_cols,
                    key="sort_cols_file",
                    help="複数選択可。上にある列ほど優先度が高くなります。",
                )
                asc_file = st.checkbox("昇順（全列一括）", value=True, key="asc_file")

            # 指定がなければ（安全側で）ext→name→depth→path の順
            df_file_show = df_files_filtered.sort_values(
                sort_cols_file or default_file_cols or ["path"],
                ascending=asc_file,
                kind="mergesort",
            )
            st.dataframe(df_file_show, width="stretch", height=420)
            st.download_button(
                "⬇️ ファイル一覧をCSVで保存",
                data=df_file_show.to_csv(index=False).encode("utf-8-sig"),
                file_name=(
                    f"files_depth_upto_{max_depth}.csv"
                    if SUBROOT is None
                    else f"files_from_{str(SUBROOT.relative_to(ROOT)).replace('/', '__')}_depth_upto_{max_depth}.csv"
                ),
                mime="text/csv",
            )
        else:
            st.info("条件に一致するファイルは見つかりませんでした。")

# 初期ヒント（探索未実行時）
if not run:
    st.caption("［ヒント］大規模ディレクトリでは、まず深さと表示上限を小さめに設定して挙動確認すると安全です。")

# 注記（I/O コストに関する注意を明示）
st.caption("※ 直下件数の計算は非再帰。必要時のみ有効化してください。")
