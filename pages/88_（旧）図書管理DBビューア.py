# pages/40_図書管理DBビューア.py
# ------------------------------------------------------------
# 📚 図書管理DB ビューア & 検索
# - PATHS.library_root から Excel を読み込み（既定: 図書館DB.xlsx → 図書管理DB.xlsx）
# - 文字列の横断キーワード検索（AND/OR, 大文字小文字）
# - 代表カラム（タイトル/著者/分類/出版年/状態 等）を推定（絞り込みUIに活用）
# - 表示列の選択、並び替え、CSV/Excel ダウンロード
# - シート選択（複数シート対応）
# - ファイルアップロードで一時差し替え
# - 横スクロール優先（Data Editor）/ 高速表示（DataFrame）を切替可能
# - 年範囲は select_slider で端ラベルの見切れを回避
# - 発行年が4桁でない行は並び替えで末尾に回す
# - 開発時は先頭 N 件のみ読む（全件読み込みも選択可）
# - ★ 新機能: 指定7カラムだけを一発で表示するボタンを追加
#   （登録番号, タイトル, キーワード, 編・著者名, 発行社名, 発行年, 修正日）
# - ★ 仕様変更: ピンポイント検索（ISBN/請求記号）は省略
# ------------------------------------------------------------
from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import io
import re

import pandas as pd
import streamlit as st

from lib.app_paths import PATHS

st.set_page_config(page_title="図書管理DB ビューア", page_icon="📚", layout="wide")
st.title("📚 図書管理DB ビューア & 検索")

# ========= パスと既定ファイル解決 =========
LIB_ROOT = Path(PATHS.library_root)
DEFAULT_CANDIDATES = ["図書館DB.xlsx", "図書管理DB.xlsx"]

def _pick_default_xlsx(root: Path) -> Optional[Path]:
    for name in DEFAULT_CANDIDATES:
        p = (root / name)
        if p.exists():
            return p
    xs = sorted(root.glob("*.xlsx"))
    return xs[0] if xs else None

# ========= キャッシュ付き読み込み =========
@st.cache_data(show_spinner=True)
def load_excel(path_or_bytes, sheet_name: Optional[str]) -> Tuple[pd.DataFrame, List[str]]:
    """Excelを読み込み、(df, シート名一覧) を返す。"""
    if isinstance(path_or_bytes, (str, Path)):
        xls = pd.ExcelFile(path_or_bytes)  # engine 自動（openpyxl）
    else:
        xls = pd.ExcelFile(io.BytesIO(path_or_bytes))
    sheets = xls.sheet_names
    target_sheet = sheet_name if (sheet_name in sheets) else sheets[0]
    df = xls.parse(target_sheet, dtype=str)  # 文字列として読み込み→検索が安定
    # 前後空白除去（applymap は将来非推奨なので map 互換で）
    for c in df.columns:
        df[c] = df[c].map(lambda x: x.strip() if isinstance(x, str) else x)
    return df, sheets

# ========= カラム推定（よくある日本語名） =========
CAND = {
    "title": {"タイトル","書名","題名","Title","タイトル名"},
    "author": {"著者","作者","編者","Author","編・著者名"},
    "publisher": {"発行社名","出版社","発行","Publisher","発行所"},
    "year": {"発行年","出版年","刊行年","発行年月","Year"},
    "category": {"分類","カテゴリ","カテゴリー","NDC","ジャンル"},
    "status": {"状態","ステータス","貸出状況","在庫","Availability"},
    "id": {"登録番号","登録No.","登録番号（社内）","ID","管理番号"},
    "keyword": {"キーワード","KW","Keywords"},
    "updated": {"修正日","更新日","最終更新"},
}

