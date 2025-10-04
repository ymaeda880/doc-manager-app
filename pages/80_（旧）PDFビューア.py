"""
pages/80_（旧）PDFビューア.py
=================================
📄 サムネイル付きの PDF ビューア（Streamlit ページ）

目的
----
- 指定ルート配下の PDF を列挙し、**サムネイル表示 → 選択 → 右ペインでプレビュー**までをワンストップで行う。
- 追加で **埋め込み画像の集計・抽出**、**テキストの先頭抜粋**などの軽量解析ができる。

外部依存（lib/*）
-----------------
- lib.pdf.io:
    - `render_thumb_png(path, width_px, mtime_ns)` …… サムネイルPNGを返す（キャッシュ前提のヘルパ）
    - `read_pdf_bytes(path, mtime_ns)` …… PDF バイナリ
    - `read_pdf_b64(path, mtime_ns)` …… base64 エンコード済み PDF 文字列
- lib.pdf.info:
    - `quick_pdf_info(path, mtime_ns)` …… {kind, pages} の簡易情報
- lib.pdf.images:
    - `analyze_pdf_images(path, mtime_ns, mode, sample_pages)` …… 埋め込み画像の集計
    - `extract_embedded_images(current_abs, img_info, mode, dpi)` …… 画像の抽出（表示用bytes/ZIP）
- lib.pdf.text:
    - `analyze_pdf_texts(path, mtime_ns, mode, sample_pages)` …… 各ページ冒頭のテキスト抽出（OCRなし）
- lib.pdf.paths:
    - `iter_pdfs(root)` …… ルート配下の PDF Path 一覧を返す
    - `rel_from(path, root)` …… ルートからの相対パスを文字列で返す
- lib.app_paths:
    - `PATHS.pdf_root` …… 既定の PDF ルート（config/settings.toml に準拠）

任意依存
--------
- `streamlit_pdf_viewer`（pdf.js ベースのビューア）: ある場合のみ選択肢に追加

UI 概要
-------
- **サイドバー（設定）**
  - ルート: 「PDF ルートフォルダ」 … 既定は `PATHS.pdf_root`
  - レイアウト: 「グリッド列数」「サムネ幅(px)」
  - 絞り込み: 「ファイル名フィルタ」「年フォルダフィルタ(例: 2024,2025)」
  - ビューア: 表示方式（st.pdf / pdf.js / ブラウザプラグイン）、サイズ（幅/高さ）、倍率プリセット（プラグイン時）
  - 解析範囲: 「全ページ」または「先頭Nページ」
  - 画像抽出: 表示ON/OFF、抽出モード（XObject/再サンプリング）、再サンプルDPI

- **左ペイン（サムネイル）**
  - `iter_pdfs()` で列挙した PDF をグリッドで表示
  - 各カード: サムネ + 簡易情報(kind/pages) + 「👁 開く」ボタン
  - 「👁 開く」押下で `st.session_state["pdf_selected"]` に相対パスを保存

- **右ペイン（ビューア）**
  - 選択中 PDF の相対/絶対パスを表示
  - 表示方式：
    - 「Streamlit内蔵（st.pdf）」 → `st.pdf(bytes)`
    - 「pdf.js」 → `streamlit_pdf_viewer(bytes)`（インストール時のみ）
    - 「ブラウザPDFプラグイン」 → `<object data="data:application/pdf;base64,...#zoom=...">`
  - ダウンロードボタン（現在表示中のPDF）
  - 画像の埋め込み集計（総数、形式別、ページ別内訳）と、任意の抽出＆ZIPダウンロード
  - テキスト抽出（各ページ冒頭500文字のプレビュー）

設定ファイルとの関係（PATHS）
-----------------------------
- `from lib.app_paths import PATHS` を利用し、既定の PDF ルートに `PATHS.pdf_root` を採用
- 例: `config/settings.toml` の `[locations.<env>].pdf_root` が `project:data/pdf` なら
  実体は `<APP_ROOT>/data/pdf` になる

セッション状態
--------------
- `st.session_state["pdf_selected"]`: 現在選択中の PDF を **ルートからの相対パス** で保持
  - 未選択時は最初の PDF を自動選択

使い方（Usage）
---------------
1) 依存 lib を配置・インポート可能にする（上記「外部依存」を参照）
2) `streamlit run pages/10_PDFビューア.py` を実行
3) サイドバーの「PDF ルートフォルダ」を必要に応じて変更
4) サムネから「👁 開く」で右ペインに詳細を表示
5) 必要に応じて埋め込み画像の抽出・ダウンロード、テキストの確認を行う

前提・注意
----------
- `st.set_page_config(...)` は **ページ最初の Streamlit 呼び出し** である必要がある（本ファイルは遵守）
- 画像抽出はファイルサイズが大きくなる場合あり（ZIP圧縮を提供）
- 解析は PDF 構造・フォント/エンコードに依存し、すべての PDF で完全に動作する保証はない
- OCR は行わない（テキスト抽出は `get_text` ベース）。画像PDFはテキストが空になる

パフォーマンスTips
-------------------
- サムネ幅（小さめ）・グリッド列数（控えめ）で一覧描画を軽くできる
- 「先頭Nページのみ調査」で重い PDF の解析時間を短縮
- `mtime_ns` をキーに各 lib 側でキャッシュされる前提

拡張ポイント
------------
- 独自のファイルメタ（タイトル/タグ等）を表示したい場合は、サムネカード生成部分を拡張
- ビューア方式の追加（例: iframe で外部ビューアを叩く等）
- 解析ロジック差し替え（`analyze_pdf_images/texts` の戻りフォーマットに追従）
"""

