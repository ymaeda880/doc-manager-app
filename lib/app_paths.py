# app_paths.py
# =================================
# docs_manager_app 用 Path マネージャ
# - 設定: config/settings.toml
# - 環境: Develop / Home / Prec / Server
# ---------------------------------

from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, Optional, List
import os

# --- optional: Streamlit は不要（存在すれば利用可） ---
try:
    import streamlit as st  # noqa: F401
except Exception:
    st = None

# --- toml loader (3.11+: tomllib / fallback: tomli) ---
try:  # Python 3.11+
    import tomllib as _toml
except Exception:  # 3.10 以下など
    try:
        import tomli as _toml  # type: ignore
    except Exception:
        _toml = None  # toml 読み込み不可

APP_ROOT = Path(__file__).resolve().parents[1]

# ================= ユーティリティ =================

def _load_toml(path: Path) -> Dict[str, Any]:
    """TOML を辞書で返す。存在しない/読めない場合は空 dict。"""
    if not path.exists() or not path.is_file() or _toml is None:
        return {}
    try:
        with path.open("rb") as f:
            return dict(_toml.load(f))
    except Exception:
        return {}

def _get_settings_file() -> Path:
    """
    設定ファイルの探索順:
      1) APP_SETTINGS_FILE（相対なら APP_ROOT 基準）
      2) APP_ROOT/config/settings.toml
      3) APP_ROOT/.streamlit/settings.toml
      4) APP_ROOT/settings.toml
    """
    env = os.getenv("APP_SETTINGS_FILE")
    if env:
        p = Path(env)
        if not p.is_absolute():
            p = (APP_ROOT / p)
        return p.resolve()

    candidates = [
        APP_ROOT / "config" / "settings.toml",
        APP_ROOT / ".streamlit" / "settings.toml",
        APP_ROOT / "settings.toml",
    ]
    for c in candidates:
        c = c.resolve()
        if c.exists() and c.is_file():
            return c

    return (APP_ROOT / "config" / "settings.toml").resolve()

def _sanitize_spec(s: str) -> str:
    """
    TOML のパス表記を前処理。
    - '\\ ' を ' ' に置換（例: '/Volumes/Extreme\\ Pro' → '/Volumes/Extreme Pro'）
    - 前後空白を除去
    """
    return s.replace("\\ ", " ").strip()

def _resolve(spec: Optional[str], *, mounts: Dict[str, Any], default: Path) -> Path:
    """
    パス指定子を実パスに解決。
      - project:SUBPATH           → APP_ROOT/SUBPATH
      - mount:Name[/subpath]      → mounts[Name]/subpath
      - mount:Name                → mounts[Name]
      - 絶対/ホーム(~)            → そのまま
      - 相対                      → APP_ROOT 基準
    """
    if not spec:
        return default
    s = _sanitize_spec(str(spec))
    if not s:
        return default

    if s.startswith("project:"):
        rel = s.split(":", 1)[1].strip()
        return (APP_ROOT / rel).resolve()

    if s.startswith("mount:"):
        rest = s.split(":", 1)[1].strip()
        if not rest:
            return default
        if "/" in rest:
            mname, sub = rest.split("/", 1)
            base = mounts.get(mname)
            if base:
                return (Path(str(base)).expanduser() / sub).resolve()
        else:
            base = mounts.get(rest)
            if base:
                return Path(str(base)).expanduser().resolve()
        return default

    p = Path(s).expanduser()
    if not p.is_absolute():
        p = (APP_ROOT / p)
    return p.resolve()

# ================= 本体クラス =================

