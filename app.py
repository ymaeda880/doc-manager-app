# app.py
# ------------------------------------------------------------
# 📄 PDF Viewer (Streamlit, single-purpose)
# - 起動時に pages/10_PDFビューア.py へ自動遷移（対応環境）
# - 非対応環境ではリンクボタンで遷移
# ------------------------------------------------------------
from __future__ import annotations

import os
import socket
from pathlib import Path

import streamlit as st

# 追加：secrets.toml を解決した標準パス
from lib.app_paths import PATHS, APP_ROOT


# ===============================
# 基本設定（ページ）
# ===============================
st.set_page_config(page_title="PDF Viewer", page_icon="📄", layout="wide")
st.title("📄 PDF Viewer")


# ===============================
# ネットワーク情報ユーティリティ
# ===============================
def get_lan_ip() -> str:
    """
    現在アクティブなNICの IPv4（例: 192.168.x.x / 10.x.x.x）を取得。
    取得不能時は '取得できませんでした' を返す。
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # 実通信は発生しないが、使用NICを判定するためのダミー接続
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "取得できませんでした"
    finally:
        try:
            s.close()
        except Exception:
            pass
    return ip


def get_localhost_ip() -> str:
    """localhost（ループバック）のIP。通常は 127.0.0.1。"""
    try:
        return socket.gethostbyname("localhost")
    except Exception:
        return "127.0.0.1"


# ===============================
# ポート／ベースパスの決定
# ===============================
# .streamlit/config.toml と合わせる想定（デフォルト: 8503 / '/doc-manager'）
DEFAULT_PORT = 8503
DEFAULT_BASE = "/doc-manager"

# 環境変数や secrets で上書き可能にしておく（任意）
port = int(
    os.getenv("STREAMLIT_PORT")
    or os.getenv("PORT")
    or (st.secrets.get("server", {}).get("port", DEFAULT_PORT) if hasattr(st, "secrets") else DEFAULT_PORT)
)

base = (
    os.getenv("BASE_URL_PATH")
    or (st.secrets.get("server", {}).get("baseUrlPath", DEFAULT_BASE) if hasattr(st, "secrets") else DEFAULT_BASE)
    or DEFAULT_BASE
)
base = base.strip()
if not base.startswith("/"):
    base = "/" + base
if not base.endswith("/"):
    base = base + "/"

# ===============================
# 🖥️ ローカルIP/URL 表示
# ===============================
lan_ip = get_lan_ip()
localhost_ip = get_localhost_ip()

localhost_url = f"http://{localhost_ip}:{port}{base}"
lan_url = f"http://{lan_ip}:{port}{base}" if lan_ip != "取得できませんでした" else "取得できませんでした"

st.markdown("### 🖥️ アクセス用URL")
col1, col2 = st.columns(2)
with col1:
    st.markdown(f"- **このMac専用（localhost）**: `{localhost_url}`")
with col2:
    st.markdown(f"- **LAN内の他端末から**: `{lan_url}`")

st.caption(
    "※ LAN URL が '取得できませんでした' の場合は、Wi-Fi/有線が有効か確認してください。"
)

# ===============================
# 📂 現在のパス設定
# ===============================
st.subheader("📂 現在のパス設定")
st.text(f"Location (env.location): {PATHS.env}")
st.text(f"APP_ROOT        : {APP_ROOT}（アプリフォルダーへのパス）")
# st.text(f"PDF Root        : {PATHS.pdf_root}")
# st.text(f"Converted Root  : {PATHS.converted_root}")
# st.text(f"Text Root       : {PATHS.text_root}")
st.text(f"Library Root    : {PATHS.library_root}")

st.text(f"original_docs_root    : {PATHS.original_docs_root}(原本データへのパス)")
st.text(f"organized_docs_root    : {PATHS.organized_docs_root}（整理したpdfファイルへのパス）")

# ===============================
# ナビゲーション
# ===============================
with st.sidebar:
    st.header("ナビゲーション")
    st.page_link("pages/50_PDFビューア.py", label="📄 PDF ビューアを開く")
    st.page_link("pages/40_OCR処理.py", label="📄 OCR処理を開く")

# ------------------------------------------------------------
# 起動直後に自動で PDF ビューアページへ遷移（オプション）
# ------------------------------------------------------------
# try:
#     st.switch_page("pages/10_PDFビューア.py")
# except Exception:
#     st.info("自動遷移できない環境です。左の『📄 PDF ビューアを開く』から移動してください。")
