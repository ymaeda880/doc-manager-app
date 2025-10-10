"""
pages/20_report整理.py
============================================
📂 report 整理（original_docs_root/report 配下の一覧）

このページでできること（処理の流れ）
------------------------------------
① 深さ1のフォルダ一覧（`original_docs_root/report` 直下のみ）
    - 隠しフォルダの除外や、直下 files/dirs 件数の取得を選択可能
    - 一覧は DataFrame で表示

② フォルダ名を規則で「年 / プロジェクト番号」に分類
    - 7桁数値: `YYYYPPP`（YYYY=年, PPP=プロジェクト番号）
    - `HNNPPP`: 平成 → 西暦は `1988 + NN`
    - `SNNPPP`: 昭和 → 西暦は `1925 + NN`
    - `P...`   : 図書館管理（年=9999, PNo=999）として一旦プレースホルダ
    - 上記以外は `other` として年なし
    - ★ 年ごとのエキスパンダーにチェックボックスを付与。
      ここでチェックした **年** を ④ の対象年として利用します。

③ Library(P) フォルダ → 図書管理DB（Excel: Sheet1）で年を補足分類
    - Library(P) フォルダ内の PDF（直下のみ対象）について
      先頭「登録番号-……」から「登録番号」を取り出し、DB で「発行年」を検索
    - 発行年の表記ゆれ（1981/3, 1977.2, 全角数字等）を正規化して 4 桁年に整形
    - 取得できない or 不正は `9999` とする
    - ★ 年ごとのエキスパンダーにチェックボックスを付与（選択状態は保存。処理は後で追加）。

④ ②で選択した年 → <ベース>/report/pdf/<年>/<pno>/ へ PDF コピー
    - ②でチェックした「年」だけを対象
    - 対象ソース: その年の **7桁数値フォルダ（YYYYPPP）**
    - コピー先: `<ベース>/report/pdf/<年>/<pno>/`（例: `ExtremeSSD/report/pdf/2020/123/`）
    - 既存同名ファイルはスキップ
"""

from __future__ import annotations
from pathlib import Path
from typing import Iterator, Dict, Any, List
import os
import re
import shutil
import datetime as dt

import streamlit as st
import pandas as pd

from lib.app_paths import PATHS
from lib.fsnav.scan import iter_dirs, safe_stat_mtime, listdir_counts

# 任意：PDFの軽量種別（現状未使用でもOK）
try:
    from lib.pdf.info import quick_pdf_info  # noqa: F401
except Exception:
    quick_pdf_info = None


# ========== ページ設定 ==========
st.set_page_config(page_title="report 整理", page_icon="📂", layout="wide")

st.title("📂 report 整理 — original_docs_root/report 配下の一覧")

st.info("使用ルート：original_docs_root -> organized_docs_root")

st.markdown("""
### ② フォルダ名を規則で「年 / プロジェクト番号」に分類
- 7桁数値: `YYYYPPP`（YYYY=年, PPP=プロジェクト番号）  
- `HNNPPP`: 平成 → 西暦は `1988 + NN`  
- `SNNPPP`: 昭和 → 西暦は `1925 + NN`  
- `P...`   : 図書館管理（年=9999, PNo=999）として一旦プレースホルダ  
- 上記以外は `other` として年なし  
- ★ 年ごとのエキスパンダーにチェックボックスを付与。  
  ここでチェックした **年** を ④ の対象年として利用します。

---

### ④ ②で選択した年 → `<ベース>/report/pdf/<年>/<pno>/` へ PDF コピー
- ②でチェックした「年」だけを対象  
- 対象ソース: その年の **7桁数値フォルダ（YYYYPPP）**  
- コピー先: `<ベース>/report/pdf/<年>/<pno>/`  
  （例: `ExtremeSSD/report/pdf/2020/123/`）  
- 既存同名ファイルはスキップ
""")

# ========== 起点 ==========
ROOT_BASE = Path(str(PATHS.original_docs_root)).expanduser().resolve()
REPORT_ROOT_DEFAULT = ROOT_BASE / "report"
report_text = st.text_input("report の実パス（変更不要なら既定のまま）", value=str(REPORT_ROOT_DEFAULT))
REPORT_ROOT = Path(report_text).expanduser().resolve()

if not REPORT_ROOT.exists():
    st.error("original_docs_root/report が見つかりません。PATHS を確認してください。")
    st.stop()

# ========== サイドバー ==========
with st.sidebar:
    st.header("設定")
    st.caption(f"実パス: `{REPORT_ROOT}`")
    c = st.columns(2)
    with c[0]:
        ignore_hidden = st.checkbox("隠しフォルダを除外", value=True)
    with c[1]:
        compute_counts = st.checkbox("直下の件数を計算", value=False)
    st.divider()
    st.subheader("① フィルタ")
    name_filter = st.text_input("名称の部分一致（大文字小文字を無視）", value="").strip()


