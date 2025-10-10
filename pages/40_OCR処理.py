# pages/40_OCR処理.py
# ------------------------------------------------------------
# 📄 OCR処理（organized/report/pdf 配下）
# - ② は <basename>_side.json の "ocr":"unprocessed" 起点でフォルダを表示
# - ③ の OCR 成否に応じて <basename>_side.json の "ocr" を "done"/"failed" に更新
# - ④〜 は既存ビューア機能を踏襲
# ------------------------------------------------------------

"""
pages/40_OCR処理.py
===================

概要
----
organized_docs_root/report/pdf 配下の階層から対象フォルダを選び、画像PDFに対して
OCR（OCRmyPDF）を一括実行する Streamlit ページ。

サイドカー（<basename>_side.json）を起点に以下のワークフローを実装する：

1) ① 上位フォルダ選択
   - 第1階層（例: 年度等）を複数選択

2) ② サブフォルダ選択（side.json の ocr=unprocessed 起点）
   - 各サブフォルダ直下の *_side.json を走査し、
     "type": "image_pdf" かつ "ocr": "unprocessed" を1件以上含むフォルダのみを表示

3) ③ OCR 一括実行
   - ②で選択した各サブフォルダ内の PDF から、
     *_skip / *_ocr / 🔒保護PDF / sidecar.ocr=skipped を除外
   - quick_pdf_info() で「画像PDF」と判定されたものだけを対象
   - *_ocr.pdf が未作成のファイルを OCR
   - 成否に応じて sidecar の "ocr" を "done" / "failed" に更新
   - 🔒保護PDFは "locked" に更新してスキップ

4) ④ PDFファイル選択
   - ②で選んだサブフォルダ直下のPDFを列挙し、チェックで複数選択
   - 🔒保護PDFは選択不可として警告

5) ⑤ サムネイル表示 & 👁 ビューア
   - 選択したPDFのサムネイルをグリッド表示
   - st.pdf / pdf.js / ブラウザプラグイン でプレビュー
   - 画像埋め込み情報や get_text による抽出テキストも確認可能

依存
----
- lib.app_paths.PATHS
- lib.pdf.io: render_thumb_png, read_pdf_bytes, read_pdf_b64
- lib.pdf.info: quick_pdf_info
- lib.pdf.images: analyze_pdf_images, extract_embedded_images
- lib.pdf.paths: rel_from
- lib.pdf.text: analyze_pdf_texts
- lib.pdf.ocr: run_ocr
- lib.viewer.files: list_dirs, list_pdfs, is_ocr_name, dest_ocr_path
- lib.viewer.pdf_flags: is_pdf_locked
- lib.pdf.sidecar: sidecar_path_for, load_sidecar_dict, find_pdf_for_sidecar, update_sidecar_ocr

サイドカー仕様（例）
-------------------
{
  "type": "image_pdf",
  "created_at": "2025-10-07T08:42:00+09:00",
  "ocr": "unprocessed"  // "done" | "failed" | "skipped" | "locked" | "unprocessed"
}

注意
----
- 本ページは「画像PDF」を OCR でテキスト層付きPDF（*_ocr.pdf）へ変換する用途に特化。
- ファイル名で *_skip を付けたもの、または sidecar.ocr=skipped のものは OCR 対象外。
- 既に *_ocr.pdf が存在する原本PDFはスキップする。
"""

from __future__ import annotations
from pathlib import Path
from typing import List, Optional, Tuple
import json
import streamlit as st

# Optional: pdf.js ビューア
try:
    from streamlit_pdf_viewer import pdf_viewer  # pip install streamlit-pdf-viewer
    HAS_PDFJS = True
except Exception:
    HAS_PDFJS = False

# 依存 lib
from lib.app_paths import PATHS
from lib.pdf.io import render_thumb_png, read_pdf_bytes, read_pdf_b64
from lib.pdf.info import quick_pdf_info
from lib.pdf.images import analyze_pdf_images, extract_embedded_images
from lib.pdf.paths import rel_from
from lib.pdf.text import analyze_pdf_texts
from lib.pdf.ocr import run_ocr

# viewer ユーティリティ
from lib.viewer.files import list_dirs, list_pdfs, is_ocr_name, dest_ocr_path
from lib.viewer.pdf_flags import is_pdf_locked