# pages/10_PDFビューア.py
# ------------------------------------------------------------
# 📄 PDF ビューア（サムネイル）
# ------------------------------------------------------------
from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Any
import streamlit as st

# Optional: pdf.js ビューア
try:
    from streamlit_pdf_viewer import pdf_viewer  # pip install streamlit-pdf-viewer
    HAS_PDFJS = True
except Exception:
    HAS_PDFJS = False

# 直接 lib/pdf/* を利用
from lib.pdf.io import render_thumb_png, read_pdf_bytes, read_pdf_b64
from lib.pdf.info import quick_pdf_info
from lib.pdf.images import analyze_pdf_images, extract_embedded_images
from lib.pdf.text import analyze_pdf_texts
from lib.pdf.paths import iter_pdfs, rel_from

# 標準パス
from lib.app_paths import PATHS  # PATHS.pdf_root を PDF 既定に使用

# ========== UI ==========
st.set_page_config(page_title="PDF ビューア", page_icon="📄", layout="wide")
st.title("📄 PDF ビューア")

with st.sidebar:
    st.header("設定")
    pdf_root = Path(st.text_input("PDF ルートフォルダ", value=str(PATHS.pdf_root))).expanduser().resolve()

    c1, c2 = st.columns(2)
    with c1:
        grid_cols = st.number_input("グリッド列数", 2, 8, 4, 1)
    with c2:
        thumb_px = st.number_input("サムネ幅(px)", 120, 600, 260, 20)

    st.divider()
    name_filter = st.text_input("ファイル名フィルタ（部分一致）", value="").strip()
    year_filter = st.text_input("年フォルダフィルタ（例: 2024,2025）", value="").strip()

    st.divider()
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
    st.subheader("解析範囲")
    scan_mode_label = st.radio("調査方式", ["全ページを調査", "先頭Nページのみ調査"], index=0)
    if scan_mode_label == "先頭Nページのみ調査":
        scan_sample_pages = st.slider("先頭Nページ", 1, 50, 6, 1)
        scan_mode = "sample"
    else:
        scan_sample_pages = 6
        scan_mode = "all"

    st.divider()
    st.subheader("埋め込み画像の出力設定")
    show_embedded_images = st.checkbox("埋め込み画像を表示する", value=False)
    extract_mode = st.radio(
        "抽出モード",
        ["XObjectそのまま（真の埋め込み画像）", "ページ見た目サイズで再サンプリング"],
        index=0,
        help="前者はPDFに埋め込まれた元画像。後者はページ上の見た目サイズで切出し。"
    )
    resample_dpi = st.slider(
        "再サンプリング時のDPI", 72, 300, 144, 12,
        help="抽出モードが再サンプリングの時のみ有効"
    )

if "pdf_selected" not in st.session_state:
    st.session_state.pdf_selected = None

# ========== データ取得 ==========
pdf_paths = iter_pdfs(pdf_root)
if name_filter:
    pdf_paths = [p for p in pdf_paths if name_filter.lower() in p.name.lower()]
if year_filter:
    years = {y.strip() for y in year_filter.split(",") if y.strip()}
    if years:
        def _has_year(p: Path) -> bool:
            try:
                parts = p.relative_to(pdf_root).parts
            except ValueError:
                parts = p.parts
            return any(part in years for part in parts[:2])
        pdf_paths = [p for p in pdf_paths if _has_year(p)]

if not pdf_paths:
    st.info("PDF が見つかりません。")
    st.stop()

left, right = st.columns([2, 3], gap="large")

