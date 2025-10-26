# pages/15_SSDビューア.py
# =============================================================================
# 📂 SSDビューア（重複ファイル名を排除したPDF集計・比較ツール）
# -----------------------------------------------------------------------------
# 概要:
#  1) ORIGINAL_DOCS_ROOT/report/ のフォルダ構造を規則に沿って解釈し、年代→年→プロジェクトを閲覧
#  2) 選択した年のプロジェクトを DataFrame で拡張子別集計（★同名ファイルは1回のみカウント）
#  3) ORGANIZED_DOCS_ROOT 側（report/pdf, report_skip/pdf）についても同様に集計して表示
#  4) 年内の各プロジェクトに対して、original の .pdf 総数 と organized（report+report_skip）の合計を
#     照合し、不一致があれば警告（★同名PDF重複は排除、サブフォルダも再帰）
#  5) 年・プロジェクト番号を指定して個別に original / organized を比較するUIも提供
#
# 重要:
#  - 「同名ファイルは 1 回のみカウント」。サブフォルダに同じ名前があっても重複として排除
#  - organized 側では *_ocr.pdf は通常 PDF として数える。*_skip.pdf は「skip」として別カウント
#  - original 側は純粋な .pdf のみを対象（同名除外・サブフォルダ含む）
# =============================================================================

import streamlit as st
from pathlib import Path
import re
from collections import defaultdict
import pandas as pd
import sys

# ------------------------------------------------------------
# パス設定
# ------------------------------------------------------------
from lib.app_paths import PATHS

ORIGINAL_DOCS_ROOT = Path(getattr(PATHS, "original_docs_root")).expanduser().resolve()
ORGANIZED_DOCS_ROOT = getattr(PATHS, "organized_docs_root", None)

if not ORIGINAL_DOCS_ROOT.exists():
    st.error(f"{ORIGINAL_DOCS_ROOT} が存在しません。マウントや設定を確認してください。")
    st.stop()

ROOT = ORIGINAL_DOCS_ROOT  # 本画面では original を基点に走査

# ------------------------------------------------------------
# UIライブラリ（任意）
# ------------------------------------------------------------
PROJECTS_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECTS_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECTS_ROOT))
try:
    from common_lib.ui.ui_basics import thick_divider
except Exception:
    def thick_divider(color="Blue", height=3, margin="1.5em 0"):
        st.markdown(f'<hr style="border:none;border-top:{height}px solid #3b82f6;margin:{margin};" />', unsafe_allow_html=True)

# ------------------------------------------------------------
# ヘッダー（パス情報）
# ------------------------------------------------------------
st.title("📂 SSDビュアー")
st.subheader("📂 パス情報")

st.markdown(
    f"""
    <div style="
        background-color:#eef6fb;
        border-left: 5px solid #5fa3e0;
        padding:10px 15px;
        border-radius:8px;
        font-size:14px;
        line-height:1.6;
    ">
        <b>ROOT:</b> {ROOT}<br>
        <b>ORIGINAL_DOCS_ROOT:</b> {ORIGINAL_DOCS_ROOT}<br>
        <b>ORGANIZED_DOCS_ROOT:</b> {ORGANIZED_DOCS_ROOT or '(後で使用)'}
    </div>
    """,
    unsafe_allow_html=True,
)

# =============================================================================
# 📦 カウント系ユーティリティ（★同名ファイル重複排除）
# =============================================================================
def count_unique_exts_recursive(dirpath: Path) -> dict:
    """
    dirpath 配下（子・孫含む）のファイルを拡張子別に集計。
    ★同名ファイル（例: 同名.pdf）が複数フォルダにあっても 1 回のみカウント。
    """
    from collections import defaultdict
    counts = defaultdict(int)
    if not dirpath or not dirpath.exists():
        return {}
    seen_names = set()
    for f in dirpath.rglob("*"):
        if not f.is_file():
            continue
        name_lower = f.name.lower()
        if name_lower in seen_names:
            continue
        seen_names.add(name_lower)
        ext = f.suffix.lower().lstrip('.') or '(noext)'
        counts[ext] += 1
    return dict(counts)


