# pages/70_sample_PDFビューア.py
# ------------------------------------------------------------
# 📄 Sample PDF ビューア（サムネイル）＋ 階層チェック選択
# - ルート: /Volumes/Extreme SSD/RAG_data/sample
# - 直下のフォルダ（例: current, 2024）を第1階層として選択
# - OCR 実行なし（既存 *_ocr.pdf は表示・集計のみ）
# ------------------------------------------------------------

from __future__ import annotations
from pathlib import Path
from typing import Optional
import streamlit as st

# Optional: pdf.js ビューア
try:
    from streamlit_pdf_viewer import pdf_viewer  # pip install streamlit-pdf-viewer
    HAS_PDFJS = True
except Exception:
    HAS_PDFJS = False

# 依存 lib
from lib.pdf.io import render_thumb_png, read_pdf_bytes, read_pdf_b64
from lib.pdf.info import quick_pdf_info
from lib.pdf.images import analyze_pdf_images, extract_embedded_images
from lib.pdf.text import analyze_pdf_texts
from lib.pdf.paths import rel_from

# viewer util
from lib.viewer.files import list_dirs, list_pdfs, is_ocr_name
from lib.viewer.pdf_flags import is_pdf_locked

# *_skip.pdf 検出（あれば使う／無ければフォールバック）
try:
    from lib.viewer.files import is_skip_name  # ある場合
except Exception:
    def is_skip_name(p: Path) -> bool:
        return p.suffix.lower() == ".pdf" and p.stem.endswith("_skip")

# ---------- ページ設定 ----------
st.set_page_config(page_title="Sample PDF ビューア", page_icon="📘", layout="wide")
st.title("📘 Sample PDF ビューア（Extreme SSD / RAG_data/sample）")

with st.expander("ℹ️ このページの役割（sample：OCR実行なし）", expanded=False):
    st.markdown(r"""
- `/Volumes/Extreme SSD/RAG_data/sample` 配下を階層選択し、フォルダ別に **sidecar の `ocr` 状態や *_skip / *_ocr を集計表示**
- 任意PDFを選んで **サムネイル一覧 → 個別プレビュー**
- さらに **画像埋め込みの集計/抽出** と **OCRなしテキスト抽出（get_text）** を確認

※本ページは OCR 実行を行いません。`*_ocr.pdf` は既存生成物として表示・集計のみです。
""")

# ========== ルート ==========
default_pdf_root = Path("/Volumes/Extreme SSD/RAG_data/sample").expanduser().resolve()

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
        thumb_px = st.number_input("サムネ幅(px)", 120, 800, 280, 20)

    st.subheader("ビューア表示")
    viewer_width  = st.slider("幅(px)", 600, 1600, 1000, 20)
    viewer_height = st.slider("高さ(px)", 400, 1600, 900, 20)

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

# ========== セッション状態（キー衝突回避のため prefix） ==========
if "sample70_sel_top" not in st.session_state:
    st.session_state.sample70_sel_top = set()
if "sample70_sel_mid" not in st.session_state:
    st.session_state.sample70_sel_mid = set()
if "sample70_sel_pdf" not in st.session_state:
    st.session_state.sample70_sel_pdf = set()
if "sample70_pdf_selected" not in st.session_state:
    st.session_state.sample70_pdf_selected = None

# ============================================================
# 上位フォルダ選択（sample 直下：current, 2024, ...）
# ============================================================
st.subheader("上位フォルダ選択（sample 直下）")
st.caption("第1階層フォルダ（例: current / 2024）をチェック選択します。選ばれたフォルダ直下のサブフォルダが次の①で展開されます。")

top_folders = list_dirs(pdf_root)
if not top_folders:
    st.info("上位フォルダが見つかりません。")
    st.stop()

cols_top = st.columns(6)
for i, d in enumerate(top_folders):
    checked = cols_top[i % 6].checkbox(d.name, key=f"sample70_top_{d.name}")
    if checked:
        st.session_state.sample70_sel_top.add(d.name)
    else:
        st.session_state.sample70_sel_top.discard(d.name)

st.divider()

# ============================================================
# ①-集計：サブフォルダ別の内訳（全幅1行・チェック付き）
# ============================================================
st.subheader("①-集計：サブフォルダ別の内訳（全幅1行・チェック付き）")

st.markdown("""
**凡例（sidecar `_side.json` の `ocr` 状態）**
- 📄 : sidecar なし（テキストPDF扱い）
- ⏳ : unprocessed（OCR未処理）
- ✅ : done（OCR正常処理済）
- 🔤 : text（テキストPDFと判断）
- ⏭ : skipped（処理対象外）
- 🔒 : locked（パスワード保護）
- ❌ : failed（OCR失敗）
- 🚫 : `<basename>_skip.pdf`（ファイル名でスキップ指定）
- ✨ : `*_ocr.pdf`（OCR生成物：**総数から除外**し、別カウント）
""")

