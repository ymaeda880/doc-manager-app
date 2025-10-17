"""
pages/10_フォルダービュア.py
============================================
📂 Folder Viewer — ラジオ→ボタングリッド→次階層プレビュー（1→2→3→4階層）
- 深さ1: ラジオ（単一選択）※従来どおり
- 深さ2/3: ✅トグル式のボタングリッド（4列）
- 深さ4: DataFrame表示＋CSV保存
"""

from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, List, Set
import datetime as dt
import pandas as pd
import streamlit as st

# パス設定
from lib.app_paths import PATHS
from lib.fsnav.scan import safe_stat_mtime, listdir_counts, iter_dirs



# ------------------------------------------------------------
# ページ設定
# ------------------------------------------------------------
st.set_page_config(page_title="Folder Viewer (1→2→3→4)", page_icon="📂", layout="wide")
st.title("📂 Folder Viewer — 1→2→3→4 階層プレビュー")

# ------------------------------------------------------------
# 基点ルート選択
# ------------------------------------------------------------
_ORG = getattr(PATHS, "original_docs_root", None)
_ORZ = getattr(PATHS, "organized_docs_root", None)
root_options = []
if _ORG is not None:
    root_options.append(("original_docs_root", str(_ORG)))
if _ORZ is not None:
    root_options.append(("organized_docs_root", str(_ORZ)))

if not root_options:
    st.error("PATHS.original_docs_root / organized_docs_root が未設定です。")
    st.stop()

selected_key = st.radio(
    "基点ルートを選択",
    options=[k for k, _ in root_options],
    index=0,
    horizontal=True,
)
ROOT = Path(dict(root_options)[selected_key]).expanduser().resolve()

if not ROOT.exists():
    st.error(f"{ROOT} が存在しません。マウントを確認してください。")
    st.stop()

# ------------------------------------------------------------
# サイドバー
# ------------------------------------------------------------
with st.sidebar:
    st.header("設定")
    st.caption(f"実パス: `{ROOT}`")
    compute_counts = st.checkbox("直下件数を計算", value=False)

    # ▼ 追加：グリッド列数（＝1行あたりのボタン数）を可変に
    st.subheader("グリッド列数（1行のボタン数）")
    grid_cols_l2 = st.slider("深さ2の列数", min_value=1, max_value=12, value=8, step=1)
    grid_cols_l3 = st.slider("深さ3の列数", min_value=1, max_value=10, value=4, step=1)

# ------------------------------------------------------------
# ユーティリティ
# ------------------------------------------------------------
def list_subdirs_once_unfiltered(base: Path) -> List[Path]:
    """隠し・フィルタ無視で base 直下のディレクトリのみ列挙"""
    if not base.exists() or not base.is_dir():
        return []
    return sorted([p for p in base.iterdir() if p.is_dir()], key=lambda x: x.name.lower())

def make_rows_for_dirs(paths: List[Path], parent_rel: str) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for p in paths:
        m = safe_stat_mtime(p)
        files_cnt, dirs_cnt = listdir_counts(p) if compute_counts else (None, None)
        rows.append(
            {
                "path": str(p.relative_to(ROOT)),
                "name": p.name,
                "parent": parent_rel,
                "modified": dt.datetime.fromtimestamp(m) if m else None,
                "files_direct": files_cnt,
                "dirs_direct": dirs_cnt,
            }
        )
    df = pd.DataFrame(rows).sort_values(["path"]) if rows else pd.DataFrame(
        columns=["path", "name", "parent", "modified", "files_direct", "dirs_direct"]
    )
    return df

# ------------------------------------------------------------
# ✅ 追加ユーティリティ：複数選択ボタングリッド
# ------------------------------------------------------------
def multiselect_button_grid(
    options: List[str],
    *,
    selected: Set[str],
    state_prefix: str,
    cols: int = 4,
    mark_selected: bool = True,
) -> Set[str]:
    """
    チェックボックス代替：ボタンをグリッド状に並べて複数選択トグル
    - options: 表示する選択肢（str）
    - selected: 現在選択済み（set）。本関数内で直接更新される
    - state_prefix: st.button の key 接頭辞（安定化用）
    - cols: 列数（デフォルト4列）
    - mark_selected: True なら選択中に ✅ を付ける
    """
    for i in range(0, len(options), cols):
        row = options[i:i + cols]
        cols_ui = st.columns(len(row))
        for j, opt in enumerate(row):
            is_selected = opt in selected
            # ラベルは最後のパス要素を見やすく表示（name中心）しつつ、選択時は✅
            label_text = Path(opt).name
            label = f"✅ {label_text}" if (mark_selected and is_selected) else label_text
            if cols_ui[j].button(label, key=f"{state_prefix}__{opt}"):
                if is_selected:
                    selected.discard(opt)
                else:
                    selected.add(opt)
    return selected

# ------------------------------------------------------------
# セッション状態（選択の保持）
# ------------------------------------------------------------
# 深さ2の選択（set[str] / ROOT からの相対パス）
if "fv_checked_l2" not in st.session_state:
    st.session_state["fv_checked_l2"] = set()
# 深さ3の選択（dict[str -> set[str]]）キー=深さ2相対パス、値=深さ3相対パスの集合
if "fv_checked_l3" not in st.session_state:
    st.session_state["fv_checked_l3"] = {}

CHECKED_L2: Set[str] = st.session_state["fv_checked_l2"]
CHECKED_L3: Dict[str, Set[str]] = st.session_state["fv_checked_l3"]

