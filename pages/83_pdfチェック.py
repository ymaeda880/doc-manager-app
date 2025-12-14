# pages/83_pdfチェック.py
# ------------------------------------------------------------
# 🔎 PDF チェック（画像PDF？テキストPDF？／ページ別判定）
#
# 仕様
# ----
# - PDF をドラッグ＆ドロップ
# - まず「PDF全体」が画像寄りかテキスト寄りかを判定して表示
# - ページ数など基本情報を表示
# - その後、ページごとに「画像/テキスト」を判定して一覧表示
# - OCR は実行しない
#
# 判定方針（現実的）
# ----------------
# - PyMuPDF の page.get_text("text") を使い、抽出文字数で判定
# - 1ページの抽出文字数 >= min_chars_per_page → "text"
# - それ以外 → "image"
# - PDF全体判定は、全ページの比率で "text寄り / image寄り / mixed" を出す
# ------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional, List, Dict, Any

import streamlit as st
import pandas as pd

# PyMuPDF
import fitz  # pip install pymupdf


# ============================================================
# 設定
# ============================================================
DEFAULT_MIN_CHARS_PER_PAGE = 30          # ページを text とみなす最小文字数
DEFAULT_TEXT_RATIO_TEXT_PDF = 0.80       # text判定ページ比率 >= 80% なら「テキストPDF寄り」
DEFAULT_TEXT_RATIO_IMAGE_PDF = 0.20      # text判定ページ比率 <= 20% なら「画像PDF寄り」


# ============================================================
# データ構造
# ============================================================
@dataclass
class PdfBasicInfo:
    page_count: int
    title: str
    author: str
    subject: str
    creator: str
    producer: str


# ============================================================
# ユーティリティ
# ============================================================
def _safe_str(x: Any) -> str:
    try:
        return str(x) if x is not None else ""
    except Exception:
        return ""


def read_basic_info(doc: fitz.Document) -> PdfBasicInfo:
    meta = doc.metadata or {}
    return PdfBasicInfo(
        page_count=int(doc.page_count),
        title=_safe_str(meta.get("title")),
        author=_safe_str(meta.get("author")),
        subject=_safe_str(meta.get("subject")),
        creator=_safe_str(meta.get("creator")),
        producer=_safe_str(meta.get("producer")),
    )


def classify_page_as_text_or_image(page: fitz.Page, *, min_chars: int) -> Dict[str, Any]:
    """
    ページを text / image と判定して、根拠情報も返す。
    """
    # PyMuPDF は例外を投げることがあるので守る
    try:
        text = page.get_text("text") or ""
    except Exception:
        text = ""

    text_len = len(text.strip())

    label = "text" if text_len >= min_chars else "image"
    return {
        "text_len": text_len,
        "label": label,
    }


def classify_pdf_overall(page_labels: List[str], *, ratio_text: float, ratio_image: float) -> str:
    """
    全体を text寄り / image寄り / mixed で判定
    """
    if not page_labels:
        return "unknown"

    n = len(page_labels)
    n_text = sum(1 for x in page_labels if x == "text")
    r = n_text / n if n > 0 else 0.0

    if r >= ratio_text:
        return "text寄り（テキストPDFの可能性が高い）"
    if r <= ratio_image:
        return "image寄り（画像PDFの可能性が高い）"
    return "mixed（混在の可能性）"


# ============================================================
# UI
# ============================================================
st.set_page_config(page_title="PDF チェック（画像/テキスト判定）", page_icon="🔎", layout="centered")
st.title("🔎 PDF チェック（画像PDF？テキストPDF？／ページ別判定）")

st.write(
    "PDF をアップロードすると、まず **PDF全体**が画像寄りかテキスト寄りかを推定し、"
    "続いて **ページごと**に text/image を判定して一覧表示します。"
)
st.caption("※ OCR は実行しません。判定は「抽出できるテキスト量（文字数）」に基づきます。")

with st.sidebar:
    st.header("判定設定")
    min_chars = st.number_input(
        "ページを text とみなす最小文字数",
        min_value=0,
        max_value=2000,
        value=int(DEFAULT_MIN_CHARS_PER_PAGE),
        step=5,
        help="この文字数以上のテキストが抽出できるページは text 扱いになります。",
    )
    ratio_text = st.slider(
        "PDF全体を「text寄り」と判定する閾値（textページ比率）",
        min_value=0.0,
        max_value=1.0,
        value=float(DEFAULT_TEXT_RATIO_TEXT_PDF),
        step=0.05,
    )
    ratio_image = st.slider(
        "PDF全体を「image寄り」と判定する閾値（textページ比率）",
        min_value=0.0,
        max_value=1.0,
        value=float(DEFAULT_TEXT_RATIO_IMAGE_PDF),
        step=0.05,
    )

uploaded = st.file_uploader("PDF をドラッグ＆ドロップ", type=["pdf"])

if not uploaded:
    st.info("PDF をアップロードしてください。")
    st.stop()

# 一時ファイルへ保存（PyMuPDF は bytes でも開けるが、パスの方が扱いやすいことが多い）
with NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
    tmp.write(uploaded.getbuffer())
    tmp_path = Path(tmp.name)

# PDF オープン
try:
    doc = fitz.open(tmp_path)
except Exception as e:
    st.error(f"PDF を開けませんでした: {e}")
    st.stop()

# 基本情報
info = read_basic_info(doc)

st.subheader("📄 基本情報")
c1, c2, c3 = st.columns(3)
c1.metric("ページ数", f"{info.page_count:,}")
c2.metric("ファイル名", uploaded.name)
c3.metric("推定", "（判定中…）")

with st.expander("メタデータ（可能な範囲）", expanded=False):
    md = {
        "title": info.title,
        "author": info.author,
        "subject": info.subject,
        "creator": info.creator,
        "producer": info.producer,
    }
    st.json(md)

# ページ別判定
st.subheader("🧪 ページ別判定（OCRなし）")

rows: List[Dict[str, Any]] = []
for i in range(info.page_count):
    page = doc.load_page(i)
    r = classify_page_as_text_or_image(page, min_chars=int(min_chars))
    rows.append(
        {
            "page": i + 1,
            "label": r["label"],
            "text_len": r["text_len"],
        }
    )

df = pd.DataFrame(rows)
labels = df["label"].tolist()

overall = classify_pdf_overall(labels, ratio_text=float(ratio_text), ratio_image=float(ratio_image))

# 全体サマリ
n = len(df)
n_text = int((df["label"] == "text").sum())
n_image = int((df["label"] == "image").sum())
text_ratio = (n_text / n) if n > 0 else 0.0

st.success(
    f"✅ 全体判定: **{overall}**\n\n"
    f"- text 判定ページ: **{n_text}/{n}**（{text_ratio:.0%}）\n"
    f"- image 判定ページ: **{n_image}/{n}**（{1 - text_ratio:.0%}）"
)

# テーブル表示
st.dataframe(
    df,
    width='stretch',
    hide_index=True,
)

# 追加：フィルタ表示
with st.expander("フィルタ表示", expanded=False):
    mode = st.radio("表示", ["全ページ", "text のみ", "image のみ"], horizontal=True)
    if mode == "text のみ":
        st.dataframe(df[df["label"] == "text"], width='stretch', hide_index=True)
    elif mode == "image のみ":
        st.dataframe(df[df["label"] == "image"], width='stretch', hide_index=True)
    else:
        st.dataframe(df, width='stretch', hide_index=True)

# 片付け
try:
    doc.close()
except Exception:
    pass
try:
    tmp_path.unlink(missing_ok=True)  # py>=3.8
except Exception:
    pass