class AppPaths:
    """
    settings.toml を読み込み、アプリ内の標準パスを提供する。

    主要属性:
      - env: 現在の環境名（Develop / Home / Prec / Server）
      - app_root, data_dir
      - pdf_root, converted_root, text_root, library_root, docs_root
      - original_docs_root, organized_docs_root
      - available_presets (任意)
    """

    def __init__(self, settings_path: Optional[Path] = None) -> None:
        # 設定ロード
        self.settings_path: Path = settings_path or _get_settings_file()
        self.settings: Dict[str, Any] = _load_toml(self.settings_path)

        env_sec   = dict(self.settings.get("env", {}))
        mounts    = dict(self.settings.get("mounts", {}))
        locs_sec  = dict(self.settings.get("locations", {}))
        app_sec   = dict(self.settings.get("app", {}))

        # 現在のロケーション（デフォルト "Home"）
        self.env: str = str(env_sec.get("location") or "Home")

        # プリセット一覧（省略可）
        aps = app_sec.get("available_presets")
        if isinstance(aps, list):
            self.available_presets: List[str] = [str(x) for x in aps]
        else:
            self.available_presets = ["Develop", "Home", "Prec", "Server"]

        # ベース
        self.app_root: Path = APP_ROOT
        self.data_dir: Path = self.app_root / "data"

        # 既定パス（locations 未定義時のフォールバック）
        default_pdf         = self.data_dir / "pdf"
        default_conv        = self.data_dir / "converted_pdf"
        default_text        = self.data_dir / "text"
        default_library     = self.data_dir / "library"
        default_docs        = self.data_dir / "docs"
        default_original    = self.data_dir / "original_docs"
        default_organized   = self.data_dir / "organized_docs"

        # 現在ロケーションの dict
        cur = locs_sec.get(self.env, {}) if isinstance(locs_sec, dict) else {}

        # 各ルート解決
        self.pdf_root         = _resolve(cur.get("pdf_root"),         mounts=mounts, default=default_pdf)
        self.converted_root   = _resolve(cur.get("converted_root"),   mounts=mounts, default=default_conv)
        self.text_root        = _resolve(cur.get("text_root"),        mounts=mounts, default=default_text)
        self.library_root     = _resolve(cur.get("library_root"),     mounts=mounts, default=default_library)

        docs_spec = cur.get("docs_root") or self.settings.get("docs_root")
        self.docs_root        = _resolve(docs_spec,                   mounts=mounts, default=default_docs)

        orig_spec = cur.get("original_docs_root") or self.settings.get("original_docs_root")
        self.original_docs_root  = _resolve(orig_spec,                mounts=mounts, default=default_original)

        orgz_spec = cur.get("organized_docs_root") or self.settings.get("organized_docs_root")
        self.organized_docs_root = _resolve(orgz_spec,                mounts=mounts, default=default_organized)

        # ディレクトリ自動作成（読み取り専用でも失敗時は黙って無視）
        for p in (
            self.pdf_root,
            self.converted_root,
            self.text_root,
            self.library_root,
            self.docs_root,
            self.original_docs_root,
            self.organized_docs_root,
        ):
            try:
                p.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

    # ---------- 便利メソッド ----------
    def to_dict(self) -> Dict[str, str]:
        """主要パスを文字列化して dict で返す（デバッグ/UI表示用）。"""
        return {
            "env": self.env,
            "settings_path": str(self.settings_path),
            "app_root": str(self.app_root),
            "data_dir": str(self.data_dir),
            "pdf_root": str(self.pdf_root),
            "converted_root": str(self.converted_root),
            "text_root": str(self.text_root),
            "library_root": str(self.library_root),
            "docs_root": str(self.docs_root),
            "original_docs_root": str(self.original_docs_root),
            "organized_docs_root": str(self.organized_docs_root),
        }

    def __repr__(self) -> str:
        d = self.to_dict()
        rows = [f"  {k:20s}= {v}" for k, v in d.items()]
        return "AppPaths(\n" + "\n".join(rows) + "\n)"

# 既定インスタンス
PATHS = AppPaths()

if __name__ == "__main__":
    # 簡易動作確認
    ap = AppPaths()
    print(ap)