# sidecar ユーティリティ（lib 下に切り出し済み）
from lib.pdf.sidecar import (
    sidecar_path_for,
    load_sidecar_dict,
    find_pdf_for_sidecar,
    update_sidecar_ocr,
)

# *_skip.pdf 検出（無ければフォールバック）
try:
    from lib.viewer.files import is_skip_name
except Exception:
    def is_skip_name(p: Path) -> bool:
        """ファイル名が *_skip.pdf かどうかを判定する簡易フォールバック。
        
        Parameters
        ----------
        p : Path
            対象 PDF のパス

        Returns
        -------
        bool
            拡張子が .pdf かつベース名が *_skip で終わる場合 True
        """
        return p.suffix.lower() == ".pdf" and p.stem.endswith("_skip")
    
# --- sidecarの ocr 状態を読む＆skip判定 ---
def get_sidecar_ocr_state(p: Path) -> Optional[str]:
    """与えられた PDF のサイドカーから OCR 状態文字列を取得する。
    
    Parameters
    ----------
    p : Path
        対象 PDF のパス

    Returns
    -------
    Optional[str]
        サイドカーが存在し "ocr" キーがあればその値（例: "unprocessed", "done"...）
        サイドカーが無い/壊れている場合は None
    """
    sc = sidecar_path_for(p)
    if not sc.exists():
        return None
    try:
        d = load_sidecar_dict(sc)
        return d.get("ocr") if isinstance(d, dict) else None
    except Exception:
        return None

def is_skipped_by_name_or_json(p: Path) -> bool:
    """ファイル名または sidecar により OCR をスキップすべきか判定する。
    
    次のいずれかに該当すれば True:
      - ファイル名が *_skip.pdf
      - sidecar の "ocr" が "skipped"

    Parameters
    ----------
    p : Path
        対象 PDF のパス

    Returns
    -------
    bool
        スキップ条件に合致すれば True、そうでなければ False
    """
    if is_skip_name(p):
        return True
    return get_sidecar_ocr_state(p) == "skipped"