def count_pdf_categories(dirpath: Path) -> dict:
    """
    organized / original いずれでも使える PDF 分類カウント（★同名排除）。
      - 'pdf'       : 通常PDF + *_ocr.pdf を一括でカウント（*_skip.pdf は除外）
      - 'skip_pdf'  : *_skip.pdf
      - 'ocr_pdf'   : *_ocr.pdf
      - 'side_json' : *_side.json
    """
    counts = {"pdf": 0, "skip_pdf": 0, "ocr_pdf": 0, "side_json": 0}
    if not dirpath or not dirpath.exists():
        return counts
    seen_names = set()
    for f in dirpath.rglob("*"):
        if not f.is_file():
            continue
        name = f.name.lower()
        if name in seen_names:
            continue
        seen_names.add(name)
        if name.endswith("_side.json"):
            counts["side_json"] += 1
        elif name.endswith("_skip.pdf"):
            counts["skip_pdf"] += 1
        elif name.endswith("_ocr.pdf"):
            counts["ocr_pdf"] += 1
            # counts["pdf"] += 1
        elif name.endswith(".pdf"):
            counts["pdf"] += 1
    return counts

# =============================================================================
# 📘 original/report のフォルダ命名規則の解釈・走査
# =============================================================================
def parse_folder_name(name: str):
    """フォルダ名を規則で解析して (種別, …) を返す。"""
    s = name.strip()
    if s.upper().startswith("P"):
        return ("library", s)
    if re.fullmatch(r"\d{7}", s):
        return ("year", int(s[:4]), int(s[4:]))  # YYYYPPP
    m = re.fullmatch(r"H(\d{2})(\d{3})", s, re.IGNORECASE)
    if m:
        return ("year", 1988 + int(m.group(1)), int(m.group(2)))
    m = re.fullmatch(r"S(\d{2})(\d{3})", s, re.IGNORECASE)
    if m:
        return ("year", 1925 + int(m.group(1)), int(m.group(2)))
    return ("other", s)

@st.cache_data(show_spinner=False)
def scan_report_dirs(report_dir: Path):
    """
    original/report 配下直下のフォルダを走査し、
    年→プロジェクト番号の対応、および (year, pno) → Path を返す。
    """
    years_to_pnos = defaultdict(set)
    proj_dir_map = {}
    library_names, others = [], []

    if not report_dir.exists():
        return years_to_pnos, proj_dir_map, library_names, others

    for p in report_dir.iterdir():
        if not p.is_dir():
            continue
        kind = parse_folder_name(p.name)
        if kind[0] == "year":
            _, year, pno = kind
            years_to_pnos[year].add(pno)
            proj_dir_map.setdefault((year, pno), p)
        elif kind[0] == "library":
            library_names.append(kind[1])
        else:
            others.append(kind[1])

    for y in list(years_to_pnos.keys()):
        years_to_pnos[y] = sorted(years_to_pnos[y])

    return years_to_pnos, proj_dir_map, sorted(set(library_names)), sorted(set(others))

REPORT_DIR = ORIGINAL_DOCS_ROOT / "report"
years_to_pnos, proj_dir_map, library_names, others = scan_report_dirs(REPORT_DIR)

# =============================================================================
# 🧮 DataFrameビルダー（重複排除）
# =============================================================================
PREFERRED_COLS = [
    "pdf","doc","docx","xls","xlsx","xlsm","ppt","pptx",
    "csv","txt","xml","json","md","jpg","jpeg","png","gif",
    "tif","tiff","svg","ai","psd","indd","dtd","p21","mcd","(noext)"
]

def build_df_from_pairs(pairs: list[tuple[str, Path]]) -> pd.DataFrame:
    """
    pairs: [(project_display, project_dir), ...]
    return: 拡張子別カウントを行った DataFrame（列順整形済）
    ★同名ファイルは排除した集計を使用
    """
    rows, all_exts = [], set()
    for proj, pdir in pairs:
        counts = count_unique_exts_recursive(pdir)
        all_exts.update(counts.keys())
        rows.append({"project": proj, "total": sum(counts.values()), **counts})
    if not rows:
        return pd.DataFrame()

    dynamic = [e for e in sorted(all_exts) if e not in PREFERRED_COLS]
    columns = ["project", "total"] + [e for e in PREFERRED_COLS if e in all_exts] + dynamic
    df = pd.DataFrame(rows).reindex(columns=columns, fill_value=0).sort_values("project")
    return df

