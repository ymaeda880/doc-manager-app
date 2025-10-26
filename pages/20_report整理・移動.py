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

import sys
from pathlib import Path

# projects/ を import パスに追加（pages → app → project → projects）
PROJECTS_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECTS_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECTS_ROOT))

# これで common_lib をパッケージとして参照できる
from common_lib.ui.ui_basics import thick_divider

# import _bootstrap_path
# from common_lib.ui.ui_basics import thick_divider


# ========== ページ設定 ==========
st.set_page_config(page_title="report 整理", page_icon="📂", layout="wide")



st.title("📂 report 整理 — original_docs_root/report 配下の一覧")

st.info("使用ルート：original_docs_root -> organized_docs_root")



# ★ ここにフルパスを追加
try:
    org_root = Path(PATHS.original_docs_root).expanduser().resolve()
    orgz_root = Path(PATHS.organized_docs_root).expanduser().resolve()
    st.markdown(
        f"""
        **original_docs_root:** `{org_root}`  
        **organized_docs_root:** `{orgz_root}`
        """,
        unsafe_allow_html=True,
    )
except Exception as e:
    st.warning(f"ルートパスの取得に失敗しました: {e}")

st.markdown(
    """
    <span style="color:steelblue;">
    元本ファイル（original_docs）を作業ファイル（organized_docs）に整理してコピーします。<br>    
    作業ファイルには、PDFファイルのみを、年とプロジェクト番号ごとにフォルダーを作って格納します。
    </span>
    """,
    unsafe_allow_html=True
)



thick_divider(color="Blue", height=3, margin="1.5em 0")