# ------------------------------------------------------------
# メイン機能：ラジオ→（深さ2/3はボタングリッド）→深さ4プレビュー
# ------------------------------------------------------------
# 深さ1のフォルダを取得（表は出さず、ラジオのみ）
level1_paths: List[Path] = list(iter_dirs(ROOT, max_depth=1, ignore_hidden=True))
lvl1_labels = [str(p.relative_to(ROOT)) for p in sorted(level1_paths)]

if not lvl1_labels:
    st.info("深さ1のサブフォルダが見つかりません。")
else:
    RADIO_KEY = "fv_lvl1_radio"

    selected_lvl1_label = st.radio(
        "深さ1（ROOT直下）のフォルダを1つ選択",
        options=lvl1_labels,
        index=0,
        key=RADIO_KEY,
    )
    selected_lvl1_path = ROOT / selected_lvl1_label

    # 深さ2（無条件列挙）— 折りたたみ
    lvl2_dirs = list_subdirs_once_unfiltered(selected_lvl1_path)
    if not lvl2_dirs:
        st.info("深さ2フォルダがありません。")
    else:
        with st.expander(f"深さ2（{selected_lvl1_label} 直下） — {len(lvl2_dirs):,} 件", expanded=False):
            c_all, c_none, c_cnt = st.columns([1, 1, 2])
            with c_all:
                if st.button("全選択", key="btn_l2_all"):
                    CHECKED_L2.clear()
                    CHECKED_L2.update(str(p.relative_to(ROOT)) for p in lvl2_dirs)
            with c_none:
                if st.button("全解除", key="btn_l2_none"):
                    CHECKED_L2.clear()
            with c_cnt:
                st.caption(f"選択数: {len(CHECKED_L2)} / {len(lvl2_dirs):,}")

            # ✅ 深さ2：チェックボックス → ボタングリッド（4列）へ変更
            rel2_list = [str(d.relative_to(ROOT)) for d in lvl2_dirs]
            CHECKED_L2 = multiselect_button_grid(
                rel2_list,
                selected=CHECKED_L2,
                state_prefix="btn_l2",
                cols=grid_cols_l2,
            )

            # 深さ2の選択に連動して、外れたものの深さ3選択は安全に削除
            for k in list(CHECKED_L3.keys()):
                if k not in CHECKED_L2:
                    CHECKED_L3.pop(k, None)

        st.divider()

        # 深さ3（深さ2で選択された各フォルダの直下）— 折りたたみ＋ボタングリッド → 深さ4表示
        selected_lvl2_labels: List[str] = sorted(CHECKED_L2)
        if not selected_lvl2_labels:
            st.info("深さ2のフォルダが選択されていません。ボタンで選択してください。")
        else:
            st.markdown("### 深さ3 / 深さ4")
            for rel2 in selected_lvl2_labels:
                d2 = ROOT / rel2
                d3_subs = list_subdirs_once_unfiltered(d2)

                # 深さ3の選択集合を初期化
                selected_set_for_l2 = CHECKED_L3.setdefault(rel2, set())

                with st.expander(f"📁 {rel2} — 深さ3: {len(d3_subs)} 件", expanded=False):
                    c3_all, c3_none, c3_cnt = st.columns([1, 1, 2])
                    with c3_all:
                        if st.button("全選択", key=f"btn_l3_all__{rel2}"):
                            selected_set_for_l2.clear()
                            selected_set_for_l2.update(str(p.relative_to(ROOT)) for p in d3_subs)
                    with c3_none:
                        if st.button("全解除", key=f"btn_l3_none__{rel2}"):
                            selected_set_for_l2.clear()
                    with c3_cnt:
                        st.caption(f"選択数: {len(selected_set_for_l2)} / {len(d3_subs)}")

                    # ✅ 深さ3：チェックボックス → ボタングリッド（4列）へ変更
                    rel3_list = [str(p.relative_to(ROOT)) for p in d3_subs]
                    CHECKED_L3[rel2] = multiselect_button_grid(
                        rel3_list,
                        selected=selected_set_for_l2,
                        state_prefix=f"btn_l3_{rel2}",
                        cols=grid_cols_l3, 
                    )

                    # === 深さ4（深さ3でチェックされたフォルダ 直下） ===
                    if CHECKED_L3[rel2]:
                        st.markdown("**深さ4（チェックした深さ3 直下のフォルダ）**")
                        for rel3 in sorted(CHECKED_L3[rel2]):
                            d3 = ROOT / rel3
                            d4_subs = list_subdirs_once_unfiltered(d3)
                            with st.expander(f"└─ {rel3} — 深さ4: {len(d4_subs)} 件", expanded=False):
                                if not d4_subs:
                                    st.write("（深さ4なし）")
                                else:
                                    df4 = make_rows_for_dirs(d4_subs, parent_rel=rel3)
                                    st.dataframe(df4, width="stretch", height=280)
                                    st.download_button(
                                        f"⬇️ CSV保存（{rel3} 直下の深さ4）",
                                        data=df4.to_csv(index=False).encode("utf-8-sig"),
                                        file_name=f"depth4__{rel3.replace('/', '__')}.csv",
                                        mime="text/csv",
                                        key=f"dl_depth4__{rel3}",
                                    )

st.caption("※ 表示はすべて“直下のサブフォルダのみ”（フィルタ無効）。深さ2/3はボタンで✅トグルしながら段階的に掘り下げます。")