# =============================================================================
# 📊 organized 側セクション表示（report/pdf, report_skip/pdf）
# =============================================================================
def render_organized_year_section(title: str, base_dir: Path, year: int):
    """
    organized 側の年フォルダー配下のプロジェクトを拡張子別集計（同名排除）して表示。
    base_dir: Path(ORGANIZED_DOCS_ROOT) / "report" / "pdf" など
    """
    st.divider()
    note = " （分析から排除しているプロジェクト）" if "report_skip" in title else ""
    st.markdown(f"**{title}/{year} の集計{note}**")

    if not ORGANIZED_DOCS_ROOT:
        st.info("ORGANIZED_DOCS_ROOT が未設定です。")
        return

    year_dir = base_dir / str(year)
    if not year_dir.exists():
        st.info(f"年フォルダーが見つかりません: {year_dir}")
        return

    proj_dirs = sorted([p for p in year_dir.iterdir() if p.is_dir()], key=lambda x: x.name)
    st.caption("プロジェクト番号: " + (", ".join([p.name for p in proj_dirs]) if proj_dirs else "（なし）"))

    pairs = [(d.name, d) for d in proj_dirs]
    df = build_df_from_pairs(pairs)
    if df.empty:
        st.info("（該当プロジェクトなし）")
    else:
        st.dataframe(df, width='stretch')
        st.download_button(
            label=f"CSVをダウンロード（{title}）",
            data=df.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"{year}_{title.replace('/','_')}_ext_counts.csv",
            mime="text/csv",
        )

# =============================================================================
# 🧭 年代 → 年 → プロジェクト UI
# =============================================================================
DECADES = [
    ("1970年代", 1970, 1979),
    ("1980年代", 1980, 1989),
    ("1990年代", 1990, 1999),
    ("2000年代", 2000, 2009),
    ("2010年代", 2010, 2019),
    ("2020年代", 2020, 2099),
]
RADIO_LABELS = [d[0] for d in DECADES] + ["図書館", "その他"]

# デフォルト選択：データがある最初の年代 → 図書館 → その他
default_idx, found = 0, False
for i, (_, y0, y1) in enumerate(DECADES):
    if any(y0 <= y <= y1 for y in years_to_pnos.keys()):
        default_idx = i
        found = True
        break
if not found and library_names:
    default_idx = len(DECADES)
elif not found and others:
    default_idx = len(DECADES) + 1

thick_divider(color="Blue", height=3, margin="1.5em 0")
st.subheader("年代 / 図書館 / その他 を選択")
selected = st.radio("表示カテゴリ", RADIO_LABELS, index=default_idx, horizontal=True)

# =============================================================================
# 🖼 表示ロジック
# =============================================================================
if selected == "図書館":
    st.markdown("**図書館（P...）のフォルダ一覧**")
    st.info(", ".join(library_names) or "図書館に該当するデータがありません。")

elif selected == "その他":
    st.markdown("**その他（命名規則に当てはまらないフォルダ）**")
    st.info(", ".join(others) or "その他のフォルダはありません。")

