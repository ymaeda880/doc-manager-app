# pages/30_PDFビューア（ocr）.py
# ------------------------------------------------------------
# 📄 PDF ビューア（サムネイル）＋ 階層チェック選択（organized_docs_root/report/pdf）
# - quick_pdf_info が正常動作する前提でシンプル化
# - レイアウト: 上部(①〜⑤) 全幅 / 最下部にビューア
# - ② サブフォルダ行に「🖼画像/🔤テキスト/✨OCR処理後の画像PDF（*_ocr.pdf）」＋ OCR状況（✅/❌）を表示
# - ③ OCR（画像PDF→テキスト層付きPDF, <name>_ocr.pdf を生成）※ *_ocr.pdf は対象外
# ------------------------------------------------------------
"""
pages/30_PDFビューア.py

目的
----
organized_docs_root/report/pdf（既定）配下の階層を辿り、選択したPDFを
サムネイル表示・詳細表示（画像埋め込み/抽出・テキスト抽出）するツール。
加えて、サブフォルダ単位で画像PDFのOCR状況（*_ocr.pdf の有無）を可視化し、
不足分の一括OCR実行をサポートする。

前提
----
- lib.pdf.info.quick_pdf_info が正常動作し、PDFの「種別（画像/テキスト/不明）」や
  ページ数などの軽量情報を返すこと
- PyMuPDF（fitz）が利用可能で、パスワード保護の判定ができること
- OCR は lib/pdf/ocr.py の run_ocr を利用（Python API 優先、失敗時 CLI へフォールバック）

依存
----
- streamlit
- streamlit-pdf-viewer（任意, pdf.js ビューア）
- PyMuPDF（fitz）
- OCRmyPDF + Tesseract（OCR 実行のため）

UIフロー（画面上の処理 ①〜👁）
------------------------------
① 上位フォルダ選択 …… /report/pdf 直下の第1階層をチェック選択
② サブフォルダ選択 …… ①で選んだフォルダ直下を表示し、PDF内訳＋OCR状況（✅/❌）を表示
   ※ *_ocr.pdf は ✨=「OCR処理後の画像PDF」として別カウント・別表示
③ OCR一括実行     …… ②で選んだサブフォルダ内の「原本の画像PDF（*_ocr以外）」から
                         *_ocr.pdf 未作成分のみOCR生成（*_ocr.pdf は対象外）
④ PDFファイル選択 …… ②で選んだサブフォルダ直下のPDFをチェック選択
⑤ サムネイル表示   …… ④で選んだPDFのサムネイルをグリッド表示（👁でビューアへ）
👁 ビューア        …… 選択中PDFのプレビュー（st.pdf / pdf.js / ブラウザプラグイン）
"""

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
from lib.pdf.ocr import run_ocr  # ★ OCR 実行

# ---------- ちょいCSS（縦の余白を圧縮 & グリッドを詰める） ----------
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

# ========== ヘルパ ==========
def _is_pdf_locked(p: Path) -> bool:
    """
    PyMuPDF を用いて PDF がパスワード保護されているかを簡易判定する。
    判定不能時は False（未ロック扱い）
    """
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(p))
        locked = bool(getattr(doc, "needs_pass", False))
        doc.close()
        return locked
    except Exception:
        return False

def _is_ocr_name(p: Path) -> bool:
    """
    ファイル名が *_ocr.pdf かどうかを判定（大文字小文字は区別）
    """
    return p.suffix.lower() == ".pdf" and p.stem.endswith("_ocr")

def _list_dirs(p: Path) -> List[Path]:
    """隠しフォルダを除外して直下のディレクトリを列挙。"""
    try:
        return sorted([c for c in p.iterdir() if c.is_dir() and not c.name.startswith(".")],
                      key=lambda x: x.name.lower())
    except Exception:
        return []

def _list_pdfs(p: Path) -> List[Path]:
    """隠しファイルを除外して直下の .pdf を列挙。"""
    if not p.exists():
        return []
    res: List[Path] = []
    for c in p.iterdir():
        if c.is_file() and not c.name.startswith(".") and c.suffix.lower() == ".pdf":
            res.append(c)
    return sorted(res, key=lambda x: x.name.lower())

@st.cache_data(show_spinner=False)
def _pdf_kind_counts(sig: Tuple[Tuple[str, int], ...]) -> Tuple[int, int, int]:
    """
    quick_pdf_info によりフォルダ直下PDFの種別を集計。（未使用の場合あり）
    """
    img = txt = 0
    for path_str, mtime_ns in sig:
        info = quick_pdf_info(path_str, mtime_ns)
        kind = (info.get("kind") or "").strip()
        if kind == "テキストPDF":
            txt += 1
        elif kind == "画像PDF":
            img += 1
    return img, txt, len(sig)

def _make_sig_from_dir(dir_path: Path) -> Tuple[Tuple[str, int], ...]:
    """フォルダ直下のPDFを (path, mtime_ns) の一覧に。"""
    pdfs = _list_pdfs(dir_path)
    return tuple(sorted([(str(p), p.stat().st_mtime_ns) for p in pdfs], key=lambda t: t[0].lower()))