# ========== ① 深さ1のフォルダ一覧 ==========
st.subheader("① 深さ1のフォルダ一覧（report 直下）")
st.markdown(
    """
    📌 **説明**  
    - 深さ1のフォルダ一覧（`original_docs_root/report` 直下のみ）
    - 隠しフォルダの除外や、直下 files/dirs 件数の取得を選択可能
    - 一覧は DataFrame で表示 
    """,
    unsafe_allow_html=True
)
rows_lvl1: List[Dict[str, Any]] = []
level1_paths: List[Path] = []

for d in iter_dirs(REPORT_ROOT, max_depth=1, ignore_hidden=ignore_hidden):
    level1_paths.append(d)
    nm = d.name
    if name_filter and (name_filter.lower() not in nm.lower()):
        continue
    mtime = safe_stat_mtime(d)
    fcnt, dcnt = listdir_counts(d) if compute_counts else (None, None)
    rows_lvl1.append({
        "path": str(d.relative_to(REPORT_ROOT)),
        "name": nm,
        "depth": 1,
        "modified": dt.datetime.fromtimestamp(mtime) if mtime else None,
        "files_direct": fcnt,
        "dirs_direct": dcnt,
    })

if rows_lvl1:
    df1 = pd.DataFrame(rows_lvl1).sort_values("path")
    st.dataframe(df1, width="stretch", height=300)
else:
    st.info("フォルダが見つかりません。")

st.divider()


# ========== ② フォルダ名 → 年/プロジェクト番号分類 ==========
st.subheader("② フォルダ名の分類（年 / プロジェクト番号）")
st.markdown(
    """
    📌 **説明**  
    - フォルダ名を規則で「年 / プロジェクト番号」に分類
    - ここで **年ごとのチェックボックス** を付けました。  
      ✅ チェックした **年** が ④ の対象になります。
      9999年は図書管理DB扱い
    """,
    unsafe_allow_html=True
)

def _parse_folder_name(name: str) -> Dict[str, Any]:
    """フォルダ名から年/プロジェクト番号/カテゴリを抽出。"""
    # (i) 7桁: YYYYPPP
    m = re.fullmatch(r"(\d{4})(\d{3})", name)
    if m:
        return {"name": name, "category": "numeric7", "year": int(m[1]), "pno": int(m[2])}
    # (ii) Heisei: HNNPPP
    m = re.fullmatch(r"H(\d{2})(\d{3})", name, re.I)
    if m:
        return {"name": name, "category": "Heisei", "year": 1988 + int(m[1]), "pno": int(m[2])}
    # (iii) Showa: SNNPPP
    m = re.fullmatch(r"S(\d{2})(\d{3})", name, re.I)
    if m:
        return {"name": name, "category": "Showa", "year": 1925 + int(m[1]), "pno": int(m[2])}
    # (iv) P*
    if re.match(r"^P", name, re.I):
        return {"name": name, "category": "Library(P)", "year": 9999, "pno": 999}
    # (v) その他
    return {"name": name, "category": "other", "year": None, "pno": None}

# ①の結果 rows_lvl1 を分類
parsed_rows: List[Dict[str, Any]] = []
for row in rows_lvl1:
    info = _parse_folder_name(row["name"])
    info["path"] = row["path"]
    parsed_rows.append(info)

# 選択された年の状態を保持する入れ物（②用）
if "selected_years_for_copy" not in st.session_state:
    st.session_state["selected_years_for_copy"] = set()

# 年ごと表示（年ヘッダにチェックボックス）
if not parsed_rows:
    st.info("分類対象のフォルダがありません。")
else:
    grouped: Dict[Any, List[Dict[str, Any]]] = {}
    for item in parsed_rows:
        year = item["year"] if item["year"] is not None else "その他"
        grouped.setdefault(year, []).append(item)

    for year, items in sorted(grouped.items(), key=lambda x: str(x[0])):
        # 年ヘッダのチェックボックス（ここで選んだ年を ④ に反映）
        year_key = f"year_pick_{year}"
        init = (year in st.session_state["selected_years_for_copy"])
        picked = st.checkbox(f"📅 年: {year}（{len(items)} 件）", key=year_key, value=init)

        if picked:
            st.session_state["selected_years_for_copy"].add(year)
        else:
            st.session_state["selected_years_for_copy"].discard(year)

        # 年ごとの詳細リストは expander で折り畳み
        with st.expander(f"{year} のフォルダ一覧", expanded=False):
            for it in sorted(items, key=lambda x: (x["pno"] if x["pno"] is not None else 999999, x["name"])):
                pn = "—" if it["pno"] is None else f"{it['pno']}"
                st.markdown(f"- **{it['name']}** ｜ PNo:{pn} 〔{it['category']}〕")

