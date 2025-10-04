# pages/20_report整理.py
# ============================================
# 📂 report 整理（original_docs_root/report 配下の一覧）
# - ① 深さ1のフォルダ一覧
# - ② フォルダ名を規則で「年 / プロジェクト番号」に分類
# - ③ Library(P) フォルダ →図書管理DB（Sheet1）で年を補足分類
# - ④ 2019xxx フォルダ → organized_docs_root/2019/xxx へ PDF コピー
# ============================================

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

# 任意：PDFの軽量種別
try:
    from lib.pdf.info import quick_pdf_info  # 未使用でもOK
except Exception:
    quick_pdf_info = None


# ========== ページ設定 ==========
st.set_page_config(page_title="report 整理", page_icon="📂", layout="wide")
st.title("📂 report 整理 — original_docs_root/report 配下の一覧")

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

def _parse_folder_name(name: str) -> Dict[str, Any]:
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

parsed_rows: List[Dict[str, Any]] = []
for row in rows_lvl1:
    info = _parse_folder_name(row["name"])
    info["path"] = row["path"]
    parsed_rows.append(info)

if not parsed_rows:
    st.info("分類対象のフォルダがありません。")
else:
    grouped = {}
    for item in parsed_rows:
        year = item["year"] if item["year"] is not None else "その他"
        grouped.setdefault(year, []).append(item)

    for year, items in sorted(grouped.items(), key=lambda x: str(x[0])):
        with st.expander(f"📅 年: {year}（{len(items)} 件）", expanded=False):
            for it in sorted(items, key=lambda x: (x["pno"] if x["pno"] is not None else 999999, x["name"])):
                pn = "—" if it["pno"] is None else f"{it['pno']}"
                st.markdown(f"- **{it['name']}** ｜ PNo:{pn} 〔{it['category']}〕")

st.divider()


# ========== ③ Library(P) →図書管理DB で年を補足 ==========
st.subheader("③図書管理DBによる分類補足（Library(P) フォルダ）")

LIB_DB_PATH = Path(PATHS.library_root).expanduser().resolve() / "図書管理DB.xlsx"

# --- 発行年の正規化ヘルパ ---
_ZEN = "０１２３４５６７８９"
_HAN = "0123456789"
Z2H = str.maketrans(_ZEN, _HAN)

def parse_year_field(val) -> int:
    """Excelの『発行年』から西暦4桁を抽出。見つからなければ 9999。"""
    if pd.isna(val):
        return 9999
    # 数値ならそのまま整数化（1981.0 → 1981）
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        try:
            y = int(val)
            return 1900 <= y <= 2100 and y or 9999
        except Exception:
            pass
    # 文字列処理
    s = str(val).strip()
    if not s:
        return 9999
    # 全角数字→半角
    s = s.translate(Z2H)
    # 先頭に現れる4桁の数字を年として採用（1981/3, 1977.2, 1980-81 など）
    m = re.search(r"(\d{4})", s)
    if m:
        y = int(m.group(1))
        return 1800 <= y <= 2100 and y or 9999
    return 9999

lib_parsed_rows: List[Dict[str, Any]] = []

if LIB_DB_PATH.exists():
    try:
        # dtype=str で読み、登録番号/発行年を文字列で安定化
        df_lib = pd.read_excel(
            LIB_DB_PATH,
            sheet_name="Sheet1",
            dtype={"登録番号": "string", "発行年": "string"}
        )

        # 前処理：登録番号→発行年(正規化) の dict
        df_lib["登録番号"] = df_lib["登録番号"].astype("string").str.strip()
        df_lib["発行年_norm"] = df_lib["発行年"].map(parse_year_field)
        regno_to_year: Dict[str, int] = (
            df_lib[["登録番号", "発行年_norm"]]
            .dropna()
            .set_index("登録番号")["発行年_norm"]
            .to_dict()
        )

        # Library(P) フォルダを処理
        for row in parsed_rows:
            if row["category"] != "Library(P)":
                continue
            folder_path = (REPORT_ROOT / row["path"]).resolve()
            if not folder_path.exists():
                continue

            # Pフォルダ名からプロジェクト番号
            try:
                pno = int(row["name"].lstrip("Pp"))
            except Exception:
                pno = 999

            # フォルダ直下のPDFのみ対象（必要なら再帰に変更可）
            for pdf in folder_path.glob("*.pdf"):
                m = re.match(r"(\d+)-", pdf.name)  # 先頭「番号-…」形式
                if not m:
                    continue
                regno = m.group(1)

                year = regno_to_year.get(regno, 9999)
                lib_parsed_rows.append({
                    "name": pdf.name,
                    "category": "Library(P)-DB",
                    "year": year,
                    "pno": pno,
                    "path": str(pdf.relative_to(REPORT_ROOT)),
                })

    except Exception as e:
        st.error(f"図書管理DBの読み込みに失敗しました: {e}")
else:
    st.warning(f"図書管理DBが見つかりません: `{LIB_DB_PATH}`")

# 表示
if lib_parsed_rows:
    grouped = {}
    for item in lib_parsed_rows:
        grouped.setdefault(item["year"], []).append(item)
    for year, items in sorted(grouped.items(), key=lambda x: str(x[0])):
        with st.expander(f"📅 年: {year}（{len(items)} 件 / Library補足）", expanded=False):
            for it in sorted(items, key=lambda x: (x["pno"], x["name"])):
                st.markdown(f"- **{it['name']}** ｜ PNo:{it['pno']} 〔{it['category']}〕")
else:
    st.info("Library(P) に該当し、DBで年が引けたPDFはありません。")

st.divider()


# ========== ④ 2019xxx → organized_docs_root へコピー ==========
st.subheader("④ 2019 年の各下3桁フォルダへ PDF コピー（organized_docs_root/2019/xyz）")

dest_base_text = st.text_input(
    "コピー先ベース（既定：organized_docs_root）",
    value=str(Path(PATHS.organized_docs_root).expanduser().resolve())
)
ORG_BASE = Path(dest_base_text)
ORGYEAR = ORG_BASE / "2019"
PAT_2019 = re.compile(r"^2019(\d{3})$")

def _iter_pdfs_under(folder: Path, *, ignore_hidden=True) -> Iterator[Path]:
    for cur, dirs, files in os.walk(folder, topdown=True, followlinks=False):
        curp = Path(cur)
        # 隠し除外
        dirs[:] = [d for d in dirs if not (ignore_hidden and d.startswith("."))]
        for fn in files:
            if ignore_hidden and fn.startswith("."):
                continue
            if fn.lower().endswith(".pdf"):
                yield curp / fn

if st.button("📥 2019/下3桁 へコピーを実行"):
    copied = skipped = errors = 0
    for row in rows_lvl1:
        m = PAT_2019.match(row["name"])
        if not m:
            continue
        last3 = m.group(1)
        src_dir = REPORT_ROOT / row["path"]
        dest_subdir = ORGYEAR / last3
        dest_subdir.mkdir(parents=True, exist_ok=True)
        for src in _iter_pdfs_under(src_dir):
            dest = dest_subdir / src.name
            try:
                if dest.exists():
                    skipped += 1
                else:
                    shutil.copy2(src, dest)
                    copied += 1
            except Exception:
                errors += 1

    c1, c2, c3 = st.columns(3)
    c1.metric("Copied", copied)
    c2.metric("Skipped", skipped)
    c3.metric("Errors", errors)