def _dest_ocr_path(src: Path) -> Path:
    """入力PDFの出力先パス（*_ocr.pdf）を返す。"""
    return src.with_name(src.stem + "_ocr.pdf")

# ============================================================
# ① 上位フォルダ（全幅）
# ============================================================
st.subheader("① 上位フォルダ選択（organized/report/pdf 下）")
st.caption("第1階層のフォルダ（例: 年）をチェック選択します。選ばれたフォルダの直下が次の②で展開されます。")

top_folders = _list_dirs(pdf_root)
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
# ② サブフォルダ（全幅）
# ============================================================
st.subheader("② サブフォルダ選択（選んだ上位フォルダの直下）")
st.caption(
    "各サブフォルダのPDF内訳（🖼 画像 / 🔤 テキスト / ✨ OCR後の画像PDF[*_ocr.pdf]（ocrを行っても画像pdfであるファイル）と、"
    "原本画像PDFに対する *_ocr.pdf の充足状況を表示します。"
    "すべて揃っていれば ✅、不足があれば ❌。🔒 はパスワード保護で判定対象外。"
)
st.markdown(
    "ocrを失敗した場合には，_ocrは作成されません．その場合はX印が残ります．",
    unsafe_allow_html=True
)

SUB_COLS = 4

for tname in sorted(st.session_state.sel_top):
    tdir = pdf_root / tname
    subdirs = _list_dirs(tdir)
    if not subdirs:
        continue

    st.markdown(f"**/{tname}**")

    cols_mid = st.columns(SUB_COLS)
    for j, sd in enumerate(subdirs):
        key = f"mid_{tname}/{sd.name}"

        pdfs = _list_pdfs(sd)
        total = len(pdfs)

        img_cnt = 0
        ocr_img_cnt = 0
        txt_cnt = 0
        img_total = 0
        img_ocr_ok = 0
        img_missing = 0
        locked_img = 0

        for p in pdfs:
            is_ocr_name = _is_ocr_name(p)
            try:
                info = quick_pdf_info(str(p), p.stat().st_mtime_ns)
                k = info.get("kind")
            except Exception:
                continue

            if not is_ocr_name and k == "画像PDF" and _is_pdf_locked(p):
                locked_img += 1
                continue

            if k == "画像PDF":
                if is_ocr_name:
                    ocr_img_cnt += 1
                    continue
                else:
                    img_cnt += 1
                    if not _is_pdf_locked(p):
                        img_total += 1
                        dst = _dest_ocr_path(p)
                        if dst.exists():
                            img_ocr_ok += 1
                        else:
                            img_missing += 1

            elif k == "テキストPDF":
                txt_cnt += 1

        if img_total > 0:
            mark = "✅" if img_missing == 0 else "❌"
            ocr_tip = f"{mark} OCR: {img_ocr_ok}/{img_total}"
        else:
            ocr_tip = "— OCR対象なし"
        if locked_img > 0:
            ocr_tip += f"（🔒 {locked_img}）"

        base_counts = f"{sd.name}：{total}（🖼 {img_cnt} / 🔤 {txt_cnt} / ✨ {ocr_img_cnt}）"
        if txt_cnt == 0 and (img_cnt + ocr_img_cnt) > 0:
            label = f"{base_counts} ｜ {ocr_tip} ⚠️画像のみ"
        else:
            label = f"{base_counts} ｜ {ocr_tip}"

        checked = cols_mid[j % SUB_COLS].checkbox(label, key=key)
        if checked:
            st.session_state.sel_mid.add(f"{tname}/{sd.name}")
        else:
            st.session_state.sel_mid.discard(f"{tname}/{sd.name}")

st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

# ============================================================
# ③ OCR 一括実行
# ============================================================
st.subheader("③ OCR（画像PDF → テキスト層付きPDF）")
st.caption(
    "②で選択した各サブフォルダについて、"
    "原本の画像PDF（*_ocr ではない & 🔒でない）のうち *_ocr.pdf が未作成のものを一括OCRします。"
    "出力は同フォルダに <元名>_ocr.pdf（必要に応じ .txt sidecar）として保存します。"
)

summary_lines: List[str] = []
total_targets = 0
total_skipped_exist = 0

for mid in sorted(st.session_state.sel_mid):
    tname, sname = mid.split("/", 1)
    sdir = pdf_root / tname / sname
    pdfs = _list_pdfs(sdir)
    if not pdfs:
        continue

    img_list: List[Path] = []
    exist_ocr = 0
    for p in pdfs:
        if _is_ocr_name(p):
            continue
        if _is_pdf_locked(p):
            continue
        try:
            info = quick_pdf_info(str(p), p.stat().st_mtime_ns)
            if info.get("kind") == "画像PDF":
                dst = _dest_ocr_path(p)
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
    col_ocr_btn2.info("OCRすべき新規の画像PDFはありません（すでに _ocr が存在します）。")