ICONS = {
    "a": "📄",
    "b": "⏳",
    "c": "✅",
    "d": "🔤",
    "e": "⏭",
    "f": "🔒",
    "g": "❌",
    "_skip": "🚫",
    "_ocr": "✨",
}

def sidecar_path_for(pdf: Path) -> Path:
    return pdf.with_name(pdf.stem + "_side.json")

def load_sidecar_ocr(path: Path) -> Optional[str]:
    try:
        import json
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        v = d.get("ocr")
        return str(v) if v is not None else None
    except Exception:
        return None

def fmt3(n: int) -> str:
    return f"{n:03d}"

for top_name in sorted(st.session_state.sample70_sel_top):
    tdir = pdf_root / top_name
    subdirs = list_dirs(tdir)
    if not subdirs:
        continue

    st.markdown(f"**/{top_name}**")

    for sd in subdirs:
        pdfs = list_pdfs(sd)

        a_no_side_text = b_unprocessed = c_done = d_text = e_skipped = f_locked = g_failed = 0
        skip_files = 0
        ocr_generated = 0
        any_unprocessed = False

        for p in pdfs:
            if is_ocr_name(p):
                ocr_generated += 1
                continue
            if is_skip_name(p):
                skip_files += 1
                continue

            sc = sidecar_path_for(p)
            if sc.exists():
                status = load_sidecar_ocr(sc)
                if status == "unprocessed":
                    b_unprocessed += 1
                    any_unprocessed = True
                elif status == "done":
                    c_done += 1
                elif status == "text":
                    d_text += 1
                elif status == "skipped":
                    e_skipped += 1
                elif status == "locked":
                    f_locked += 1
                elif status == "failed":
                    g_failed += 1
                else:
                    pass
            else:
                a_no_side_text += 1

        base_total = max(0, len(pdfs) - ocr_generated)
        bucket_sum = (a_no_side_text + b_unprocessed + c_done + d_text + e_skipped + f_locked + g_failed + skip_files)

        suffix = []
        if bucket_sum != base_total:
            suffix.append("⚠️内訳不一致")
        if any_unprocessed:
            suffix.append("❌unprocessedあり")

        status_tail = f"｜{ICONS['_ocr']}*_ocr: {ocr_generated}"
        status_tail += (" ｜ " + "・".join(suffix)) if suffix else " ｜ ✅集計OK"

        label = (
            f"{sd.name}｜合計（✨除く）: {fmt3(base_total)}｜"
            f"{ICONS['a']} {fmt3(a_no_side_text)} / "
            f"{ICONS['b']} {fmt3(b_unprocessed)} / "
            f"{ICONS['c']} {fmt3(c_done)} / "
            f"{ICONS['d']} {fmt3(d_text)} / "
            f"{ICONS['e']} {fmt3(e_skipped)} / "
            f"{ICONS['f']} {fmt3(f_locked)} / "
            f"{ICONS['g']} {fmt3(g_failed)} / "
            f"{ICONS['_skip']} {fmt3(skip_files)} "
            f"{status_tail}"
        )

        key_mid = f"sample70_midagg_{top_name}/{sd.name}"
        checked = st.checkbox(label, key=key_mid, value=False)
        mid_val = f"{top_name}/{sd.name}"
        if checked:
            st.session_state.sample70_sel_mid.add(mid_val)
        else:
            st.session_state.sample70_sel_mid.discard(mid_val)

# sel_mid の整合性
valid_mids = set()
for top_name in sorted(st.session_state.sample70_sel_top):
    tdir = pdf_root / top_name
    if not tdir.exists():
        continue
    for sd in list_dirs(tdir):
        valid_mids.add(f"{top_name}/{sd.name}")
st.session_state.sample70_sel_mid = {m for m in st.session_state.sample70_sel_mid if m in valid_mids}

st.divider()

# ============================================================
# ② PDFファイル選択
# ============================================================
st.subheader("② PDFファイル選択（①で選択したサブフォルダ直下）")
st.caption("①でチェックしたサブフォルダ直下のPDFを列挙します。🔒（パスワード保護）は選択不可として警告表示します。")

