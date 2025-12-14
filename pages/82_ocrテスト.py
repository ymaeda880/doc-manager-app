# pages/82_ocrテスト.py
# ------------------------------------------------------------
# 📄 OCR / Text 判定テストページ
#
# - PDF をドラッグ＆ドロップ
# - 画像PDF → OCR
#     - Python API or CLI を選択可能
#     - CLI の場合はページ進捗（Page x / y）表示
#     - OCR 済み PDF をダウンロード可能
# - テキストPDF → テキスト抽出
#     - 抽出テキスト表示
#     - .txt ダウンロード可能
# ------------------------------------------------------------

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import streamlit as st

from lib.pdf.info import quick_pdf_info
from lib.pdf.text import analyze_pdf_texts
from lib.pdf.ocr import run_ocr

# ------------------------------------------------------------
# Page config
# ------------------------------------------------------------
st.set_page_config(
    page_title="OCR / Text テスト",
    page_icon="📄",
    layout="centered",
)

st.title("📄 OCR / Text 判定テスト")

st.markdown(
    """
PDF をアップロードしてください。

- **画像PDF**
  - OCR を実行します
  - **Python API / CLI を選択可能**
  - CLI では **ページ単位の進捗**が表示されます

- **テキストPDF**
  - テキストを抽出して表示
  - `.txt` としてダウンロードできます
"""
)

# ------------------------------------------------------------
# Upload
# ------------------------------------------------------------
uploaded = st.file_uploader("PDF ファイルをドロップ", type=["pdf"])

if uploaded is None:
    st.stop()

# ------------------------------------------------------------
# Save to temp
# ------------------------------------------------------------
with TemporaryDirectory() as tmpdir:
    src = Path(tmpdir) / uploaded.name
    src.write_bytes(uploaded.read())

    info = quick_pdf_info(str(src), src.stat().st_mtime_ns)
    kind = info.get("kind", "不明")
    pages = int(info.get("pages") or 0)

    st.subheader("📌 判定結果")
    st.write(f"- 種別: **{kind}**")
    st.write(f"- ページ数: **{pages}**")

    # ========================================================
    # Image PDF → OCR
    # ========================================================
    if kind == "画像PDF":
        st.subheader("🖼 OCR 実行")

        # ---------- OCR方式選択 ----------
        ocr_mode = st.radio(
            "OCR 実行方式",
            ["Python API（高速・進捗なし）", "CLI（ページ進捗あり）"],
            index=1,
        )

        progress = st.progress(0.0)
        status = st.empty()

        # CLI用 progress callback
        def progress_cb(msg: str, frac: float | None = None):
            if frac is not None:
                progress.progress(frac)

            status.markdown(
                f"""
**処理中**

- 📄 ファイル: `{uploaded.name}`
- 📊 {msg}
"""
            )

        dst = src.with_name(src.stem + "_ocr.pdf")

        if st.button("▶ OCR 実行"):
            with st.spinner("OCR 実行中…"):
                if ocr_mode.startswith("CLI"):
                    # ▼ CLI：ページ進捗あり
                    run_ocr(
                        src=src,
                        dst=dst,
                        lang="jpn+eng",
                        progress_cb=progress_cb,
                    )
                else:
                    # ▼ Python API：進捗なし（高速）
                    run_ocr(
                        src=src,
                        dst=dst,
                        lang="jpn+eng",
                        progress_cb=None,
                    )

            st.success("✅ OCR 完了")

            st.download_button(
                "📥 OCR 済み PDF をダウンロード",
                data=dst.read_bytes(),
                file_name=dst.name,
                mime="application/pdf",
            )

    # ========================================================
    # Text PDF → Extract text
    # ========================================================
    elif kind == "テキストPDF":
        st.subheader("🔤 テキスト抽出")

        text_info = analyze_pdf_texts(
            str(src),
            src.stat().st_mtime_ns,
            mode="all",
        )

        blocks: list[str] = []
        for row in text_info.get("pages", []):
            blocks.append(f"===== p.{row['page']} =====\n{row['text']}")

        full_text = "\n\n".join(blocks)

        st.text_area(
            "抽出テキスト（先頭部分）",
            full_text[:5000],
            height=300,
        )

        st.download_button(
            "📥 テキストをダウンロード (.txt)",
            data=full_text.encode("utf-8"),
            file_name=src.stem + ".txt",
            mime="text/plain",
        )

    else:
        st.warning("この PDF は画像PDF／テキストPDFのどちらとも判定できませんでした。")