st.divider()


# ========== ③ Library(P) → 図書管理DB で年を補足 ==========
st.subheader("③ 図書管理DBによる分類補足（Library(P) フォルダ）")
st.markdown(
    """
    📌 **説明**  
    - Library(P) フォルダ → 図書管理DB（Excel: Sheet1）で年を補足分類  
    - 本セクションでも **年ごとのエキスパンダーにチェックボックス** を付け、選択状態を保存します（後続処理は後で追加）。  
    - ここでの **pno は「登録番号の下3桁」** を採用します。  
    """,
    unsafe_allow_html=True
)

LIB_DB_PATH = Path(PATHS.library_root).expanduser().resolve() / "図書管理DB.xlsx"

# 発行年の正規化
_ZEN = "０１２３４５６７８９"
_HAN = "0123456789"
Z2H = str.maketrans(_ZEN, _HAN)

def parse_year_field(val) -> int:
    """Excel『発行年』から4桁年を抽出。失敗時は 9999。"""
    if pd.isna(val):
        return 9999
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        try:
            y = int(val)
            return y if 1800 <= y <= 2100 else 9999
        except Exception:
            pass
    s = str(val).strip().translate(Z2H)
    m = re.search(r"(\d{4})", s)
    if m:
        y = int(m.group(1))
        return y if 1800 <= y <= 2100 else 9999
    return 9999

lib_parsed_rows: List[Dict[str, Any]] = []

if LIB_DB_PATH.exists():
    try:
        df_lib = pd.read_excel(
            LIB_DB_PATH, sheet_name="Sheet1",
            dtype={"登録番号": "string", "発行年": "string"}
        )
        df_lib["登録番号"] = df_lib["登録番号"].astype("string").str.strip()
        df_lib["発行年_norm"] = df_lib["発行年"].map(parse_year_field)
        regno_to_year: Dict[str, int] = (
            df_lib[["登録番号", "発行年_norm"]]
            .dropna()
            .set_index("登録番号")["発行年_norm"]
            .to_dict()
        )

        # Library(P) と判定されたフォルダのみ処理
        for row in parsed_rows:
            if row["category"] != "Library(P)":
                continue
            folder_path = (REPORT_ROOT / row["path"]).resolve()
            if not folder_path.exists():
                continue

            # フォルダ直下の PDF を列挙
            for pdf in folder_path.glob("*.pdf"):
                # ファイル名先頭「登録番号-…」から登録番号を抽出
                m = re.match(r"(\d+)-", pdf.name)
                if not m:
                    continue
                regno = m.group(1)

                # 図書DBから発行年を引く（見つからなければ 9999）
                year = regno_to_year.get(regno, 9999)

                # ★ pno は「登録番号の下3桁」
                pno_last3 = 999
                if regno.isdigit():
                    pno_last3 = int(regno[-3:])

                lib_parsed_rows.append({
                    "name": pdf.name,
                    "category": "Library(P)-DB",
                    "year": year,
                    "pno": pno_last3,                        # ← ここが変更点
                    "path": str(pdf.relative_to(REPORT_ROOT)),
                })

    except Exception as e:
        st.error(f"図書管理DBの読み込みに失敗しました: {e}")
else:
    st.warning(f"図書管理DBが見つかりません: `{LIB_DB_PATH}`")

# ③の選択状態を保持（年単位）
if "selected_years_libdb" not in st.session_state:
    st.session_state["selected_years_libdb"] = set()

# --- ③の結果表示（年ごとに展開・年見出しにチェックボックス付き） ---
if lib_parsed_rows:
    grouped2: Dict[int, List[Dict[str, Any]]] = {}
    for item in lib_parsed_rows:
        grouped2.setdefault(item["year"], []).append(item)

    for year, items in sorted(grouped2.items(), key=lambda x: str(x[0])):
        # 年見出しチェックボックス（状態のみ保持。処理は後で追加）
        key_y = f"libdb_year_pick_{year}"
        init_y = (year in st.session_state["selected_years_libdb"])
        picked_y = st.checkbox(f"📚（DB）年: {year}（{len(items)} 件）", key=key_y, value=init_y)
        if picked_y:
            st.session_state["selected_years_libdb"].add(year)
        else:
            st.session_state["selected_years_libdb"].discard(year)

        with st.expander(f"{year} の PDF 一覧（Library補足）", expanded=False):
            for it in sorted(items, key=lambda x: (x["pno"], x["name"])):
                st.markdown(f"- **{it['name']}** ｜ PNo:{it['pno']:03d} 〔{it['category']}〕")
else:
    st.info("Library(P) に該当し、DBで年が引けたPDFはありません。")

st.divider()