# ========== 左：サムネ ==========
with left:
    st.subheader("📚 サムネイル")
    rows = (len(pdf_paths) + int(grid_cols) - 1) // int(grid_cols)
    idx = 0
    for _ in range(rows):
        cols = st.columns(int(grid_cols))
        for c in range(int(grid_cols)):
            if idx >= len(pdf_paths):
                break
            p = pdf_paths[idx]; idx += 1
            rel = rel_from(p, pdf_root)
            mtime_ns = p.stat().st_mtime_ns

            try:
                png = render_thumb_png(str(p), int(thumb_px), mtime_ns)
                cols[c].image(png, caption=rel, width="stretch")
            except Exception as e:
                cols[c].warning(f"サムネ生成失敗: {rel}\n{e}")

            try:
                info = quick_pdf_info(str(p), mtime_ns)
                cols[c].markdown(
                    f"<div style='font-size:12px;color:#555;'>🧾 <b>{info['kind']}</b>・📄 {info['pages']}ページ</div>",
                    unsafe_allow_html=True,
                )
            except Exception:
                cols[c].markdown(
                    "<div style='font-size:12px;color:#555;'>🧾 種別不明・📄 ページ数不明</div>",
                    unsafe_allow_html=True
                )

            if cols[c].button("👁 開く", key=f"open_{rel}", width="stretch"):
                st.session_state.pdf_selected = rel

# ========== 右：ビューア ==========
with right:
    # 👁 ビューアの見出し + 選択中のビューア方式を表示
    st.subheader(f"👁 ビューア")
    st.caption(f"現在の方式: {viewer_mode}")
    # st.subheader("👁 ビューア")
    current_rel = st.session_state.pdf_selected or rel_from(pdf_paths[0], pdf_root)
    current_abs = (pdf_root / current_rel).resolve()
    st.write(f"**{current_rel}**")

    if not current_abs.exists():
        st.error("選択されたファイルが見つかりません。")
    else:
        try:
            # 左上バッジ用ラベル
            if viewer_mode == "ブラウザPDFプラグイン":
                zoom_label = f"倍率: {zoom_preset}"
            elif viewer_mode == "Streamlit内蔵（st.pdf）":
                zoom_label = "倍率: 可変（st.pdf）"
            else:
                zoom_label = "倍率: 可変（pdf.js）"

            # 表示方式ごとに出力
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

            # DLボタン
            with open(current_abs, "rb") as f:
                st.download_button("📥 このPDFをダウンロード", data=f.read(),
                                   file_name=current_abs.name, mime="application/pdf")

            # ========== 画像埋め込み情報 ==========
            st.divider()
            st.subheader("🖼 画像埋め込み情報")
            img_info = analyze_pdf_images(
                str(current_abs), current_abs.stat().st_mtime_ns,
                mode=scan_mode, sample_pages=int(scan_sample_pages)
            )

            c = st.columns(4)
            c[0].metric("走査ページ数", f"{img_info['scanned_pages']}/{img_info['total_pages']}")
            c[1].metric("画像総数", f"{img_info['total_images']}")
            if img_info["formats_count"]:
                formats_sorted = sorted(img_info["formats_count"].items(), key=lambda x: x[1], reverse=True)
                top_fmt = ", ".join([f"{k}:{v}" for k, v in formats_sorted[:2]])
                rest_total = sum(v for _, v in formats_sorted[2:])
                c[2].metric("形式の上位", top_fmt or "-")
                c[3].metric("他形式の合計", str(rest_total))
            else:
                c[2].metric("形式の上位", "-")
                c[3].metric("他形式の合計", "0")

            with st.expander("ページ別の詳細（形式と枚数）", expanded=False):
                lines = []
                for row in img_info["pages"]:
                    fmts = ", ".join(row["formats"]) if row["formats"] else "-"
                    lines.append(f"p.{row['page']:>4}: 画像 {row['count']:>3} 枚｜形式 [{fmts}]")
                st.text("\n".join(lines) if lines else "（画像は検出されませんでした）")

            # ========== 埋め込み画像の抽出＆ZIP ==========
            if show_embedded_images and img_info["total_images"] > 0:
                with st.expander("埋め込み画像を表示 / ダウンロード", expanded=False):
                    mode_key = "xobject" if extract_mode.startswith("XObject") else "resample"
                    result = extract_embedded_images(
                        current_abs,
                        img_info,
                        mode=mode_key,
                        dpi=int(resample_dpi)
                    )
                    for page_out in result["pages"]:
                        st.markdown(f"**p.{page_out['page']} の画像**")
                        imgs = page_out["images"]
                        cols = st.columns(min(3, max(1, len(imgs))))
                        for i, im in enumerate(imgs):
                            if im["bytes"]:
                                cols[i % 3].image(im["bytes"], caption=im["label"], use_container_width=True)
                            else:
                                cols[i % 3].warning(im["label"])
                    st.download_button(
                        "🗜 抽出画像をZIPでダウンロード",
                        data=result["zip_bytes"],
                        file_name=f"{current_abs.stem}_images.zip",
                        mime="application/zip"
                    )

            # ========== テキスト抽出情報 ==========
            st.divider()
            st.subheader("📝 抽出テキスト（get_textの抽出：OCRは行っていない）")
            text_info = analyze_pdf_texts(
                str(current_abs), current_abs.stat().st_mtime_ns,
                mode=scan_mode, sample_pages=int(scan_sample_pages)
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