st.markdown("""
### フォルダ名を規則で「年 / プロジェクト番号」に分類
- 7桁数値: `YYYYPPP`（YYYY=年, PPP=プロジェクト番号）  
- `HNNPPP`: 平成 → 西暦は `1988 + NN`  
- `SNNPPP`: 昭和 → 西暦は `1925 + NN`  
- `P...`   : 図書館管理（年=9999, PNo=999）として一旦プレースホルダ  
- 上記以外は `other` として年なし  
- ★ 年ごとのエキスパンダーにチェックボックスを付与。  
  ここでチェックした **年** を ④ の対象年として利用します。

---

### 選択した年 → `<ベース>/report/pdf/<年>/<pno>/` へ PDF コピー
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

    st.subheader("①.5 表示オプション")
    grid_cols = st.slider("横の列数（プロジェクトを横並び表示）", min_value=2, max_value=10, value=5, step=1)
    calc_recursive = st.checkbox("プロジェクト内の**再帰**集計（件数・総容量）を計算する", value=False,
                                 help="ONにすると各プロジェクトフォルダ内のPDFに限らず全ファイルを再帰で数え、総容量を算出します。時間がかかる場合があります。")


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


thick_divider(color="Blue", height=3, margin="1.5em 0")

# ========== ① 深さ1のフォルダ一覧 ==========
st.subheader("① 深さ1のフォルダ一覧（report 直下）")
st.info(f"""
（原本ファイル）original_docs_root: `{org_root}`  
""")
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

# ========== ① 年 / プロジェクト一覧（original)（拡張子別：件数・総容量、再帰・DataFrame表示） ==========
st.subheader("① 年 / プロジェクト一覧（original）（拡張子別：件数・総容量、DataFrame表示）")
st.markdown(
    """
    📌 **説明**  
    - ①で列挙した「深さ1フォルダ」を **最下層まで再帰** で捜査し、**拡張子ごと**（pdf/docx/pptx/xlsx…）に**件数**と**総容量**を集計します。  
    - 表の列順は `year / pno / pdf / pdf_size / folder / docx / docx_size / pptx / pptx_size / xlsx / xlsx_size / ...` の並びです。  
    - `folder` 列は元のフォルダ名（例: `2019003`）です。  
    """,
    unsafe_allow_html=True
)

def _fmt_bytes(n: int | None) -> str:
    if n is None:
        return "—"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(n)
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024.0
        idx += 1
    return f"{size:.1f} {units[idx]}"

# 集計対象の代表拡張子（必要に応じて追加）
TARGET_EXTS = ["pdf", "docx", "pptx", "xlsx", "csv", "txt", "jpg", "jpeg", "png"]

@st.cache_data(show_spinner=False)
def _ext_stats_recursive_cached(path_str: str, mtime: float, ignore_hidden: bool) -> dict:
    """
    ディレクトリ以下を再帰で走査し、拡張子ごとの件数・総容量を返す。
    返り値: {"by_ext": {ext: {"count":int, "bytes":int}}, "total_files":int, "total_bytes":int}
    キャッシュは path + mtime + ignore_hidden をキーにする。
    """
    import os
    from pathlib import Path

    p = Path(path_str)
    by_ext: dict[str, dict] = {}
    total_files = 0
    total_bytes = 0

    if not p.exists():
        return {"by_ext": {}, "total_files": 0, "total_bytes": 0}

    for cur, dirs, files in os.walk(p, topdown=True, followlinks=False):
        # 隠し除外
        dirs[:] = [d for d in dirs if not (ignore_hidden and d.startswith("."))]
        for fn in files:
            if ignore_hidden and fn.startswith("."):
                continue
            total_files += 1
            fpath = Path(cur) / fn
            # サイズ
            try:
                sz = fpath.stat().st_size
            except Exception:
                sz = 0
            total_bytes += sz
            # 拡張子
            ext = fpath.suffix.lower().lstrip(".")
            if not ext:
                ext = "(noext)"
            slot = by_ext.setdefault(ext, {"count": 0, "bytes": 0})
            slot["count"] += 1
            slot["bytes"] += sz

    return {"by_ext": by_ext, "total_files": total_files, "total_bytes": total_bytes}

# === rows_lvl1 を解析して year/pno 抽出（numeric7 / Heisei / Showa を対象） ===
parsed_for_grid = []
for row in rows_lvl1:
    info = _parse_folder_name(row["name"])
    if info["category"] in ("numeric7", "Heisei", "Showa"):
        info["path"] = row["path"]
        parsed_for_grid.append(info)

if not parsed_for_grid:
    st.info("対象となるフォルダがありません。")
else:
    records: list[dict] = []
    for item in sorted(parsed_for_grid, key=lambda x: (x["year"], x["pno"])):
        year = item["year"]
        pno = item["pno"]
        folder_name = item["name"]  # 例: 2019003
        folder_path = (REPORT_ROOT / item["path"]).resolve()

        mtime = safe_stat_mtime(folder_path) or 0.0
        stats = _ext_stats_recursive_cached(str(folder_path), mtime, ignore_hidden=ignore_hidden)
        by_ext = stats["by_ext"]

        rec: dict = {
            "year": year,
            "pno": int(pno) if pno is not None else None,
            "folder": folder_name,
            "relpath": str(folder_path.relative_to(REPORT_ROOT)),
        }

        # 代表拡張子の列を「件数」「サイズ（fmt）」で並べる
        for ext in TARGET_EXTS:
            cnt = by_ext.get(ext, {}).get("count", 0)
            bts = by_ext.get(ext, {}).get("bytes", 0)
            rec[f"{ext}"] = cnt
            rec[f"{ext}_size"] = _fmt_bytes(bts)

        # TARGET_EXTS 以外も合算（other）
        other_cnt = 0
        other_bts = 0
        for ext, v in by_ext.items():
            if ext not in TARGET_EXTS:
                other_cnt += v.get("count", 0)
                other_bts += v.get("bytes", 0)
        rec["other"] = other_cnt
        rec["other_size"] = _fmt_bytes(other_bts)

        # トータル
        rec["files_total"] = stats["total_files"]
        rec["size_total"] = _fmt_bytes(stats["total_bytes"])

        records.append(rec)

      # 列順を整える（year / pno / files_total / size_total / pdf / pdf_size / ... / folder / relpath）
    cols_order = ["year", "pno", "files_total", "size_total"]
    for ext in TARGET_EXTS:
        cols_order += [ext, f"{ext}_size"]
    cols_order += ["other", "other_size", "folder", "relpath"]

    df_ext = pd.DataFrame(records)

    # 欠け列があっても落ちないように補完
    for col in cols_order:
        if col not in df_ext.columns:
            # _size列なら文字列、件数列なら0
            if col.endswith("_size") or col in ("size_total",):
                df_ext[col] = "—"
            else:
                df_ext[col] = 0

    df_ext = df_ext[cols_order].sort_values(["year", "pno"]).reset_index(drop=True)

    st.dataframe(df_ext, width="stretch", height=520)


# ========== ①.6 比較（organized配下 vs ①.5 集計） ==========
st.subheader("①.6 比較（organized配下 vs ①.5 集計）")
st.markdown(
    """
    📌 **説明**  
    - 下記の**コピー先ベース**（既定：`organized_docs_root/report/pdf`）を起点に、  
      `year/pno` または `pno` 直下構成を**自動判別**して格納PDFを集計します（PDFのみ対象）。  
    - ①.5 で計算した **year/pno ごとの PDF 個数・容量** と比較し、  
      **一致/不一致** と **差分ファイル名**（不足/余剰）を表示します。  
    """,
    unsafe_allow_html=True
)

# ④の入力値を参照して使う（①.6では同じkeyの入力ウィジェットを描画しない）
default_dest = str((Path(PATHS.organized_docs_root).expanduser().resolve() / "report" / "pdf"))
if "dest_base_input" not in st.session_state:
    st.session_state["dest_base_input"] = default_dest

dest_base_text_16 = st.session_state["dest_base_input"]
DEST_BASE_16 = Path(dest_base_text_16).expanduser().resolve()
st.caption(f"比較対象の organized ベース: `{DEST_BASE_16}`")
st.caption(f"比較元の original ベース: `{REPORT_ROOT}`")


# organized直下に存在する「年（4桁）フォルダ」を列挙（無ければ空集合）
try:
    AVAILABLE_YEARS = {
        int(p.name)
        for p in DEST_BASE_16.iterdir()
        if p.is_dir() and re.fullmatch(r"\d{4}", p.name)
    }
except Exception:
    AVAILABLE_YEARS = set()


def _fmt_bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(n)
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024.0
        idx += 1
    return f"{size:.1f} {units[idx]}"

def _walk_pdfs_under(root: Path, *, ignore_hidden: bool = True) -> tuple[set[str], int]:
    """
    root 以下の PDF（.pdf）だけを再帰で集める。
    ただし *_ocr.pdf は無視する（比較対象外）。
    戻り値：(basename集合, 総バイト)
    """
    names: set[str] = set()
    total = 0
    if not root.exists():
        return names, 0
    for cur, dirs, files in os.walk(root, topdown=True, followlinks=False):
        # 隠し除外
        dirs[:] = [d for d in dirs if not (ignore_hidden and d.startswith("."))]
        for fn in files:
            if ignore_hidden and fn.startswith("."):
                continue
            low = fn.lower()
            # .pdf かつ *_ocr.pdf は除外
            if (low.endswith(".pdf")) and (not low.endswith("_ocr.pdf")):
                names.add(fn)
                try:
                    total += (Path(cur) / fn).stat().st_size
                except Exception:
                    pass
    return names, total

def _resolve_dest_bucket(base: Path, year: int, pno: int) -> Path | None:
    """
    organized 側の格納先を自動判別:
      1) base/<year>/<pno:03d>/ があれば採用
      2) base/<pno:03d>/      があれば採用（pno 直下構成）
      3) どちらも無ければ None
    """
    y_path = base / str(year) / f"{int(pno):03d}"
    if y_path.exists():
        return y_path
    p_path = base / f"{int(pno):03d}"
    if p_path.exists():
        return p_path
    return None

# ①.5 で作った parsed_for_grid（numeric7/Heisei/Showa）を前提に比較
if not parsed_for_grid:
    st.info("①.5 に対象フォルダが無いため、比較対象がありません。")
else:
    # year,pno ごとに“ソース”の PDF 基準集合を作る
    #   - ①.5 では by_ext の合計だけだったので、ここで改めて PDF を**ファイル名単位**で収集
    buckets_src: dict[tuple[int, int], dict] = {}
    for item in sorted(parsed_for_grid, key=lambda x: (x["year"], x["pno"])):
        year: int = int(item["year"])
        pno:  int = int(item["pno"])
        src_dir = (REPORT_ROOT / item["path"]).resolve()
        names, total_bytes = _walk_pdfs_under(src_dir, ignore_hidden=ignore_hidden)
        rec = buckets_src.setdefault((year, pno), {"names": set(), "bytes": 0, "folders": []})
        rec["names"].update(names)
        rec["bytes"] += total_bytes
        rec["folders"].append(item["name"])  # 例: 2019003 など

    # organized 側を調べて比較
    rows_cmp: list[dict] = []
    for (year, pno), src in sorted(buckets_src.items()):
        # ★ organized の直下に year フォルダが無ければスキップ
        if AVAILABLE_YEARS and (year not in AVAILABLE_YEARS):
            continue
        dest_dir = _resolve_dest_bucket(DEST_BASE_16, year, pno)
        if dest_dir is None:
            # 置き場なし
           
            # 置き場なし＝organized 側に存在しないので、全ファイルが「不足」
            _missing_all = sorted(src["names"])
            rows_cmp.append({
                "year": year,
                "pno": pno,
                "src_count": len(src["names"]),
                "src_size": _fmt_bytes(src["bytes"]),
                "src_bytes": src["bytes"],          # ★追加
                "dst_count": 0,
                "dst_size": _fmt_bytes(0),
                "dst_bytes": 0,                      # ★追加
                "match": False,

                # プレビュー（短縮）
                "missing_in_dst": ", ".join(_missing_all)[:500],
                "extra_in_dst": "",

                # フル配列
                "missing_list": _missing_all,
                "extra_list": [],

                # ★差分件数（年サマリー用）
                "missing_count": len(_missing_all),
                "extra_count": 0,

                "dest_path": "(not found)",
                "src_folders": ", ".join(src["folders"]),
            })
            continue

        dst_names, dst_bytes = _walk_pdfs_under(dest_dir, ignore_hidden=ignore_hidden)

        missing = sorted(src["names"] - dst_names)
        extra   = sorted(dst_names - src["names"])

        rows_cmp.append({
            "year": year,
            "pno": pno,
            "src_count": len(src["names"]),
            "src_size": _fmt_bytes(src["bytes"]),
            "src_bytes": src["bytes"],          # ★追加
            "dst_count": len(dst_names),
            "dst_size": _fmt_bytes(dst_bytes),
            "dst_bytes": dst_bytes,             # ★追加
            "match": (len(missing) == 0 and len(extra) == 0 and src["bytes"] == dst_bytes),

            # プレビュー（短縮）
            "missing_in_dst": ", ".join(missing)[:500],
            "extra_in_dst": ", ".join(extra)[:500],

            # フル配列
            "missing_list": missing,
            "extra_list": extra,

            # ★差分件数（年サマリー用）
            "missing_count": len(missing),
            "extra_count": len(extra),

            "dest_path": str(dest_dir),
            "src_folders": ", ".join(src["folders"]),
        })

    # ---- 年別 PDF 比較（サマリー）を先に表示 ----
    df_cmp = pd.DataFrame(rows_cmp)

    if not df_cmp.empty:
        df_year = (
            df_cmp.groupby("year", as_index=False)
            .agg(
                src_count=("src_count", "sum"),
                src_bytes=("src_bytes", "sum"),
                dst_count=("dst_count", "sum"),
                dst_bytes=("dst_bytes", "sum"),
                missing_count=("missing_count", "sum"),
                extra_count=("extra_count", "sum"),
                buckets=("pno", "count"),
                perfect_buckets=("match", "sum"),  # True=1, False=0 として合計
            )
        )
        # 読みやすいサイズ表記を追加
        df_year["src_size"] = df_year["src_bytes"].map(_fmt_bytes)
        df_year["dst_size"] = df_year["dst_bytes"].map(_fmt_bytes)
        # 年単位で一致判定：差分ゼロ＆総容量一致
        df_year["match"] = (
            (df_year["missing_count"] == 0)
            & (df_year["extra_count"] == 0)
            & (df_year["src_bytes"] == df_year["dst_bytes"])
        )
        df_year = df_year[
            ["year", "src_count", "src_size", "dst_count", "dst_size",
            "missing_count", "extra_count", "buckets", "perfect_buckets", "match"]
        ].sort_values("year")

        st.markdown("#### 年別 PDF 比較（ソース vs organized）")
        st.dataframe(df_year, width="stretch", height=240)

        # ===== 年を入力して「出力」ボタンを押した時だけ詳細を表示 =====
        st.markdown("##### 年を指定して詳細を出力")
        col_y, col_btn = st.columns([2, 1])
        with col_y:
            year_input_str = st.text_input(
                "年（4桁、空欄なら全件）",
                value=st.session_state.get("cmp_year_input", ""),
                key="cmp_year_input"
            )
        with col_btn:
            run_cmp = st.button("▶ 出力", key="cmp_run")

        # ボタン押下でフィルタ値を確定
        if run_cmp:
            yf = None
            s = (year_input_str or "").strip()
            if re.fullmatch(r"\d{4}", s):
                yf = int(s)
            st.session_state["cmp_year_filter_val"] = yf
            st.session_state["cmp_run_pressed"] = True

        # 以降の詳細2表は、ボタン押下後のみ描画
        if st.session_state.get("cmp_run_pressed", False):
            year_filter = st.session_state.get("cmp_year_filter_val", None)

            # --- year/pno ごとの PDF 比較 ---
            df_cmp = pd.DataFrame(rows_cmp).sort_values(["year", "pno"]).reset_index(drop=True)
            df_cmp_filtered = df_cmp if year_filter is None else df_cmp[df_cmp["year"] == year_filter]

            st.markdown("#### year/pno ごとの PDF 比較（ソース vs organized）")
            st.dataframe(
                df_cmp_filtered[
                    [
                        "year", "pno",
                        "src_count", "src_size",
                        "dst_count", "dst_size",
                        "match",
                        "missing_in_dst", "extra_in_dst",
                        "src_folders", "dest_path",
                    ]
                ],
                width="stretch",
                height=420,
            )

            # --- 差分PDF一覧（1ファイル=1行） ---
            diff_rows: list[dict] = []
            for rec in rows_cmp:
                if (year_filter is not None) and (rec.get("year") != year_filter):
                    continue

                year = rec["year"]
                pno  = rec["pno"]
                dest_path = rec.get("dest_path", "")
                src_folders = rec.get("src_folders", "")

                for name in rec.get("missing_list", []):
                    diff_rows.append({
                        "year": year, "pno": pno, "delta": "missing_in_dst",
                        "filename": name, "dest_path": dest_path, "src_folders": src_folders,
                    })
                for name in rec.get("extra_list", []):
                    diff_rows.append({
                        "year": year, "pno": pno, "delta": "extra_in_dst",
                        "filename": name, "dest_path": dest_path, "src_folders": src_folders,
                    })

            st.markdown("#### 差分PDF一覧（1ファイル=1行）")
            if diff_rows:
                df_diff = pd.DataFrame(diff_rows).sort_values(["year", "pno", "delta", "filename"]).reset_index(drop=True)
                st.dataframe(df_diff, width="stretch", height=420)
                csv_bytes = df_diff.to_csv(index=False).encode("utf-8-sig")
                st.download_button(
                    "⬇️ 差分PDF一覧をCSVでダウンロード",
                    data=csv_bytes,
                    file_name="pdf_differences.csv",
                    mime="text/csv",
                )
            else:
                st.info("差分PDFはありません。")
        else:
            st.info("年を入力して『▶ 出力』を押すと、詳細（pno別と差分一覧）を表示します。")



thick_divider("#007ACC", 4)

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
# ④ セクション内の入力（既存行をこの1行に置換）
dest_base_text = st.text_input(
    "コピー先ベース（既定：organized_docs_root/report/pdf）",
    value=str((Path(PATHS.organized_docs_root).expanduser().resolve() / "report" / "pdf")),
    key="dest_base_input",
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
