# app.py
# ------------------------------------------------------------
# 📄 PDF Viewer (Streamlit, single-purpose)
# - 起動時に pages/10_PDFビューア.py へ自動遷移（対応環境）
# - 非対応環境ではリンクボタンで遷移
# ------------------------------------------------------------
from __future__ import annotations
import streamlit as st
from pathlib import Path

# 追加：secrets.toml を解決した標準パス
from lib.app_paths import PATHS, APP_ROOT

st.set_page_config(page_title="PDF Viewer", page_icon="📄", layout="wide")
st.title("📄 PDF Viewer")

# パスの確認表示（secrets.toml 反映済み）
st.subheader("📂 現在のパス設定")
st.text(f"Location (env.location): {PATHS.env}")   # ← 追加
st.text(f"APP_ROOT        : {APP_ROOT}")
st.text(f"PDF Root        : {PATHS.pdf_root}")
st.text(f"Converted Root  : {PATHS.converted_root}")
st.text(f"Text Root       : {PATHS.text_root}")
st.text(f"Library Root    : {PATHS.library_root}")  # ← 追加

# ここでは最小限のホーム画面だけ用意し、対応環境なら即ページ遷移します
with st.sidebar:
    st.header("ナビゲーション")
    # フォールバック用のリンク（自動遷移できない環境でも使える）
    st.page_link("pages/80_（旧）PDFビューア.py", label="📄 PDF ビューアを開く")
    st.page_link("pages/82_（旧）PDFテキストビューア.py", label="📄 PDF テキストビューアを開く")

# 起動直後に自動で PDF ビューアページへ遷移（対応していないStreamlit版もあるため try 保護）
# try:
#     # ファイル名に合わせて 10_ の方へ
#     st.switch_page("pages/10_PDFビューア.py")
# except Exception:
#     st.info("自動遷移できない環境です。左の『📄 PDF ビューアを開く』から移動してください。")
