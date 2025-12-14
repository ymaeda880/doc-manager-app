# pages/60_skip_json作成.py
# ============================================================
# 🚫 skip JSON（_side.json, ocr:"skipped"）作成 + PDF軽量情報表示
# - ドロップしたPDFを quick_pdf_info で解析（画像/テキスト, ページ数, サイズ）
# - organized/report/pdf を起点に同名PDFを探索（重複時は選択）
# - ① すべてのドロップファイルが同一フォルダに存在する場合は「一括作成」UIを表示
# - ② それ以外は従来どおり：単一ヒット→そのまま / 複数ヒット→ラジオで選択して作成
# - 既存 side.json がある場合はデフォルトでスキップ（上書きON時のみ更新）
# ============================================================

from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Tuple
import json
from datetime import datetime, timedelta, timezone

import streamlit as st

# 依存 lib
from lib.app_paths import PATHS
from lib.pdf.info import quick_pdf_info

# ========== ページ設定 ==========
st.set_page_config(page_title="60_skip_json作成", page_icon="🚫", layout="wide")
st.title("🚫 skip JSON（_side.json, ocr:'skipped'）作成")


with st.expander("ℹ️ このページの役割と処理フロー（skip sidecar作成）", expanded=False):
    st.markdown(r"""
## 目的（What）
**organized_docs_root/report/pdf** を起点に、指定した **PDFと同名の実体ファイル** を探し出し、  
**`<basename>_side.json`** を作成/更新して `ocr: "skipped"` を付与します。  
（図面や票など **OCR/ベクトル化の対象外** にしたいPDFを、**安全に・素早く** まとめて除外登録するためのツール）

---

## 主な機能（Features）
- **ドラッグ&ドロップ**した PDF 名で、`organized/report/pdf` 配下を探索（年→pnoの優先探索＋`rglob`）
- **同名ヒットが複数**ある場合は、候補を列挙して**ラジオ選択**
- すべてのドロップファイルが **同一フォルダに存在** と判断できれば、**一括作成** UI を提示
- 既存の sidecar がある場合は **既定ではスキップ**（サイドバーで **上書きON** にすると更新）
- 作成/更新した結果は **一覧（成功/スキップ理由）** を表示
- 参考情報として `quick_pdf_info` による **種別（画像/テキスト）・ページ数・サイズ** を表示

---

## 重要な用語（Naming）
- **sidecar（_side.json）**：`<basename>_side.json` という隣接JSON  
  ```json
  {"type":"image_pdf","created_at":"YYYY-MM-DDTHH:MM:SS+09:00","ocr":"skipped"}

 """)               

st.info("使用ルート：organized_docs_root")

st.caption(
    "PDFをドロップすると、organized/report/pdf を起点に**同名のPDF**を検索し、"
    "見つかったフォルダに `<basename>_side.json` を作成します。"
    "\n\n"
    "複数ファイルをドロップした場合、**すべて同じフォルダ内に存在する**と判定されれば、"
    "そのフォルダを選んで**一括で side.json を作成**できます。"
    "（個別のファイルごとにも確認・作成が可能です。）"
)


# ========== 基点ルート ==========
def default_pdf_root() -> Path:
    return (Path(str(PATHS.organized_docs_root)).expanduser().resolve() / "report" / "pdf").resolve()

with st.sidebar:
    st.header("基点ルート")
    pdf_root = Path(st.text_input("PDF ルート", value=str(default_pdf_root()))).expanduser().resolve()
    st.caption(f"実パス: `{pdf_root}`")

    overwrite = st.checkbox("既存 side.json を上書き/更新する", value=False)
    st.caption("OFF: 既存の side.json がある場合は警告を出してスキップ。ON: 上書きして更新。")

if not pdf_root.exists():
    st.error("PDFルートが存在しません。")
    st.stop()

# ========== 定数 ==========
SIDE_SUFFIX = "_side.json"
JST = timezone(timedelta(hours=9))

