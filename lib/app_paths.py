"""
app_paths.py
=================================
アプリ内で利用する標準パスを一元管理するユーティリティ（path manager）。

- 設定ファイル: `config/settings.toml`
- 参照セクション:
    - [env]
    - [mounts]
    - [locations.<env>]
    - （任意）[app]
- 特殊指定子:
    - `project:SUBPATH` …… APP_ROOT 配下への相対
    - `mount:NAME/SUBPATH` …… `[mounts].NAME` を起点に解決
    - `mount:NAME` …… `[mounts].NAME` そのもの
    - 相対パス …… APP_ROOT 基準に解決
    - 絶対パス / `~`（ホーム） …… そのまま採用

このモジュールが提供する主な属性（paths）
------------------------------------------
AppPaths / PATHS から参照できる標準パス:

- `app_root`（Path）: アプリのルート（APP_ROOT）
- `data_dir`（Path）: APP_ROOT/data
- `pdf_root`（Path）: PDF格納ルート
- `converted_root`（Path）: OCR/変換後PDF格納
- `text_root`（Path）: テキスト抽出結果格納
- `library_root`（Path）: メタ/インデックス/カタログ等
- `docs_root`（Path）: ドキュメント原本格納ルート
- `original_docs_root`（Path）: 新設。真正原本のルート
- `available_presets`（List[str]）: [app].available_presets の値
"""

from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, Optional, List
import os

# --- optional: Streamlit is not required ---
try:
    import streamlit as st  # noqa: F401
except Exception:
    st = None

# --- toml loader (3.11+: tomllib / fallback: tomli) ---
try:  # Python 3.11+
    import tomllib as _toml
except Exception:  # 3.10以下など
    try:
        import tomli as _toml  # type: ignore
    except Exception:
        _toml = None  # toml 読み込み不可

APP_ROOT = Path(__file__).resolve().parents[1]

# ============= ユーティリティ =============

def _load_toml(path: Path) -> Dict[str, Any]:
    """
    TOML を辞書に読み込む。

    Parameters
    ----------
    path : Path
        TOMLファイルへのパス

    Returns
    -------
    dict
        読み込んだ内容。存在しない/読めない場合は空dict。
    """
    if not path.exists() or not path.is_file() or _toml is None:
        return {}
    try:
        with path.open("rb") as f:
            return dict(_toml.load(f))
    except Exception:
        return {}

def _get_settings_file() -> Path:
    """
    設定ファイルの探索順序で最初に見つかったものを返す。

    優先順:
      1) 環境変数 APP_SETTINGS_FILE（相対なら APP_ROOT 基準）
      2) APP_ROOT/config/settings.toml
      3) APP_ROOT/.streamlit/settings.toml
      4) APP_ROOT/settings.toml

    Returns
    -------
    Path
        見つかった設定ファイルのパス。存在しなくても既定パスを返す。
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
    TOML 内のパス表記を前処理する。

    - '\\ ' をスペース ' ' に置換（例: '/Volumes/Extreme\\ Pro' → '/Volumes/Extreme Pro'）
    - 前後の空白を除去

    Parameters
    ----------
    s : str
        設定ファイルから取得した文字列

    Returns
    -------
    str
        補正済み文字列
    """
    return s.replace("\\ ", " ").strip()