else:
    # 年代の範囲取得
    for label, a, b in DECADES:
        if label == selected:
            y0, y1 = a, b
            break
    years_in_decade = sorted(y for y in years_to_pnos if y0 <= y <= y1)

    st.markdown(f"**{selected} のプロジェクト一覧**")
    if not years_in_decade:
        st.info("該当データがありません。")
    else:
        # 年ごとのプロジェクト番号一覧（視覚整形）
        lines = [f"{y}年： " + ", ".join(f"{n:03d}" for n in years_to_pnos[y]) for y in years_in_decade]
        html_lines = "<br>".join(f"<b>{line.split('：')[0]}：</b>{line.split('：')[1]}" for line in lines)
        st.markdown(
            f"""
            <div style="
                background-color:#eef6fb;
                border-left:5px solid #5fa3e0;
                padding:12px 18px;
                border-radius:8px;
                font-size:14px;
                line-height:1.8;
                color:#002b55;
            ">
                {"<br><br>".join(html_lines.split("<br>"))}
            </div>
            """,
            unsafe_allow_html=True,
        )

        # --- 年ラジオ（年代内の年から選択） ---
        st.divider()
        year_options = [y for y in years_in_decade]
        if year_options:
            chosen_year_label = st.radio(
                "年を選択",
                options=[f"{y}年" for y in year_options],
                index=0,  # 最初の年をデフォルト
                horizontal=True,
                key="year_radio_in_decade",
            )
            chosen_year = int(chosen_year_label[:-1])  # "1973年" -> 1973

            # ========== original 側：選択年のプロジェクト拡張子別集計（同名排除） ==========
            pairs_original = [
                (f"{pno:03d}", proj_dir_map.get((chosen_year, pno)))
                for pno in years_to_pnos.get(chosen_year, [])
                if proj_dir_map.get((chosen_year, pno)) is not None
            ]
            df_original = build_df_from_pairs(pairs_original)
            st.markdown(f"**{chosen_year}年のプロジェクト（拡張子別ファイル数, original/report）**")
            if df_original.empty:
                st.info("（該当プロジェクトなし）")
            else:
                st.dataframe(df_original, width='stretch')
                st.download_button(
                    label="CSVをダウンロード（original/report）",
                    data=df_original.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"{chosen_year}_original_report_ext_counts.csv",
                    mime="text/csv",
                )

            # ========== organized 側：report/pdf/<年> と report_skip/pdf/<年> ==========
            if ORGANIZED_DOCS_ROOT:
                render_organized_year_section(
                    "organized/report/pdf", Path(ORGANIZED_DOCS_ROOT) / "report" / "pdf", chosen_year
                )
                render_organized_year_section(
                    "organized/report_skip/pdf", Path(ORGANIZED_DOCS_ROOT) / "report_skip" / "pdf", chosen_year
                )
            else:
                st.info("ORGANIZED_DOCS_ROOT が未設定です。")

            # =============================================================================
            # 🔍 年内プロジェクトの整合性チェック（original vs organized）
            # -----------------------------------------------------------------------------
            # original総数 = original/report/<YYYYPPP> 内の .pdf（同名除外）
            # organized総数 = organized/(report/pdf + report_skip/pdf) 内の
            #                 （.pdf + *_skip.pdf、*_ocr.pdfはpdfに含めない／同名除外）
            # → 一致しないプロジェクトを警告
            # =============================================================================
            from itertools import chain

            # 年内でプロジェクト集合を網羅
            projects_original = {f"{pno:03d}" for pno in years_to_pnos.get(chosen_year, [])}
            org_report_year_dir      = Path(ORGANIZED_DOCS_ROOT) / "report"      / "pdf" / str(chosen_year) if ORGANIZED_DOCS_ROOT else None
            org_report_skip_year_dir = Path(ORGANIZED_DOCS_ROOT) / "report_skip" / "pdf" / str(chosen_year) if ORGANIZED_DOCS_ROOT else None
            projects_org_report      = {p.name for p in org_report_year_dir.iterdir()      if org_report_year_dir      and p.is_dir()} if ORGANIZED_DOCS_ROOT and org_report_year_dir      and org_report_year_dir.exists()      else set()
            projects_org_report_skip = {p.name for p in org_report_skip_year_dir.iterdir() if org_report_skip_year_dir and p.is_dir()} if ORGANIZED_DOCS_ROOT and org_report_skip_year_dir and org_report_skip_year_dir.exists() else set()

            all_projects = sorted(projects_original | projects_org_report | projects_org_report_skip)

            rows_chk = []
            for proj in all_projects:
                # original 側（同名PDF排除）
                pdir_original = proj_dir_map.get((chosen_year, int(proj))) if proj.isdigit() else None
                original_count = 0
                if pdir_original:
                    seen = set()
                    for f in pdir_original.rglob("*"):
                        if f.is_file() and f.suffix.lower() == ".pdf":
                            name = f.name.lower()
                            if name in seen: 
                                continue
                            seen.add(name)
                            original_count += 1

                # organized 側（同名PDF排除、_ocrはpdfに含めない）
                b = c = d = e = 0
                if ORGANIZED_DOCS_ROOT:
                    # report/pdf/<year>/<proj>
                    rp = (org_report_year_dir / proj) if org_report_year_dir else None
                    if rp and rp.exists():
                        cc = count_pdf_categories(rp)
                        b = cc["pdf"]       # 通常pdf（_ocr除外, _skip除外）
                        c = cc["skip_pdf"]  # *_skip.pdf
                    # report_skip/pdf/<year>/<proj>
                    rps = (org_report_skip_year_dir / proj) if org_report_skip_year_dir else None
                    if rps and rps.exists():
                        cc2 = count_pdf_categories(rps)
                        d = cc2["pdf"]
                        e = cc2["skip_pdf"]

                org_report_sum      = b + c
                org_report_skip_sum = d + e
                organized_count     = org_report_sum + org_report_skip_sum
                match_flag          = (original_count == organized_count)

                rows_chk.append({
                    "チェック結果": "✅一致" if match_flag else "⚠️不一致",
                    "プロジェクト": proj,
                    "original総数": original_count,
                    "organized(report)": org_report_sum,
                    "organized(report_skip)": org_report_skip_sum,
                    "organized総数": organized_count,
                })

            df_chk = pd.DataFrame(rows_chk).sort_values("プロジェクト")

            thick_divider(color="Blue", height=3, margin="1.5em 0")
            st.subheader("🔍 整合性チェック（original vs organized）")
            st.caption(f"対象年：{chosen_year}年")  # ← 年を表示
            st.dataframe(df_chk, width='stretch')

            # 不一致プロジェクトを警告
            mismatched = df_chk[df_chk["チェック結果"] == "⚠️不一致"]["プロジェクト"].tolist()
            if mismatched:
                st.warning(
                    "original の .pdf 総数 と organized の合計が一致しないプロジェクトがあります："
                    + ", ".join(mismatched)
                )

            # CSV ダウンロード
            st.download_button(
                label="CSVをダウンロード（整合性チェック）",
                data=df_chk.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"{chosen_year}_consistency_check.csv",
                mime="text/csv",
            )

            # =============================================================================
            # 🧮 個別プロジェクト確認（year + pno を指定して集計）— 同名排除
            # =============================================================================
            st.divider()
            st.subheader("🧮 個別プロジェクト確認")

            col1, col2, col3 = st.columns([1, 1, 1])
            with col1:
                input_year = st.text_input("年（例: 2015）", value=str(chosen_year))
            with col2:
                input_pno = st.text_input("プロジェクト番号（例: 123）", value="")
            with col3:
                run_check = st.button("集計")

            if run_check and input_year.isdigit() and input_pno.isdigit():
                y_val = int(input_year)
                p_val = int(input_pno)

                # original 側：YYYYPPP でパスを直接指す（規則に一致していれば存在）
                pdir_original_direct = Path(ORIGINAL_DOCS_ROOT) / "report" / f"{y_val}{p_val:03d}"
                orig_counts = count_pdf_categories(pdir_original_direct)
                orig_total = orig_counts["pdf"]

                # organized 側
                counts_report = count_pdf_categories(
                    Path(ORGANIZED_DOCS_ROOT or "") / "report" / "pdf" / str(y_val) / f"{p_val:03d}"
                )
                counts_report_skip = count_pdf_categories(
                    Path(ORGANIZED_DOCS_ROOT or "") / "report_skip" / "pdf" / str(y_val) / f"{p_val:03d}"
                )

                b, c = counts_report["pdf"], counts_report["skip_pdf"]
                d, e = counts_report_skip["pdf"], counts_report_skip["skip_pdf"]
                org_total = b + c + d + e

                df_single = pd.DataFrame([{
                    "year": y_val,
                    "project": f"{p_val:03d}",
                    "original総数": orig_total,
                    "organized総数": org_total,
                    "report(pdf)": b,
                    "report(_skip.pdf)": c,
                    "report_skip(pdf)": d,
                    "report_skip(_skip.pdf)": e,
                    "一致": "✅一致" if orig_total == org_total else "⚠️不一致"
                }])

                st.dataframe(df_single, width='stretch')

                if orig_total == org_total:
                    st.success("✅ original と organized のPDF総数は一致しています。")
                else:
                    st.error("⚠️ original と organized のPDF総数が一致していません。")

            elif run_check:
                st.warning("年とプロジェクト番号は数値で入力してください。")