# ========== ユーティリティ ==========
def sidecar_path_for(pdf_path: Path) -> Path:
    return pdf_path.with_name(pdf_path.stem + SIDE_SUFFIX)

def write_sidecar_skipped(pdf_path: Path, *, overwrite: bool) -> Tuple[bool, str, Path]:
    """<basename>_side.json (ocr:'skipped') を作成/更新"""
    pdf_path = pdf_path.expanduser().resolve()
    sc = sidecar_path_for(pdf_path)
    payload = {
        "type": "image_pdf",
        "created_at": datetime.now(tz=JST).isoformat(),
        "ocr": "skipped",
    }

    try:
        if sc.exists():
            if not overwrite:
                st.warning(f"⚠️ 既に side.json が存在します（スキップ）: {sc}")
                return (False, f"既存 {sc.name} があるためスキップ", sc.resolve())
            # 上書き更新
            try:
                data = json.loads(sc.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            data.update(payload)
            sc.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return (True, f"{sc.name} を更新（ocr:'skipped'）", sc.resolve())
        else:
            # 新規作成
            sc.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return (True, f"{sc.name} を作成（ocr:'skipped'）", sc.resolve())
    except Exception as e:
        return (False, f"書き込み失敗: {e}", sc.resolve())

def smart_locate_by_filename(filename: str, root: Path, max_hits: int = 200) -> List[Path]:
    """/<root>/<year> と /<root>/<year>/<pno> を優先探索 → 見つからなければ rglob"""
    hits: List[Path] = []
    try:
        for year_dir in root.iterdir():
            if not year_dir.is_dir():
                continue
            cand = year_dir / filename
            if cand.exists():
                hits.append(cand)
            for sub in year_dir.iterdir():
                if sub.is_dir():
                    cand2 = sub / filename
                    if cand2.exists():
                        hits.append(cand2)
            if len(hits) >= max_hits:
                break
    except PermissionError:
        pass

    if not hits:
        for p in root.rglob(filename):
            if p.is_file():
                hits.append(p)
                if len(hits) >= max_hits:
                    break
    return hits

def fmt_size(bytes_: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_ < 1024:
            return f"{bytes_:.1f} {unit}"
        bytes_ /= 1024
    return f"{bytes_:.1f} TB"

def show_pdf_info_block(pdf_path: Path):
    """quick_pdf_infoでPDF概要を表示（種別・ページ数・サイズ）"""
    try:
        stat = pdf_path.stat()
        info = quick_pdf_info(str(pdf_path), stat.st_mtime_ns)
        size = fmt_size(stat.st_size)
        kind = info.get("kind", "-")
        pages = info.get("pages", 0)
        ratio = info.get("text_ratio", 0.0)
        checked = info.get("checked", 0)
        st.markdown(
            f"📄 **{pdf_path.name}** — {kind}　"
            f"({pages}ページ中 {checked}ページ確認, text_ratio={ratio:.2f})　"
            f"💾 {size}"
        )
    except Exception as e:
        st.warning(f"⚠️ PDF情報取得失敗: {e}")

def show_result_box(title: str, items: List[Dict[str, str]]) -> None:
    st.success(title)
    for r in items:
        st.markdown(f"**PDF**: `{r['pdf']}`")
        st.markdown(f"**sidecar**: `{r['sidecar']}`")
        st.text(f"→ {r['result']}")
        st.markdown("---")
    st.code("\n".join(f"{r['pdf']} -> {r['sidecar']}  // {r['result']}" for r in items), language="text")

# === 新規: 複数ファイルを同一フォルダに一括作成するための候補探索 ===
def build_hits_map(filenames: List[str], root: Path) -> Dict[str, List[Path]]:
    """各ファイル名 → 候補パス一覧"""
    mp: Dict[str, List[Path]] = {}
    for fn in filenames:
        mp[fn] = smart_locate_by_filename(fn, root)
    return mp

def find_common_parent_dirs(hits_map: Dict[str, List[Path]]) -> List[Path]:
    """全ファイルが同一ディレクトリに存在する候補（親ディレクトリ）のリストを返す"""
    parent_sets: List[set[Path]] = []
    for fn, paths in hits_map.items():
        parents = {p.parent.resolve() for p in paths}
        parent_sets.append(parents)
    if not parent_sets:
        return []
    common = set.intersection(*parent_sets) if len(parent_sets) > 1 else parent_sets[0]
    # 同一階層の候補をパスソート
    return sorted(common)

# ========== 入力 ==========
st.subheader("① PDF をドロップ")

# 🔸 追加：アップローダ用の key カウンタ
if "skip_pdf_uploader_key" not in st.session_state:
    st.session_state["skip_pdf_uploader_key"] = 0

uploader_key = f"skip_pdf_uploads_{st.session_state['skip_pdf_uploader_key']}"

uploads = st.file_uploader(
    "PDFをドラッグ＆ドロップ（複数可）",
    type=["pdf"],
    accept_multiple_files=True,
    key=uploader_key,  # ← 固定値ではなく動的 key
)


st.markdown("<hr>", unsafe_allow_html=True)
st.subheader("②（任意）対象PDFの絶対パスを直接指定")
manual_abs = st.text_input("PDFの絶対パスを直接指定", value="")
use_manual = st.checkbox("上の絶対パスを使う（ドロップより優先）", value=False)

# ========== 実行（単発ボタン：単一ヒットや絶対パスを一括処理） ==========
do_run = st.button("💾 side.json（ocr:'skipped'）を作成/更新", type="primary", use_container_width=True)

results: List[Dict[str, str]] = []
errors: List[str] = []

# ========== 絶対パスで処理 ==========
if do_run and use_manual and manual_abs.strip():
    p = Path(manual_abs.strip()).expanduser().resolve()
    if not p.exists():
        st.error(f"指定されたPDFが見つかりません: {p}")
    else:
        st.markdown("### ✅ 直接指定")
        show_pdf_info_block(p)
        changed, msg, sc_abs = write_sidecar_skipped(p, overwrite=overwrite)
        results.append({"pdf": str(p), "sidecar": str(sc_abs), "result": msg})

# ========== ドロップ（同一フォルダ一括オプション → その後に従来の個別処理） ==========
if uploads:
    filenames = [Path(uf.name).name for uf in uploads]
    # 候補パスを前もって収集
    hits_map = build_hits_map(filenames, pdf_root)

    # ---- 一括候補の探索（全ファイルが同じ親フォルダに揃うか？）----
    common_parents = find_common_parent_dirs(hits_map)

    if len(filenames) >= 2 and common_parents:
        with st.expander("🧩 一括：全ファイルが同一フォルダに存在します（候補あり）", expanded=True):
            parent_opts = [str(d) for d in common_parents]
            parent_key = "batch_parent_choice"
            if parent_key not in st.session_state:
                st.session_state[parent_key] = parent_opts[0]

            sel_parent_str = st.radio("ターゲットフォルダを選択", options=parent_opts, key=parent_key)
            sel_parent = Path(sel_parent_str).resolve()

            # プレビュー（各ファイル）
            st.markdown("**プレビュー（quick scan）**")
            for fn in filenames:
                p = (sel_parent / fn).resolve()
                if not p.exists():
                    st.error(f"見つからないファイルがあります: {p}")
                else:
                    show_pdf_info_block(p)

            if st.button("→ このフォルダに **全ファイル分** の side.json を一括作成/更新", type="secondary"):
                batch_res: List[Dict[str, str]] = []
                for fn in filenames:
                    p = (sel_parent / fn).resolve()
                    if not p.exists():
                        errors.append(f"[一括] {fn} が {sel_parent} に存在しません。")
                        continue
                    changed, msg, sc_abs = write_sidecar_skipped(p, overwrite=overwrite)
                    batch_res.append({"pdf": str(p), "sidecar": str(sc_abs), "result": msg})
                if batch_res:
                    show_result_box("一括処理結果", batch_res)

    # ---- 従来の個別処理フロー ----
    for uf in uploads:
        fname = Path(uf.name).name
        hits = hits_map.get(fname, [])
        if not hits:
            errors.append(f"{fname} が {pdf_root} 以下に見つかりません。")
            continue

        if len(hits) == 1:
            # 単一候補：常にプレビュー表示、do_run のときだけ書き込み
            p = hits[0].expanduser().resolve()
            st.markdown(f"### ✅ {fname}")
            show_pdf_info_block(p)
            if do_run:
                changed, msg, sc_abs = write_sidecar_skipped(p, overwrite=overwrite)
                results.append({"pdf": str(p), "sidecar": str(sc_abs), "result": msg})
        else:
            # 複数候補：選んだ瞬間にプレビュー、同ブロックのボタンで作成/更新
            with st.expander(f"候補が複数見つかりました — {fname}", expanded=True):
                options = [str(h.expanduser().resolve()) for h in hits]
                sel_key = f"pick_{fname}"
                if sel_key not in st.session_state:
                    # 一括で選ばれている親があれば、そのフォルダ優先で初期化
                    if common_parents:
                        preferred = [o for o in options if Path(o).parent.resolve() in common_parents]
                        st.session_state[sel_key] = preferred[0] if preferred else options[0]
                    else:
                        st.session_state[sel_key] = options[0]

                sel = st.radio(
                    f"{fname} のターゲットを選択",
                    options=options,
                    key=sel_key,
                )

                p = Path(sel).expanduser().resolve()
                show_pdf_info_block(p)  # ← 選択した瞬間にプレビュー

                # 外側の do_run に依存しない独立ボタン
                if st.button(f"→ {fname} はこれに作成/更新", key=f"apply_{fname}"):
                    changed, msg, sc_abs = write_sidecar_skipped(p, overwrite=overwrite)
                    st.success(msg)
                    st.markdown(f"**PDF**: `{p}`")
                    st.markdown(f"**sidecar**: `{sc_abs}`")
                    st.markdown("---")

# ========== 結果出力 ==========
if results:
    show_result_box("処理結果", results)

if errors:
    st.warning("未処理")
    for e in errors:
        st.text(f"- {e}")

# 🔽 ここから新しいクリア処理
# 「一括実行ボタン」が押されていて、かつ uploads があったときだけクリア
if do_run and uploads:
    # 次の run で使う uploader key をインクリメント
    st.session_state["skip_pdf_uploader_key"] += 1
    st.rerun()


# ========== 使い方メモ ==========
with st.expander("ℹ️ 使い方 / 仕様メモ", expanded=False):
    st.markdown(
        """
- **推奨フロー**  
  1. PDF をドロップ  
  2. 自動で `organized/report/pdf` 配下から **同名ファイル** を探索  
  3. 見つかったフォルダに `<basename>_side.json` を作成  
     （内容：`{"type":"image_pdf","created_at":"...","ocr":"skipped"}`）  
  4. 作成または更新後、**sidecar の絶対パス**を表示。

- **同一フォルダ一括**  
  → ドロップした全ファイルが同じフォルダに揃うと判定できた場合、上部に一括作成UIが出ます。  
    ここで選んだフォルダに対して **全ファイル** の side.json をまとめて作成/更新できます。

- **重複候補が複数ある場合**  
  → エクスパンダ内のラジオで選ぶと**即プレビュー**されます。  
    その下のボタンで作成/更新できます（外側の赤いボタンは不要）。

- **絶対パスが分かっている場合**  
  → ②で直接入力し、「上の絶対パスを使う」をONにして作成/更新ボタンを押します。

- **既に side.json がある場合**  
  → デフォルトではスキップ。上書きしたい場合はサイドバーの「上書き/更新する」をONに。

- `created_at` は `+09:00`（JST）で記録されます。
        """
    )