# ---------- ちょいCSS ----------
st.set_page_config(page_title="OCR処理", page_icon="📄", layout="wide")
st.markdown(
    """
    <style>
      .block-container {padding-top: 1rem; padding-bottom: 2rem; max-width: 1300px;}
      h1, h2, h3 {margin: 0.2rem 0 0.6rem 0;}
      .stCheckbox > label, label {line-height: 1.2;}
      .stMarkdown p {margin: 0.2rem 0;}
      .tight {margin-top: 0.25rem; margin-bottom: 0.25rem;}
      .divider {margin: .6rem 0 1rem 0; border-bottom: 1px solid #e5e7eb;}
      .muted {color:#6b7280;}
      .mono {font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📄 OCR処理（organized/report/pdf から階層選択）")

st.info("使用ルート：organized_docs_root")

# ========== ルート ==========
default_pdf_root = (Path(str(PATHS.organized_docs_root)).expanduser().resolve() / "report" / "pdf")
with st.sidebar:
    st.header("基点フォルダ")
    pdf_root = Path(st.text_input("PDF ルートフォルダ", value=str(default_pdf_root))).expanduser().resolve()
    st.caption(f"実パス: `{pdf_root}`")

if not pdf_root.exists():
    st.error("PDF ルートが存在しません。パスを確認してください。")
    st.stop()

# ========== サイドバー：表示・解析設定 ==========
with st.sidebar:
    st.divider()
    st.header("表示設定")
    c1, c2 = st.columns(2)
    with c1:
        grid_cols = st.number_input("グリッド列数", 2, 8, 4, 1)
    with c2:
        thumb_px = st.number_input("サムネ幅(px)", 120, 600, 260, 20)

    st.subheader("ビューア表示")
    viewer_width  = st.slider("幅(px)", 600, 1400, 900, 20)
    viewer_height = st.slider("高さ(px)", 400, 1400, 820, 20)
    viewer_choices = ["Streamlit内蔵（st.pdf）"]
    if HAS_PDFJS:
        viewer_choices.append("pdf.js（streamlit_pdf_viewer）")
    viewer_choices.append("ブラウザPDFプラグイン")
    viewer_mode = st.radio("方式", viewer_choices, index=0)
    zoom_preset = st.selectbox("初期倍率（プラグイン時）", ["page-fit", "page-width", "100", "125", "75"], index=0)

    st.divider()
    st.header("解析範囲")
    scan_mode_label = st.radio("調査方式", ["全ページを調査", "先頭Nページのみ調査"], index=0)
    if scan_mode_label == "先頭Nページのみ調査":
        scan_sample_pages = st.slider("先頭Nページ", 1, 50, 6, 1)
        scan_mode = "sample"
    else:
        scan_sample_pages = 6
        scan_mode = "all"

    st.divider()
    st.header("埋め込み画像の出力設定")
    show_embedded_images = st.checkbox("埋め込み画像を表示する", value=False)
    extract_mode = st.radio(
        "抽出モード",
        ["XObjectそのまま（真の埋め込み画像）", "ページ見た目サイズで再サンプリング"],
        index=0,
    )
    resample_dpi = st.slider("再サンプリング時のDPI", 72, 300, 144, 12)

    # ---------- ★ OCR 設定 ----------
    st.divider()
    st.header("OCR 設定")
    ocr_lang = st.text_input("言語（Tesseractのlang）", value="jpn+eng")
    ocr_optimize = st.slider("optimize（1=既定 / 0=無効 / 2=強）", 0, 3, 1, 1)
    ocr_jobs = st.slider("並列ジョブ数", 1, 8, 2, 1)
    ocr_rotate = st.checkbox("自動回転（rotate_pages）", value=True)
    ocr_sidecar = st.checkbox("Sidecar（.txtを別出力）", value=False)

# ========== セッション状態 ==========
if "sel_top" not in st.session_state:
    st.session_state.sel_top = set()
if "sel_mid" not in st.session_state:
    st.session_state.sel_mid = set()
if "sel_pdf" not in st.session_state:
    st.session_state.sel_pdf = set()
if "pdf_selected" not in st.session_state:
    st.session_state.pdf_selected = None

# ============================================================
# ① 上位フォルダ（全幅）
# ============================================================
st.subheader("① 上位フォルダ選択（organized/report/pdf 下）")
st.caption("第1階層のフォルダ（例: 年）をチェック選択します。選ばれたフォルダの直下が次の②で展開されます。")

top_folders = list_dirs(pdf_root)
if not top_folders:
    st.info("上位フォルダが見つかりません。")
    st.stop()

cols_top = st.columns(6)
for i, d in enumerate(top_folders):
    checked = cols_top[i % 6].checkbox(d.name, key=f"top_{d.name}")
    if checked:
        st.session_state.sel_top.add(d.name)
    else:
        st.session_state.sel_top.discard(d.name)

st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

# ============================================================
# ② サブフォルダ選択（<basename>_side.json の "ocr": "unprocessed" だけを見る）
#    ※ ファイル名の後にページ数を表示
# ============================================================
st.subheader("② サブフォルダ選択（side.json の ocr=unprocessed のみ表示）")
st.caption("フォルダ内の *_side.json を起点にし、'ocr': 'unprocessed' を1つ以上含むフォルダだけを表示します。PDFの種別判定はしません。")

SUB_COLS = 3
shown_any = False

def _safe_pages(p: Path) -> str:
    """安全にページ数を取得する（失敗時は '?' を返す）。
    
    Parameters
    ----------
    p : Path
        対象 PDF のパス

    Returns
    -------
    str
        ページ数（整数文字列）または "?"（取得失敗時）
    """
    try:
        info = quick_pdf_info(str(p), p.stat().st_mtime_ns)
        pages = info.get("pages")
        return str(int(pages)) if pages else "?"
    except Exception:
        return "?"

for tname in sorted(st.session_state.sel_top):
    tdir = pdf_root / tname
    subdirs = list_dirs(tdir)
    if not subdirs:
        continue

    st.markdown(f"**/{tname}**")
    cols_mid = st.columns(SUB_COLS)
    col_idx = 0

    for sd in subdirs:
        sidecars = sorted(sd.glob("*_side.json"))
        if not sidecars:
            continue

        # このフォルダ内で ocr=unprocessed の side.json を収集
        unprocessed: list[tuple[Path, Path]] = []  # (pdf_path, sidecar_path)
        for sc in sidecars:
            data = load_sidecar_dict(sc)
            if not (isinstance(data, dict) and data.get("type") == "image_pdf"):
                continue
            if data.get("ocr") == "unprocessed":
                pdf = find_pdf_for_sidecar(sc)  # 拡張子大小ゆらぎ対応
                if pdf and not is_skip_name(pdf):
                    unprocessed.append((pdf, sc))

        if not unprocessed:
            continue  # このフォルダは非表示

        shown_any = True

        # ✅ セル確保
        cell = cols_mid[col_idx % SUB_COLS]

        # チェックボックス（件数付き）
        label = f"{sd.name}： unprocessed {len(unprocessed)} 件"
        checked = cell.checkbox(label, key=f"mid_{tname}/{sd.name}")

        # 📄 ファイル名一覧（ベース名＋ページ数を最大 N 件表示）
        max_show = 20
        lines = []
        for pdf, _sc in unprocessed[:max_show]:
            pages = _safe_pages(pdf)
            lines.append(f"• {pdf.name}（📄 {pages}p）")

        if lines:
            cell.markdown(
                "<div style='margin-left:1.8rem; margin-top:-0.3rem; line-height:1.2; color:#555;'>"
                + "<br>".join([f"<span class='mono'>{ln}</span>" for ln in lines])
                + "</div>",
                unsafe_allow_html=True,
            )
            if len(unprocessed) > max_show:
                cell.caption(f"…ほか {len(unprocessed) - max_show} 件")

        col_idx += 1

        if checked:
            st.session_state.sel_mid.add(f"{tname}/{sd.name}")
        else:
            st.session_state.sel_mid.discard(f"{tname}/{sd.name}")

if not shown_any:
    st.info("ocr=unprocessed の side.json を含むフォルダは見つかりませんでした。")

st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

# ============================================================
# ③ OCR 一括実行（成功→side.json=done、失敗→failed）
# ============================================================
st.subheader("③ OCR（画像PDF → テキスト層付きPDF）")
st.caption(
    "②で選択した各サブフォルダについて、原本の画像PDF（*_ocr ではない & 🔒でない & ⏭ ではない）のうち "
    "*_ocr.pdf が未作成のものを一括OCRします。完了/失敗で side.json の 'ocr' を更新します。"
)

summary_lines: List[str] = []
total_targets = 0
total_skipped_exist = 0

for mid in sorted(st.session_state.sel_mid):
    tname, sname = mid.split("/", 1)
    sdir = pdf_root / tname / sname
    pdfs = list_pdfs(sdir)
    if not pdfs:
        continue

    img_list: List[Path] = []
    exist_ocr = 0

    for p in pdfs:
        # *_skip / *_ocr / 🔒保護PDF は除外
        if is_skip_name(p) or is_ocr_name(p) or is_pdf_locked(p):
            continue

        # ★ sidecar の ocr=skipped も除外
        try:
            sc = sidecar_path_for(p)
            if sc.exists():
                d = load_sidecar_dict(sc)
                if isinstance(d, dict) and d.get("ocr") == "skipped":
                    continue
        except Exception:
            pass

        # 種別チェック
        try:
            info = quick_pdf_info(str(p), p.stat().st_mtime_ns)
            if info.get("kind") == "画像PDF":
                dst = dest_ocr_path(p)
                if dst.exists():
                    exist_ocr += 1
                else:
                    img_list.append(p)
        except Exception:
            pass

    total_targets += len(img_list)
    total_skipped_exist += exist_ocr
    summary_lines.append(f"- /{tname}/{sname}：対象 {len(img_list)} 件（既存 _ocr: {exist_ocr} 件）")

if not summary_lines:
    st.caption("（②でサブフォルダを選ぶと、ここにOCR対象のサマリーが表示されます）")
else:
    st.markdown("**対象サマリー**")
    st.markdown("<div class='mono'>" + "<br>".join(summary_lines) + "</div>", unsafe_allow_html=True)

col_ocr_btn1, col_ocr_btn2 = st.columns([1, 2])
do_ocr = col_ocr_btn1.button("▶️ 選択サブフォルダをまとめてOCR実行", use_container_width=True)
if total_targets == 0 and summary_lines:
    col_ocr_btn2.info("OCRすべき新規の画像PDFはありません（すでに _ocr が存在、または ⏭ / 🔒 が指定されています）。")

if do_ocr and st.session_state.sel_mid:
    prog = st.progress(0, text="準備中…")
    done = 0
    failed: List[str] = []
    created: List[str] = []
    skipped_locked: List[str] = []
    skipped_exists: List[str] = []
    skipped_sidecar: List[str] = []  # *_skip または sidecar=skipped

    with st.status("OCR 実行中…", expanded=True) as status:
        left, right = st.columns([3, 2])
        log = left.container()
        panel = right.empty()

        log.write(f"言語: `{ocr_lang}` ｜ optimize={ocr_optimize} ｜ jobs={ocr_jobs} ｜ rotate_pages={ocr_rotate}")
        if ocr_sidecar:
            log.write("Sidecar: 有効（.txt も出力）")

        for mid in sorted(st.session_state.sel_mid):
            tname, sname = mid.split("/", 1)
            sdir = pdf_root / tname / sname
            log.markdown(f"**/{tname}/{sname}**")

            for p in list_pdfs(sdir):
                # *_ocr は対象外
                if is_ocr_name(p):
                    continue

                relp = str(rel_from(p, pdf_root))

                # ⏭ ファイル名/sidecar によるスキップ
                if is_skip_name(p):
                    skipped_sidecar.append(relp)
                    panel.markdown(
                        f"**現在の状況**\n\n- ⏭ *_skip 名のためスキップ: `{relp}`\n- 進捗: {done}/{max(total_targets,1)}"
                    )
                    continue
                try:
                    sc = sidecar_path_for(p)
                    if sc.exists():
                        d = load_sidecar_dict(sc)
                        if isinstance(d, dict) and d.get("ocr") == "skipped":
                            skipped_sidecar.append(relp)
                            panel.markdown(
                                f"**現在の状況**\n\n- ⏭ sidecar=skipped のためスキップ: `{relp}`\n- 進捗: {done}/{max(total_targets,1)}"
                            )
                            continue
                except Exception:
                    pass

                # 🔒 保護PDF → sidecar を 'locked' に更新してスキップ
                if is_pdf_locked(p):
                    try:
                        update_sidecar_ocr(p, "locked")
                        log.write(f"🔒 locked: `{relp}` → side.json を 'locked' に更新")
                    except Exception as e:
                        log.write(f"⚠️ locked: `{relp}` → side.json 更新失敗: {e}")
                    skipped_locked.append(relp)
                    panel.markdown(
                        f"**現在の状況**\n\n- 🔒 保護PDFをスキップ: `{relp}`\n- 進捗: {done}/{max(total_targets,1)}"
                    )
                    continue

                # 画像PDF以外はスキップ
                try:
                    info = quick_pdf_info(str(p), p.stat().st_mtime_ns)
                    if info.get("kind") != "画像PDF":
                        panel.markdown(
                            f"**現在の状況**\n\n- スキップ（画像PDF以外）: `{relp}`\n- 進捗: {done}/{max(total_targets,1)}"
                        )
                        continue
                except Exception:
                    panel.markdown(
                        f"**現在の状況**\n\n- スキップ（判定不能）: `{relp}`\n- 進捗: {done}/{max(total_targets,1)}"
                    )
                    continue

                # 既に *_ocr.pdf があるならスキップ
                dst = dest_ocr_path(p)
                if dst.exists():
                    skipped_exists.append(relp)
                    panel.markdown(
                        f"**現在の状況**\n\n- 既存のためスキップ: `{relp}`\n- 進捗: {done}/{max(total_targets,1)}"
                    )
                    continue

                # OCR 実行
                try:
                    panel.markdown(
                        f"**現在の状況**\n\n- ⏳ 処理中: `{relp}`\n- 進捗: {done}/{max(total_targets,1)}"
                    )
                    sidecar_txt_path: Optional[Path] = dst.with_suffix(".txt") if ocr_sidecar else None
                    run_ocr(
                        src=p,
                        dst=dst,
                        lang=ocr_lang,
                        optimize=int(ocr_optimize),
                        jobs=int(ocr_jobs),
                        rotate_pages=bool(ocr_rotate),
                        sidecar_path=sidecar_txt_path,
                        progress_cb=lambda s: panel.markdown(f"**現在の状況**\n\n- ⏳ {s}"),
                    )
                    created.append(str(rel_from(dst, pdf_root)))
                    log.write(f"✅ 生成: `{rel_from(dst, pdf_root)}`")
                    update_sidecar_ocr(p, "done")  # 成功 → done
                    panel.markdown(
                        f"**現在の状況**\n\n- ✅ 完了: `{rel_from(dst, pdf_root)}`\n- 進捗: {done+1}/{max(total_targets,1)}"
                    )
                except Exception as e:
                    update_sidecar_ocr(p, "failed")  # 失敗 → failed
                    failed.append(f"{relp} → {e}")
                    log.write(f"❌ 失敗: `{relp}` — {e}")
                    panel.markdown(
                        f"**現在の状況**\n\n- ❌ 失敗: `{relp}`\n- 進捗: {done+1}/{max(total_targets,1)}"
                    )
                finally:
                    done += 1
                    prog.progress(min(done / max(total_targets, 1), 1.0), text=f"OCR {done}/{max(total_targets,1)}")

        status.update(label="OCR 完了", state="complete")

    st.markdown("**実行結果**")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("新規作成 (_ocr)", len(created))
    c2.metric("既存のためスキップ", len(skipped_exists))
    c3.metric("⏭ 名前/sidecarスキップ", len(skipped_sidecar))
    c4.metric("🔒 保護PDFスキップ", len(skipped_locked))
    c5.metric("失敗", len(failed))

    with st.expander("🆕 作成されたファイル一覧", expanded=False):
        st.text("\n".join(created) if created else "（なし）")
    with st.expander("⏭ 名前/sidecar スキップ", expanded=False):
        st.text("\n".join(skipped_sidecar) if skipped_sidecar else "（なし）")
    with st.expander("⏭ 既存のためスキップ", expanded=False):
        st.text("\n".join(skipped_exists) if skipped_exists else "（なし）")
    with st.expander("🔒 保護PDFのためスキップ", expanded=False):
        st.text("\n".join(skipped_locked) if skipped_locked else "（なし）")
    with st.expander("❌ 失敗ログ", expanded=False):
        st.text("\n".join(failed) if failed else "（なし）")

st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

# ============================================================
# ④ PDFファイル選択
# ============================================================
st.subheader("④ PDFファイル選択（選んだサブフォルダ直下）")
st.caption("②で選択したサブフォルダ直下のPDFを列挙します。🔒（パスワード保護）は選択不可として警告表示します。")

cols_pdf = st.columns(3)
k = 0
for mid in sorted(st.session_state.sel_mid):
    tname, sname = mid.split("/", 1)
    sdir = pdf_root / tname / sname
    pdfs = list_pdfs(sdir)
    if not pdfs:
        continue

    st.markdown(f"**/{tname}/{sname}**")

    for p in pdfs:
        locked = is_pdf_locked(p)

        if locked:
            kind = "保護（要パスワード）"
            pages = "?"
            badge = "🔒 保護PDF"
        else:
            info = quick_pdf_info(str(p), p.stat().st_mtime_ns)
            kind = str(info.get("kind") or "不明")
            pages = int(info.get("pages") or 0)
            if is_ocr_name(p) and kind == "画像PDF":
                badge = "✨ OCR後の画像PDF"
            elif is_skip_name(p):
                badge = "⏭ スキップ指定"
            else:
                badge = "🔤 テキストPDF" if kind == "テキストPDF" else ("🖼 画像PDF" if kind == "画像PDF" else "❓ 不明")

        label = f"{tname}/{sname} / {p.name} — {badge}・📄 {pages}ページ"

        key = f"pdf_{tname}/{sname}/{p.name}"
        checked = cols_pdf[k % 3].checkbox(label, key=key)

        if checked:
            if locked:
                cols_pdf[k % 3].warning("このPDFはパスワード保護されています。選択をスキップしました。")
                st.session_state.sel_pdf.discard(str(p))
                try:
                    relp = rel_from(p, pdf_root)
                    if st.session_state.pdf_selected == relp:
                        st.session_state.pdf_selected = None
                except Exception:
                    pass
            else:
                st.session_state.sel_pdf.add(str(p))
        else:
            st.session_state.sel_pdf.discard(str(p))

        k += 1

# ============================================================
# ⑤ サムネイル
# ============================================================
st.subheader("⑤ サムネイル（選択PDF）")
st.caption("④で選択したPDFをグリッド表示します。各カードの『👁 開く』で下部ビューアに切り替わります。")

selected_pdf_paths = [Path(s) for s in sorted(st.session_state.sel_pdf)]
if not selected_pdf_paths:
    st.info("左のチェックでPDFを選ぶと、ここにサムネイルが表示されます。")
else:
    rows = (len(selected_pdf_paths) + int(grid_cols) - 1) // int(grid_cols)
    idx = 0
    for _ in range(rows):
        cols_thumb = st.columns(int(grid_cols))
        for c in range(int(grid_cols)):
            if idx >= len(selected_pdf_paths):
                break
            p = selected_pdf_paths[idx]; idx += 1
            rel = rel_from(p, pdf_root)
            mtime_ns = p.stat().st_mtime_ns
            try:
                png = render_thumb_png(str(p), int(thumb_px), mtime_ns)
                cols_thumb[c].image(png, caption=rel, use_container_width=True)
            except Exception as e:
                cols_thumb[c].warning(f"サムネ生成失敗: {rel}\n{e}")
            try:
                info = quick_pdf_info(str(p), mtime_ns)
                if is_skip_name(p):
                    badge = "⏭ スキップ指定"
                else:
                    badge = "✨ OCR後の画像PDF" if (is_ocr_name(p) and info.get('kind') == '画像PDF') \
                            else ("🔤 テキストPDF" if info.get('kind') == 'テキストPDF'
                                  else ("🖼 画像PDF" if info.get('kind') == '画像PDF' else "❓ 不明"))
                cols_thumb[c].markdown(
                    f"<div class='tight' style='font-size:12px;color:#555;'>🧾 <b>{badge}</b>・📄 {info.get('pages','?')}ページ</div>",
                    unsafe_allow_html=True,
                )
            except Exception:
                pass
            if cols_thumb[c].button("👁 開く", key=f"open_{rel}", use_container_width=True):
                st.session_state.pdf_selected = rel

st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

# ============================================================
# 👁 ビューア
# ============================================================
st.subheader("👁 ビューア")
st.caption("現在選択中のPDFを表示します。st.pdf / pdf.js / ブラウザプラグインから選択可能。下部で画像・テキストの解析結果も確認できます。")
st.caption(f"現在の方式: {viewer_mode}")

if st.session_state.pdf_selected is None and st.session_state.sel_pdf:
    any_first = sorted(st.session_state.sel_pdf)[0]
    try:
        st.session_state.pdf_selected = rel_from(Path(any_first), pdf_root)
    except Exception:
        st.session_state.pdf_selected = None

if st.session_state.pdf_selected is None:
    st.info("上のサムネイルから「👁 開く」を押すと、ここにプレビューを表示します。")
else:
    current_rel = st.session_state.pdf_selected
    current_abs = (pdf_root / current_rel).resolve()
    st.write(f"**{current_rel}**")

    if not current_abs.exists():
        st.error("選択されたファイルが見つかりません。")
        st.stop()

    try:
        if viewer_mode == "Streamlit内蔵（st.pdf）":
            data = read_pdf_bytes(str(current_abs), current_abs.stat().st_mtime_ns)
            st.pdf(data, height=int(viewer_height), key=f"stpdf_{current_rel}")
        elif viewer_mode.startswith("pdf.js") and HAS_PDFJS:
            data = read_pdf_bytes(str(current_abs), current_abs.stat().st_mtime_ns)
            pdf_viewer(data, width=int(viewer_width), height=int(viewer_height), key=f"pdfjs_{current_rel}")
        else:
            b64 = read_pdf_b64(str(current_abs), current_abs.stat().st_mtime_ns)
            st.components.v1.html(
                f"""
                <div style="position:relative; border:1px solid #e5e7eb;border-radius:8px;overflow:hidden">
                  <object data="data:application/pdf;base64,{b64}#zoom={zoom_preset}"
                          type="application/pdf" width="{int(viewer_width)}" height="{int(viewer_height)}">
                    <p>PDF を表示できません。下のボタンでダウンロードしてください。</p>
                  </object>
                </div>
                """,
                height=int(viewer_height) + 16,
            )

        with open(current_abs, "rb") as f:
            st.download_button("📥 このPDFをダウンロード", data=f.read(),
                               file_name=current_abs.name, mime="application/pdf")

        st.divider()
        st.subheader("🖼 画像埋め込み情報")
        st.caption("PDF内の埋め込み画像の総数・形式の分布を集計します。")
        img_info = analyze_pdf_images(
            str(current_abs), current_abs.stat().st_mtime_ns,
            mode=("sample" if scan_mode == "sample" else "all"),
            sample_pages=int(scan_sample_pages)
        )
        c = st.columns(4)
        c[0].metric("走査ページ数", f"{img_info['scanned_pages']}/{img_info['total_pages']}")
        c[1].metric("画像総数", f"{img_info['total_images']}")
        if img_info["formats_count"]:
            top = sorted(img_info["formats_count"].items(), key=lambda x: x[1], reverse=True)
            c[2].metric("形式の上位", ", ".join([f"{k}:{v}" for k, v in top[:2]]) or "-")
            c[3].metric("他形式の合計", str(sum(v for _, v in top[2:])))
        else:
            c[2].metric("形式の上位", "-")
            c[3].metric("他形式の合計", "0")

        with st.expander("ページ別の詳細（形式と枚数）", expanded=False):
            lines = []
            for row in img_info["pages"]:
                fmts = ", ".join(row["formats"]) if row["formats"] else "-"
                lines.append(f"p.{row['page']:>4}: 画像 {row['count']:>3} 枚｜形式 [{fmts}]")
            st.text("\n".join(lines) if lines else "（画像は検出されませんでした）")

        if show_embedded_images:
            with st.expander("埋め込み画像を表示 / ダウンロード", expanded=False):
                mode_key = "xobject" if extract_mode.startswith("XObject") else "resample"
                result = extract_embedded_images(str(current_abs), img_info, mode=mode_key, dpi=int(resample_dpi))
                if (not result.get("pages")) and mode_key == "xobject" and img_info.get("total_images", 0) > 0:
                    st.info("XObject として抽出できませんでした。ページ見た目サイズでの再サンプリングを試みます。")
                    result = extract_embedded_images(str(current_abs), img_info, mode="resample", dpi=int(resample_dpi))

                total_shown = 0
                for page_out in result.get("pages", []):
                    st.markdown(f"**p.{page_out['page']} の画像**")
                    imgs = [im for im in page_out.get("images", []) if im.get("bytes")]
                    if not imgs:
                        st.caption("（このページで抽出できる画像はありませんでした）")
                        continue
                    cols_img = st.columns(min(3, max(1, len(imgs))))
                    for i, im in enumerate(imgs):
                        cols_img[i % 3].image(im["bytes"], caption=im.get("label", ""), use_container_width=True)
                        total_shown += 1

                if total_shown == 0:
                    st.warning(
                        "抽出できる埋め込み画像が見つかりませんでした。\n"
                        "- 画像がベクター描画/フォントの可能性\n"
                        "- 上部の抽出モードを「ページ見た目サイズで再サンプリング」に変更すると拾える場合があります。"
                    )
                else:
                    st.download_button(
                        "🗜 抽出画像をZIPでダウンロード",
                        data=result.get("zip_bytes", b""),
                        file_name=f"{current_abs.stem}_images.zip",
                        mime="application/zip",
                    )

        st.divider()
        st.subheader("📝 抽出テキスト（get_textベース：OCRなし）")
        st.caption("PyMuPDFの get_text で取得したテキストをページごとに要約表示します（OCRはしません）。")
        text_info = analyze_pdf_texts(
            str(current_abs), current_abs.stat().st_mtime_ns,
            mode=("sample" if scan_mode == "sample" else "all"),
            sample_pages=int(scan_sample_pages)
        )
        st.write(f"走査ページ数: {text_info['scanned_pages']}/{text_info['total_pages']}")
        if not text_info["pages"]:
            st.info("テキストが抽出できませんでした。")
        else:
            with st.expander("ページごとの抽出テキスト（各ページ冒頭500文字）", expanded=False):
                for row in text_info["pages"]:
                    st.markdown(f"**p.{row['page']}**")
                    st.text(row["text"])

    except Exception as e:
        st.error(f"PDF 表示に失敗しました: {e}")