def pick_cols(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    cols = list(df.columns)
    found: Dict[str, Optional[str]] = {k: None for k in CAND}
    for key, candidates in CAND.items():
        for c in cols:
            if c in candidates:
                found[key] = c
                break
    return found

# 年抽出（4桁だけ返す、なければ None）
def _extract_year(v) -> Optional[int]:
    if v is None:
        return None
    s = str(v)
    m = re.search(r"(\d{4})", s)
    if not m:
        return None
    y = int(m.group(1))
    if 1000 <= y <= 2100:
        return y
    return None

# ========= サイドバー =========
with st.sidebar:
    st.header("📂 データソース")
    st.caption(f"library_root: {LIB_ROOT}")
    default_path = _pick_default_xlsx(LIB_ROOT)
    path_text = st.text_input(
        "Excel ファイルパス",
        value=str(default_path or (LIB_ROOT / "図書館DB.xlsx"))
    ).strip()
    uploaded = st.file_uploader("一時的に別ファイルを使う（.xlsx）", type=["xlsx"])

    # 読み込み
    try:
        if uploaded is not None:
            df0, sheets = load_excel(uploaded.getvalue(), sheet_name=None)
            current_source = f"(uploaded) {uploaded.name}"
        else:
            target_path = Path(path_text).expanduser().resolve()
            if not target_path.exists():
                st.error(f"ファイルが見つかりません: {target_path}")
                st.stop()
            df0, sheets = load_excel(str(target_path), sheet_name=None)
            current_source = str(target_path)
    except Exception as e:
        st.error(f"Excel 読み込みに失敗しました: {e}")
        st.stop()

    # 開発時の読み込み件数制限
    DEV_MAX_ROWS = st.number_input("先頭 N 件だけ読む（0で全件）", 0, 100_000, 500, 50)
    sheet = st.selectbox("シート", sheets, index=0)

    # 指定シートで再読込（キャッシュは効く）
    if uploaded is not None:
        df, _ = load_excel(uploaded.getvalue(), sheet)
    else:
        df, _ = load_excel(str(Path(current_source)), sheet)

    if DEV_MAX_ROWS and len(df) > DEV_MAX_ROWS:
        df = df.head(int(DEV_MAX_ROWS))

    st.caption(f"読み込み元: {current_source}")

    st.divider()
    st.header("🔎 検索・絞り込み")

    # カラム推定
    COL = pick_cols(df)

    # 検索対象列（既定は代表列）
    default_search_cols = [c for c in [COL.get("title"), COL.get("author"), COL.get("publisher"), COL.get("keyword")] if c]
    search_cols = st.multiselect(
        "キーワード検索の対象列",
        options=list(df.columns),
        default=default_search_cols or list(df.columns)[:4]
    )

    q = st.text_input("キーワード（空白区切り）", value="")
    mode = st.radio("モード", ["AND", "OR"], index=0, horizontal=True)
    case_sensitive = st.checkbox("大文字小文字を区別", value=False)
    use_regex = st.checkbox("正規表現", value=False)

    # よく使う絞り込み（年）
    st.subheader("よく使う絞り込み（カラムがあれば表示）")

    filters: Dict[str, object] = {}

    # 年範囲（select_slider で端ラベル見切れ回避）
    if COL.get("year"):
        years_extracted = sorted(
            {y for y in (_extract_year(v) for v in df[COL["year"]].dropna().unique()) if y is not None}
        )
        if years_extracted:
            y_min, y_max = years_extracted[0], years_extracted[-1]
            st.caption(f"範囲（最小/最大）: **{y_min} – {y_max}**")
            sel_y1, sel_y2 = st.select_slider(
                f"{COL['year']} 範囲",
                options=years_extracted,
                value=(y_min, y_max),
                label_visibility="visible",
            )
            st.caption(f"選択中: **{sel_y1} – {sel_y2}**")
            filters["year_range"] = (sel_y1, sel_y2)

    # 表示設定
    st.divider()
    st.header("表示設定")

    # 表示列の初期値：代表列があればそれを、なければ先頭8列
    default_show_cols = [c for c in [
        COL.get("id"), COL.get("title"), COL.get("keyword"),
        COL.get("author"), COL.get("publisher"),
        COL.get("year"), COL.get("updated")
    ] if c] or list(df.columns)[:8]

    # セッションに現在の選択を保持
    if "lib_show_cols" not in st.session_state:
        st.session_state["lib_show_cols"] = default_show_cols

    # ★ ワンクリックで7カラムにするボタン
    LIB_STD_SET = ["登録番号","タイトル","キーワード","編・著者名","発行社名","発行年","修正日"]
    if st.button("📋 指定7カラムだけ表示（登録番号/タイトル/…/修正日）"):
        # 実データに存在するものだけに絞る
        st.session_state["lib_show_cols"] = [c for c in LIB_STD_SET if c in df.columns]

    show_cols = st.multiselect(
        "表示列", list(df.columns),
        default=st.session_state["lib_show_cols"]
    )
    # 保存
    st.session_state["lib_show_cols"] = show_cols

    sort_cols = st.multiselect(
        "並び替えキー", list(df.columns),
        default=[COL["title"]] if COL.get("title") else []
    )
    ascending = st.checkbox("昇順で並べ替え", value=True)

    # 表の表示方法
    view_mode = st.radio("表の表示方法", ["高速表示（DataFrame）", "横スクロール優先（Data Editor）"], index=1)
    col_width = st.slider("列幅(px)（Data Editor時）", 80, 400, 160, 10)

# ========= 検索適用 =========
def _match_keywords(val: str, pats: List[re.Pattern], mode: str) -> bool:
    s = "" if val is None else str(val)
    if mode == "AND":
        return all(p.search(s) for p in pats)
    return any(p.search(s) for p in pats)

# 1) キーワード検索
if q.strip():
    tokens = [t for t in q.split() if t.strip()]
    flags = 0 if case_sensitive else re.IGNORECASE
    pats = []
    for t in tokens:
        try:
            pats.append(re.compile(t if use_regex else re.escape(t), flags))
        except re.error:
            pats.append(re.compile(re.escape(t), flags))
    mask = pd.Series(False, index=df.index)
    for col in (search_cols or df.columns):
        mask = mask | df[col].astype(str).apply(lambda s: _match_keywords(s, pats, mode))
    df = df[mask]

# 2) 年範囲
if filters.get("year_range") and COL.get("year"):
    y1, y2 = filters["year_range"]
    def _in_range(v) -> bool:
        y = _extract_year(v)
        return (y is not None) and (y1 <= y <= y2)
    df = df[df[COL["year"]].apply(_in_range)]

# 3) 並び替え（発行年は4桁化したキーで末尾送りを実現）
if sort_cols:
    def _year_key(s):
        y = _extract_year(s)
        # None を末尾へ（tuple の 1番目で制御）
        return (1, "") if y is None else (0, y)
    try:
        by = []
        for c in sort_cols:
            if COL.get("year") == c:
                by.append(df[c].map(_year_key))
            else:
                by.append(df[c].astype(str))
        df = df.assign(**{f"__sort{i}": by[i] for i in range(len(by))})
        df = df.sort_values([f"__sort{i}" for i in range(len(by))], ascending=ascending, na_position="last")
        df = df.drop(columns=[c for c in df.columns if c.startswith("__sort")])
    except Exception:
        pass

# ========= 概要・DL =========
st.metric("ヒット件数", f"{len(df):,}")

# 表示列確定
cols_to_show = [c for c in (show_cols or list(df.columns)) if c in df.columns]
if not cols_to_show:
    cols_to_show = list(df.columns)

# 表表示
if view_mode.startswith("横スクロール"):
    col_cfg = {c: st.column_config.Column(width=int(col_width)) for c in cols_to_show}
    st.data_editor(
        df[cols_to_show],
        width="stretch",
        height=520,
        disabled=True,
        hide_index=True,
        column_config=col_cfg,
        key="lib_de",
    )
else:
    st.dataframe(df[cols_to_show], width="stretch", height=520)

# ダウンロード
c1, c2 = st.columns(2)
with c1:
    csv_bytes = df[cols_to_show].to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "📥 CSV をダウンロード",
        data=csv_bytes,
        file_name="library_filtered.csv",
        mime="text/csv",
        width="stretch",
    )
with c2:
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="xlsxwriter") as writer:
        df[cols_to_show].to_excel(writer, index=False, sheet_name="filtered")
    st.download_button(
        "📥 Excel をダウンロード",
        data=out.getvalue(),
        file_name="library_filtered.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )

# ========= 代表カラムが見つからない場合のヒント =========
missing = []
for k in ["id","title","keyword","author","publisher","year","updated"]:
    if k not in CAND: 
        continue
    if not pick_cols(df).get(k):
        missing.append(k)

if missing:
    with st.expander("ℹ️ カラム自動推定について（不足あり）"):
        st.write("以下の代表カラムが見つかりませんでした。列名を次のいずれかへ近づけるとUIがより便利になります。")
        for k in missing:
            st.write(f"- **{k}** 候補: {sorted(list(CAND[k]))}")