def _resolve(spec: Optional[str], *, mounts: Dict[str, Any], default: Path) -> Path:
    """
    パス指定子を実際のパスに変換する。

    サポートされる形式:
      - project:SUBPATH  -> APP_ROOT / SUBPATH
      - mount:Name[/subpath] -> mounts[Name] / subpath
      - mount:Name -> mounts[Name]
      - 絶対パス or ~付き -> そのまま解決
      - 相対パス -> APP_ROOT 基準

    Parameters
    ----------
    spec : str or None
        設定値
    mounts : dict
        [mounts] セクション
    default : Path
        デフォルトのパス

    Returns
    -------
    Path
        解決済みのPath
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

# ============= 本体クラス =============

class AppPaths:
    """
    settings.toml を読み込み、アプリ内で利用する標準パスを提供するクラス。

    読み込むセクション:
      - [env] : 現在の location を決定
      - [mounts] : 論理マウント名と実パス
      - [locations.<env>] : 環境ごとのパス指定
      - [app] : 補助的なアプリ設定（例: available_presets）

    優先順位:
      1. [locations.<env>] にあるキー
      2. トップレベルのキー（docs_root, original_docs_root）
      3. デフォルト値（APP_ROOT/data/...）
    """

    def __init__(self, settings_path: Optional[Path] = None) -> None:
        # 設定ファイルロード
        self.settings_path: Path = settings_path or _get_settings_file()
        self.settings: Dict[str, Any] = _load_toml(self.settings_path)

        # セクション取得
        env_sec   = dict(self.settings.get("env", {}))
        mounts    = dict(self.settings.get("mounts", {}))
        locs_sec  = dict(self.settings.get("locations", {}))
        app_sec   = dict(self.settings.get("app", {}))

        # 現在のロケーション（デフォルト "Home"）
        self.env: str = str(env_sec.get("location") or "Home")

        # プリセット一覧
        aps = app_sec.get("available_presets")
        self.available_presets: List[str] = list(aps) if isinstance(aps, list) else []

        # 基本パス
        self.app_root: Path = APP_ROOT
        self.data_dir: Path = self.app_root / "data"

        # デフォルト値
        default_pdf         = self.data_dir / "pdf"
        default_conv        = self.data_dir / "converted_pdf"
        default_text        = self.data_dir / "text"
        default_library     = self.data_dir / "library"
        default_docs        = self.data_dir / "docs"
        default_original    = self.data_dir / "original_docs"
        default_organized = self.data_dir / "organized_docs"

        # 現在ロケーションの定義
        cur = locs_sec.get(self.env, {}) if isinstance(locs_sec, dict) else {}

        # 各種ルート解決
        self.pdf_root       = _resolve(cur.get("pdf_root"),       mounts=mounts, default=default_pdf)
        self.converted_root = _resolve(cur.get("converted_root"), mounts=mounts, default=default_conv)
        self.text_root      = _resolve(cur.get("text_root"),      mounts=mounts, default=default_text)
        self.library_root   = _resolve(cur.get("library_root"),   mounts=mounts, default=default_library)

        docs_spec = cur.get("docs_root") or self.settings.get("docs_root")
        self.docs_root = _resolve(docs_spec, mounts=mounts, default=default_docs)

        orig_spec = cur.get("original_docs_root") or self.settings.get("original_docs_root")
        self.original_docs_root = _resolve(orig_spec, mounts=mounts, default=default_original)

        org_spec = cur.get("organized_docs_root") or self.settings.get("organized_docs_root")
        self.organized_docs_root = _resolve(org_spec, mounts=mounts, default=default_organized)

        # ディレクトリ自動作成（読み取り専用で失敗しても無視）
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

    def __repr__(self) -> str:
        """インスタンス内容を文字列化（デバッグ用）。"""
        return (
            "AppPaths(\n"
            f"  env                 = {self.env}\n"
            f"  settings_path       = {self.settings_path}\n"
            f"  available_presets   = {self.available_presets}\n"
            f"  app_root            = {self.app_root}\n"
            f"  data_dir            = {self.data_dir}\n"
            f"  pdf_root            = {self.pdf_root}\n"
            f"  converted_root      = {self.converted_root}\n"
            f"  text_root           = {self.text_root}\n"
            f"  library_root        = {self.library_root}\n"
            f"  docs_root           = {self.docs_root}\n"
            f"  original_docs_root  = {self.original_docs_root}\n"
            f"  organized_docs_root = {self.organized_docs_root}\n"
            ")"
        )

# 既定インスタンス
PATHS = AppPaths()