if do_ocr and st.session_state.sel_mid:
    prog = st.progress(0, text="準備中…")
    done = 0
    failed: List[str] = []
    created: List[str] = []
    skipped_locked: List[str] = []
    skipped_exists: List[str] = []

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

            for p in _list_pdfs(sdir):
                if _is_ocr_name(p):
                    continue

                try:
                    if _is_pdf_locked(p):
                        skipped_locked.append(str(rel_from(p, pdf_root)))
                        panel.markdown(
                            f"**現在の状況**\n\n"
                            f"- フォルダ: `{tname}/{sname}`\n"
                            f"- 🔒 保護PDFをスキップ: `{rel_from(p, pdf_root)}`\n"
                            f"- 進捗: {done}/{max(total_targets,1)}"
                        )
                        continue
                    info = quick_pdf_info(str(p), p.stat().st_mtime_ns)
                    if info.get("kind") != "画像PDF":
                        panel.markdown(
                            f"**現在の状況**\n\n"
                            f"- フォルダ: `{tname}/{sname}`\n"
                            f"- スキップ（画像PDF以外）: `{rel_from(p, pdf_root)}`\n"
                            f"- 進捗: {done}/{max(total_targets,1)}"
                        )
                        continue
                except Exception:
                    panel.markdown(
                        f"**現在の状況**\n\n"
                        f"- フォルダ: `{tname}/{sname}`\n"
                        f"- スキップ（判定不能）: `{rel_from(p, pdf_root)}`\n"
                        f"- 進捗: {done}/{max(total_targets,1)}"
                    )
                    continue

                dst = _dest_ocr_path(p)
                if dst.exists():
                    skipped_exists.append(str(rel_from(p, pdf_root)))
                    panel.markdown(
                        f"**現在の状況**\n\n"
                        f"- フォルダ: `{tname}/{sname}`\n"
                        f"- 既存のためスキップ: `{rel_from(p, pdf_root)}`\n"
                        f"- 進捗: {done}/{max(total_targets,1)}"
                    )
                    continue

                try:
                    panel.markdown(
                        f"**現在の状況**\n\n"
                        f"- フォルダ: `{tname}/{sname}`\n"
                        f"- ⏳ 処理中: `{rel_from(p, pdf_root)}`\n"
                        f"- 進捗: {done}/{max(total_targets,1)}"
                    )
                    sidecar_path: Optional[Path] = dst.with_suffix(".txt") if ocr_sidecar else None
                    run_ocr(
                        src=p,
                        dst=dst,
                        lang=ocr_lang,
                        optimize=int(ocr_optimize),
                        jobs=int(ocr_jobs),
                        rotate_pages=bool(ocr_rotate),
                        sidecar_path=sidecar_path,
                        progress_cb=lambda s: panel.markdown(
                            f"**現在の状況**\n\n- ⏳ {s}", unsafe_allow_html=False
                        ),
                    )
                    created.append(str(rel_from(dst, pdf_root)))
                    log.write(f"✅ 生成: `{rel_from(dst, pdf_root)}`")
                    panel.markdown(
                        f"**現在の状況**\n\n"
                        f"- フォルダ: `{tname}/{sname}`\n"
                        f"- ✅ 完了: `{rel_from(dst, pdf_root)}`\n"
                        f"- 進捗: {done+1}/{max(total_targets,1)}"
                    )
                except Exception as e:
                    failed.append(f"{rel_from(p, pdf_root)} → {e}")
                    log.write(f"❌ 失敗: `{rel_from(p, pdf_root)}` — {e}")
                    panel.markdown(
                        f"**現在の状況**\n\n"
                        f"- フォルダ: `{tname}/{sname}`\n"
                        f"- ❌ 失敗: `{rel_from(p, pdf_root)}`\n"
                        f"- 進捗: {done+1}/{max(total_targets,1)}"
                    )
                finally:
                    done += 1
                    total = max(total_targets, 1)
                    prog.progress(min(done / total, 1.0), text=f"OCR {done}/{total}")

        status.update(label="OCR 完了", state="complete")

    st.markdown("**実行結果**")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("新規作成 (_ocr)", len(created))
    c2.metric("既存のためスキップ", len(skipped_exists))
    c3.metric("保護PDFスキップ", len(skipped_locked))
    c4.metric("失敗", len(failed))

    with st.expander("🆕 作成されたファイル一覧", expanded=False):
        st.text("\n".join(created) if created else "（なし）")
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
    pdfs = _list_pdfs(sdir)
    if not pdfs:
        continue

    st.markdown(f"**/{tname}/{sname}**")

    for p in pdfs:
        locked = _is_pdf_locked(p)

        if locked:
            kind = "保護（要パスワード）"
            pages = "?"
            badge = "🔒 保護PDF"
        else:
            info = quick_pdf_info(str(p), p.stat().st_mtime_ns)
            kind = str(info.get("kind") or "不明")
            pages = int(info.get("pages") or 0)
            if _is_ocr_name(p) and kind == "画像PDF":
                badge = "✨ OCR後の画像PDF"
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
                badge = "✨ OCR後の画像PDF" if (_is_ocr_name(p) and info.get('kind') == '画像PDF') \
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