# ========== ④ ②で選択した年の <年>/<pno>/ へ PDF コピー ==========
st.subheader("④ ②で選択した年のフォルダへ PDF コピー（<ベース>/report/pdf/<年>/<pno>/）")
st.markdown(
    """
    📌 **説明**  
    - ②でチェックした **年** のみを対象にします。  
    - 対象ソースは、その年の **7桁数値フォルダ（YYYYPPP 例: 2020xxx）** です。  
    - コピー先: `<ベース>/report/pdf/<年>/<pno>/` （例: `ExtremeSSD/report/pdf/2020/123/`）。  
    - 既存同名ファイルはスキップします（ファイルの上書きはしない）。  
    """,
    unsafe_allow_html=True
)

# ②で選ばれた年の表示（バッジ風）
picked_years = sorted(st.session_state.get("selected_years_for_copy", set()), key=str)
if picked_years:
    chips = " ".join([
        f"<span style='padding:2px 8px;border:1px solid #ddd;border-radius:12px;margin-right:6px;'>{y}</span>"
        for y in picked_years
    ])
    st.markdown(f"**対象年:** {chips}", unsafe_allow_html=True)
else:
    st.info("②で対象年をチェックしてください。")

# コピー先ベース（例: ExtremeSSD/report/pdf）
dest_base_text = st.text_input(
    "コピー先ベース（既定：organized_docs_root/report/pdf）",
    value=str((Path(PATHS.organized_docs_root).expanduser().resolve() / "report" / "pdf"))
)
DEST_BASE = Path(dest_base_text).expanduser().resolve()
st.caption(f"コピー先ベース: `{DEST_BASE}`")

def _iter_pdfs_under(folder: Path, *, ignore_hidden: bool = True) -> Iterator[Path]:
    """folder 配下の PDF を再帰列挙。"""
    for cur, dirs, files in os.walk(folder, topdown=True, followlinks=False):
        dirs[:] = [d for d in dirs if not (ignore_hidden and d.startswith("."))]
        for fn in files:
            if ignore_hidden and fn.startswith("."):
                continue
            if fn.lower().endswith(".pdf"):
                yield Path(cur) / fn

# 実行ボタン
if st.button("📥 ②で選択した年の <年>/<pno>/ へコピーを実行"):
    if not picked_years:
        st.warning("②で対象年を少なくとも1つ選んでください。")
    else:
        copied_total = skipped_total = errors_total = 0
        # 年×pnoごとの統計
        per_bucket_stats: Dict[str, Dict[str, int]] = {}  # key: f"{year}/{pno:03d}"

        # ②の分類結果（parsed_rows）から、選択年かつ 7桁数値(YYYYPPP)のみ処理
        for item in parsed_rows:
            year = item.get("year")
            pno  = item.get("pno")
            name = item.get("name", "")

            # 年が選択されていない / 年が数値でない場合は除外
            if year not in picked_years or not isinstance(year, int):
                continue

            # 7桁数値フォルダ（YYYYPPP）だけ対象
            if not re.fullmatch(rf"^{year}\d{{3}}$", name):
                continue

            # pno が取れないケースはスキップ（理論上 numeric7 なら 3桁）
            if pno is None:
                continue

            # ソース・デスティネーション
            src_dir = (REPORT_ROOT / item["path"]).resolve()
            dest_dir = (DEST_BASE / str(year) / f"{int(pno):03d}").resolve()  # 例: .../2020/123/
            dest_dir.mkdir(parents=True, exist_ok=True)

            bucket_key = f"{year}/{int(pno):03d}"
            per_bucket_stats.setdefault(bucket_key, {"copied": 0, "skipped": 0, "errors": 0})

            for src in _iter_pdfs_under(src_dir):
                dest = dest_dir / src.name
                try:
                    if dest.exists():
                        skipped_total += 1
                        per_bucket_stats[bucket_key]["skipped"] += 1
                    else:
                        shutil.copy2(src, dest)  # タイムスタンプ維持
                        copied_total += 1
                        per_bucket_stats[bucket_key]["copied"] += 1
                except Exception:
                    errors_total += 1
                    per_bucket_stats[bucket_key]["errors"] += 1

        # サマリ
        c1, c2, c3 = st.columns(3)
        c1.metric("Copied (total)", copied_total)
        c2.metric("Skipped (total)", skipped_total)
        c3.metric("Errors (total)", errors_total)

        # 年/pnoごとの内訳
        if per_bucket_stats:
            df_bucket = pd.DataFrame(
                [{"year_pno": y, **stat} for y, stat in sorted(per_bucket_stats.items(), key=lambda x: x[0])]
            )
            st.dataframe(df_bucket, width="stretch", height=260)
        else:
            st.info("対象フォルダが見つかりませんでした。")
