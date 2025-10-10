# pages/50_PDFビューア.py (OCRセクション削除版)
# ------------------------------------------------------------
# 📄 PDF ビューア（サムネイル）＋ 階層チェック選択（organized_docs_root/report/pdf）
# - quick_pdf_info が正常動作する前提でシンプル化
# - レイアウト: 上部(①〜⑤) 全幅 / 最下部にビューア
# - ② サブフォルダ行に「🖼画像/🔤テキスト/✨OCR処理後の画像PDF（*_ocr.pdf）」＋ OCR状況（✅/❌）を表示
# - ③ OCR（画像PDF→テキスト層付きPDF, <name>_ocr.pdf を生成）※ *_ocr.pdf は対象外  ←★ このセクションを削除
# - ⏭ *_skip.pdf を別集計し、OCR対象から除外
# ------------------------------------------------------------


from __future__ import annotations
from pathlib import Path
from typing import List, Tuple, Optional
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
from lib.app_paths import PATHS  # organized_docs_root を既定に
# from lib.pdf.ocr import run_ocr  # ★ OCR 実行 ← 使用箇所がなくなるためコメントアウト推奨

# 切り出し済みユーティリティ（lib/viewer/*）
from lib.viewer.files import list_dirs, list_pdfs, is_ocr_name, dest_ocr_path
from lib.viewer.pdf_flags import is_pdf_locked
from lib.viewer.signatures import make_sig_from_dir, pdf_kind_counts

# *_skip.pdf 検出（あれば使う／無ければフォールバック）
try:
    from lib.viewer.files import is_skip_name  # ある場合
except Exception:
    def is_skip_name(p: Path) -> bool:
        return p.suffix.lower() == ".pdf" and p.stem.endswith("_skip")

# ---------- ちょいCSS ----------
st.set_page_config(page_title="PDF ビューア", page_icon="📄", layout="wide")
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

st.title("📄 PDF ビューア（organized/report/pdf から階層選択）")
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
    # ③ セクションを削除したため、以下は『将来の再有効化用』に残すか、気になる場合はコメントアウトしてください。
    # st.divider()
    # st.header("OCR 設定（無効化中）")
    # st.caption("このページではOCRの実行は行いません。設定は表示のみです。")
    # ocr_lang = st.text_input("言語（Tesseractのlang）", value="jpn+eng", disabled=True)
    # ocr_optimize = st.slider("optimize（1=既定 / 0=無効 / 2=強）", 0, 3, 1, 1, disabled=True)
    # ocr_jobs = st.slider("並列ジョブ数", 1, 8, 2, 1, disabled=True)
    # ocr_rotate = st.checkbox("自動回転（rotate_pages）", value=True, disabled=True)
    # ocr_sidecar = st.checkbox("Sidecar（.txtを別出力）", value=False, disabled=True)

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
# 上位フォルダ（全幅）
# ============================================================
st.subheader("上位フォルダ選択（organized/report/pdf 下）")


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
# ①-追加集計：上位フォルダ配下のサブフォルダを1行集計表示（全幅）
#   - *_ocr.pdf は「生成物」として総数から除外し、別カウントで表示
#   - <basename>_skip.pdf は (3) “スキップ指定” として別カウント
#   - sidecar (<basename>_side.json) の ocr ステータス別に (a)〜(g) を集計
#   - (b) unprocessed が1つでもあれば ❌ を表示
#   - (a)〜(g) + (3) の合計 と、フォルダ内PDF総数（*_ocr 除く）が異なれば ⚠️ を表示
#   - 行頭チェックで st.session_state.sel_mid に追加（後段の②と同じ集合を使える）
# ============================================================
# ============================================================
# ①-追加集計（アイコン版）：サブフォルダ別の内訳（全幅1行・チェック付き）
# ============================================================
st.subheader("①-集計：サブフォルダ別の内訳（全幅1行・チェック付き）")

# ---- 凡例（最初に表示）----
st.markdown("""
**凡例（sidecar `_side.json` の `ocr` 状態）**

- 📄 : sidecar なし（テキストPDF扱い） *(a)*
- ⏳ : unprocessed（OCR未処理） *(b)*
- ✅ : done（OCR正常処理済） *(c)*
- 🔤 : text（見た目は画像PDFだが中身を確認してテキストと判断） *(d)*
- ⏭ : skipped（処理対象外として明示） *(e)*
- 🔒 : locked（パスワード保護） *(f)*
- ❌ : failed（OCR失敗） *(g)*
- 🚫 : `<basename>_skip.pdf`（ファイル名でスキップ指定） *(3)*
- ✨ : `*_ocr.pdf`（OCR生成物：**総数から除外**し、別カウント）
""")