cols_pdf = st.columns(3)
k = 0
for mid in sorted(st.session_state.sample70_sel_mid):
    top_name, sub_name = mid.split("/", 1)
    sdir = pdf_root / top_name / sub_name
    pdfs = list_pdfs(sdir)
    if not pdfs:
        continue

    st.markdown(f"**/{top_name}/{sub_name}**")

    for p in pdfs:
        locked = is_pdf_locked(p)

        if locked:
            pages = "?"
            badge = "🔒 保護PDF"
        else:
            info = quick_pdf_info(str(p), p.stat().st_mtime_ns)
            pages = int(info.get("pages") or 0)

            if is_ocr_name(p) and info.get("kind") == "画像PDF":
                badge = "✨ OCR後の画像PDF"
            elif is_skip_name(p):
                badge = "⏭ スキップ指定"
            else:
                kind = str(info.get("kind") or "不明")
                badge = "🔤 テキストPDF" if kind == "テキストPDF" else ("🖼 画像PDF" if kind == "画像PDF" else "❓ 不明")

        label = f"{top_name}/{sub_name} / {p.name} — {badge}・📄 {pages}ページ"
        key = f"sample70_pdf_{top_name}/{sub_name}/{p.name}"
        checked = cols_pdf[k % 3].checkbox(label, key=key)

        if checked:
            if locked:
                cols_pdf[k % 3].warning("このPDFはパスワード保護されています。選択をスキップしました。")
                st.session_state.sample70_sel_pdf.discard(str(p))
                try:
                    relp = rel_from(p, pdf_root)
                    if st.session_state.sample70_pdf_selected == relp:
                        st.session_state.sample70_pdf_selected = None
                except Exception:
                    pass
            else:
                st.session_state.sample70_sel_pdf.add(str(p))
        else:
            st.session_state.sample70_sel_pdf.discard(str(p))

        k += 1

# ============================================================
# ③ サムネイル
# ============================================================
st.subheader("③ サムネイル（選択PDF）")
st.caption("②で選択したPDFをグリッド表示します。各カードの『👁 開く』で下部ビューアに切り替わります。")

selected_pdf_paths = [Path(s) for s in sorted(st.session_state.sample70_sel_pdf)]
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
                cols_thumb[c].image(png, caption=rel, width=int(thumb_px))
            except Exception as e:
                cols_thumb[c].warning(f"サムネ生成失敗: {rel}\n{e}")

            if cols_thumb[c].button("👁 開く", key=f"sample70_open_{rel}"):
                st.session_state.sample70_pdf_selected = rel

st.divider()

# ============================================================
# 👁 ビューア
# ============================================================
st.subheader("👁 ビューア")
st.caption("st.pdf / pdf.js / ブラウザプラグインから選択可能。下部で画像・テキスト解析も確認できます。")
st.caption(f"現在の方式: {viewer_mode}")

if st.session_state.sample70_pdf_selected is None and st.session_state.sample70_sel_pdf:
    any_first = sorted(st.session_state.sample70_sel_pdf)[0]
    try:
        st.session_state.sample70_pdf_selected = rel_from(Path(any_first), pdf_root)
    except Exception:
        st.session_state.sample70_pdf_selected = None

if st.session_state.sample70_pdf_selected is None:
    st.info("上のサムネイルから『👁 開く』を押すと、ここにプレビューを表示します。")
else:
    current_rel = st.session_state.sample70_pdf_selected
    current_abs = (pdf_root / current_rel).resolve()
    st.write(f"**{current_rel}**")

    if not current_abs.exists():
        st.error("選択されたファイルが見つかりません。")
        st.stop()

    try:
        if viewer_mode == "Streamlit内蔵（st.pdf）":
            data = read_pdf_bytes(str(current_abs), current_abs.stat().st_mtime_ns)
            st.pdf(data, height=int(viewer_height), key=f"sample70_stpdf_{current_rel}")

        elif viewer_mode.startswith("pdf.js") and HAS_PDFJS:
            data = read_pdf_bytes(str(current_abs), current_abs.stat().st_mtime_ns)
            pdf_viewer(data, width=int(viewer_width), height=int(viewer_height), key=f"sample70_pdfjs_{current_rel}")

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
            st.download_button(
                "📥 このPDFをダウンロード",
                data=f.read(),
                file_name=current_abs.name,
                mime="application/pdf",
                key=f"sample70_dl_{current_rel}",
            )

        st.divider()
        st.subheader("🖼 画像埋め込み情報")
        img_info = analyze_pdf_images(
            str(current_abs),
            current_abs.stat().st_mtime_ns,
            mode=("sample" if scan_mode == "sample" else "all"),
            sample_pages=int(scan_sample_pages),
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
                    st.info("XObject として抽出できませんでした。ページ見た目サイズで再サンプリングを試みます。")
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
                        cols_img[i % 3].image(im["bytes"], caption=im.get("label", ""), width=320)
                        total_shown += 1

                if total_shown == 0:
                    st.warning(
                        "抽出できる埋め込み画像が見つかりませんでした。\n"
                        "- 画像がベクター描画/フォントの可能性\n"
                        "- 抽出モードを『ページ見た目サイズで再サンプリング』に変更すると拾える場合があります。"
                    )
                else:
                    st.download_button(
                        "🗜 抽出画像をZIPでダウンロード",
                        data=result.get("zip_bytes", b""),
                        file_name=f"{current_abs.stem}_images.zip",
                        mime="application/zip",
                        key=f"sample70_imgzip_{current_rel}",
                    )

        st.divider()
        st.subheader("📝 抽出テキスト（get_text：OCRなし）")
        text_info = analyze_pdf_texts(
            str(current_abs),
            current_abs.stat().st_mtime_ns,
            mode=("sample" if scan_mode == "sample" else "all"),
            sample_pages=int(scan_sample_pages),
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
