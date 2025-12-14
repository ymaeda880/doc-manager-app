# pages/84_pdfテキスト抽出.py
# ------------------------------------------------------------
# 📄 PDF テキスト抽出（判定結果つき）
#
# 仕様
# ----
# - PDF をドラッグ＆ドロップ
# - 現状の判定基準（quick_pdf_info）で「画像PDF / テキストPDF」を判定して表示
# - 各ページからテキストを抽出して表示
# - 抽出結果を .txt でダウンロード可能
#
# 依存
# ----
# - lib.pdf.info.quick_pdf_info
# - lib.pdf.text.analyze_pdf_texts
# ------------------------------------------------------------

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import streamlit as st

from lib.pdf.info import quick_pdf_info
from lib.pdf.text import analyze_pdf_texts

st.set_page_config(
    page_title="PDF テキスト抽出（判定つき）",
    page_icon="📄",
    layout="centered",
)

st.title("📄 PDF テキスト抽出（判定つき）")

st.markdown(
    """
PDF をアップロードすると、

1) `quick_pdf_info` の **現状の判定基準**で **画像PDF / テキストPDF** を推定して表示  
2) 全ページからテキストを抽出して表示（OCRは実行しません）  
3) 抽出結果を `.txt` としてダウンロードできます
"""
)

uploaded = st.file_uploader("PDF ファイルをドロップ", type=["pdf"])
if uploaded is None:
    st.stop()

# TemporaryDirectory 配下のファイルは rerun で消えるので、
# ダウンロード用データは session_state に保持するのが安全
pdf_bytes = uploaded.getvalue()

with TemporaryDirectory() as tmpdir:
    src = Path(tmpdir) / uploaded.name
    src.write_bytes(pdf_bytes)

    # ------------------------------------------------------------
    # 1) 判定（現状の基準をそのまま利用）
    # ------------------------------------------------------------
    info = quick_pdf_info(str(src), src.stat().st_mtime_ns)  # sample_pages=6, threshold=0.3, min_chars=20
    kind = info.get("kind", "不明")
    pages = int(info.get("pages") or 0)
    text_ratio = float(info.get("text_ratio") or 0.0)
    checked = int(info.get("checked") or 0)

    st.subheader("📌 判定結果（quick_pdf_info）")
    st.write(f"- 種別: **{kind}**")
    st.write(f"- ページ数: **{pages}**")
    st.write(f"- チェックしたページ数: **{checked}**（先頭 N ページ）")
    st.write(f"- text_ratio: **{text_ratio:.2f}**（テキスト有りページ / チェックページ）")
    st.caption("※ 判定基準は現状の quick_pdf_info（先頭6ページ・20文字以上をテキスト有り、比率0.3以上でテキストPDF）を使用。")

    # ------------------------------------------------------------
    # 2) 各ページのテキスト抽出（OCRはしない）
    # ------------------------------------------------------------
    st.subheader("🔤 ページ別テキスト抽出（OCRなし）")

    with st.spinner("テキスト抽出中…"):
        text_info = analyze_pdf_texts(
            str(src),
            src.stat().st_mtime_ns,
            mode="all",
        )

    pages_list = text_info.get("pages", [])

    # 表示用（ページごとの文字数）
    # - analyze_pdf_texts の戻りが {"page": int, "text": str} を想定
    rows = []
    blocks = []
    for row in pages_list:
        pno = int(row.get("page", 0))
        txt = (row.get("text") or "")
        tlen = len(txt.strip())

        rows.append({"page": pno, "text_len": tlen})
        blocks.append(f"===== p.{pno} =====\n{txt}")

    full_text = "\n\n".join(blocks)

    # 先頭プレビュー
    st.text_area(
        "抽出テキスト（先頭部分）",
        full_text[:8000],
        height=320,
    )

    # ページ別サマリ表
    if rows:
        st.caption("ページ別サマリ（抽出文字数）")
        st.dataframe(rows, width='stretch', hide_index=True)

    # ------------------------------------------------------------
    # 3) ダウンロード
    # ------------------------------------------------------------
    # rerun 対策：bytesを session_state に保存
    key_txt = f"pdf_text_bytes::{uploaded.name}"
    st.session_state[key_txt] = full_text.encode("utf-8")

    st.download_button(
        "📥 抽出テキストをダウンロード (.txt)",
        data=st.session_state[key_txt],
        file_name=Path(uploaded.name).with_suffix(".txt").name,
        mime="text/plain",
    )

    # 参考：判定情報も見たい場合（任意）
    with st.expander("判定情報（raw）", expanded=False):
        st.json(info)