ICONS = {
    "a": "📄",  # sidecarなし（テキスト扱い）
    "b": "⏳",  # unprocessed
    "c": "✅",  # done
    "d": "🔤",  # text
    "e": "⏭",  # skipped
    "f": "🔒",  # locked
    "g": "❌",  # failed
    "_skip": "🚫",  # <basename>_skip.pdf
    "_ocr": "✨",   # *_ocr.pdf（生成物）
}

st.caption("各サブフォルダのPDFを sidecar（_side.json）の ocr ステータスで集計します。*_ocr.pdf は除外カウント。`<basename>_skip.pdf` は (3) として別計上。")

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

for tname in sorted(st.session_state.sel_top):
    tdir = pdf_root / tname
    subdirs = list_dirs(tdir)
    if not subdirs:
        continue

    st.markdown(f"**/{tname}**")

    for sd in subdirs:
        pdfs = list_pdfs(sd)

        # カウンタ初期化
        a_no_side_text   = 0  # (a)
        b_unprocessed    = 0  # (b)
        c_done           = 0  # (c)
        d_text           = 0  # (d)
        e_skipped        = 0  # (e)
        f_locked         = 0  # (f)
        g_failed         = 0  # (g)
        skip_files       = 0  # (3) <basename>_skip.pdf
        ocr_generated    = 0  # *_ocr.pdf（生成物：合計から除外）
        any_unprocessed  = False

        for p in pdfs:
            if is_ocr_name(p):              # ✨ 生成物 → 総数から除外
                ocr_generated += 1
                continue
            if is_skip_name(p):             # 🚫 ファイル名スキップ
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
                    # 未知値は未分類（整合性チェックで検知）
                    pass
            else:
                a_no_side_text += 1

        # 合計整合性チェック（✨*_ocr を除く）
        base_total = max(0, len(pdfs) - ocr_generated)
        bucket_sum = (a_no_side_text + b_unprocessed + c_done +
                      d_text + e_skipped + f_locked + g_failed +
                      skip_files)

        suffix = []
        if bucket_sum != base_total:
            suffix.append("⚠️内訳不一致")
        if any_unprocessed:
            suffix.append("❌unprocessedあり")

        status_tail = f"｜{ICONS['_ocr']}*_ocr: {ocr_generated}"
        if suffix:
            status_tail += " ｜ " + "・".join(suffix)
        else:
            status_tail += " ｜ ✅集計OK"

        # 1行ラベル（全幅・チェック付き）
        # 各サブフォルダ行の数字部分フォーマットを3桁ゼロ埋めで整形
        def fmt3(n: int) -> str:
            """数字を3桁ゼロ埋めで表示（例: 7→007, 80→080, 116→116）"""
            return f"{n:03d}"

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


        checked = st.checkbox(label, key=f"midagg_{tname}/{sd.name}", value=False)
        if checked:
            st.session_state.sel_mid.add(f"{tname}/{sd.name}")
        else:
            st.session_state.sel_mid.discard(f"{tname}/{sd.name}")

# ①-集計の直後に追加：選択の整合性を整える & 仕切り線
#  - sel_top に含まれない年配下の sel_mid を除去
#  - 実在しないサブフォルダの sel_mid を除去
valid_mids = set()
for tname in sorted(st.session_state.sel_top):
    tdir = pdf_root / tname
    if not tdir.exists():
        continue
    for sd in list_dirs(tdir):
        valid_mids.add(f"{tname}/{sd.name}")

st.session_state.sel_mid = {m for m in st.session_state.sel_mid if m in valid_mids}

st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

# ============================================================
# ② PDFファイル選択
# ============================================================
st.subheader("② PDFファイル選択（①で選択したサブフォルダ直下）")
st.caption("①でチェックしたサブフォルダ直下のPDFを列挙します。🔒（パスワード保護）は選択不可として警告表示します。")


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
# ③ サムネイル
# ============================================================
st.subheader("③ サムネイル（選択PDF）")
st.caption("②で選択したPDFをグリッド表示します。各カードの『👁 開く』で下部ビューアに切り替わります。")


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
    st.info("上のサムネイルから『👁 開く』を押すと、ここにプレビューを表示します。")
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
                        "- 上部の抽出モードを『ページ見た目サイズで再サンプリング』に変更すると拾える場合があります。"
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
