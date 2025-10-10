# 25_PDF整理（処理判定）.py — 画像PDFに sidecar JSON を付与するユーティリティ
# ============================================================
# 概要
# ① pages/30_PDFビューア.py と同様に、organized/report/pdf 直下の
#   上位フォルダ（例: 年フォルダ）をチェック選択する UI を提供。
# ② ①で選んだフォルダ配下の PDF を走査し、quick_pdf_info で種別を判定。
#    - 画像PDFであれば <basename>_side.json を作成（既存ならスキップ）
#    - JSON 構造は {"type":"image_pdf","created_at":"...","ocr":"unprocessed|done"}
#    - <basename>_ocr.pdf が存在すれば、<basename>.pdf の side.json の ocr は "done"
#    - *_ocr.pdf 自身に対しても、画像PDFであれば side.json を作成（ocr は常に "done"）
# ③ 実行は「処理を始める」ボタンで開始。
# ============================================================

from __future__ import annotations
from pathlib import Path
from typing import List, Tuple, Optional
import json
from datetime import datetime, timezone

import streamlit as st

# 依存 lib
from lib.app_paths import PATHS
from lib.viewer.files import list_dirs, list_pdfs, is_ocr_name, dest_ocr_path
from lib.pdf.info import quick_pdf_info
from lib.pdf.paths import rel_from

# *_skip.pdf 検出（存在しない環境用のフォールバックを内蔵）
try:
    from lib.viewer.files import is_skip_name
except Exception:
    def is_skip_name(p: Path) -> bool:
        return p.suffix.lower() == ".pdf" and p.stem.endswith("_skip")

# ------------------------------------------------------------
# UI 設定 & スタイル
# ------------------------------------------------------------
st.set_page_config(page_title="PDF整理（画像PDFに sidecar 付与）", page_icon="🧩", layout="wide")
st.title("🧩 PDF整理 — 画像PDFに sidecar JSON を付与")

st.info("使用ルート：organized_docs_root")

st.markdown(
    """
    <style>
      .block-container {padding-top: 1rem; padding-bottom: 2rem; max-width: 1200px;}
      .mono {font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;}
      .divider {margin: .6rem 0 1rem 0; border-bottom: 1px solid #e5e7eb;}
      .tight {margin-top: 0.2rem; margin-bottom: 0.2rem; line-height: 1.2;}
    </style>
    """,
    unsafe_allow_html=True,
)

# ------------------------------------------------------------
# ルート設定（30_PDFビューア.py と同じ規約）
# ------------------------------------------------------------
def default_pdf_root() -> Path:
    return (Path(str(PATHS.organized_docs_root)).expanduser().resolve() / "report" / "pdf").resolve()

with st.sidebar:
    st.header("基点フォルダ")
    pdf_root = Path(st.text_input("PDF ルートフォルダ", value=str(default_pdf_root()))).expanduser().resolve()
    st.caption(f"実パス: `{pdf_root}`")

if not pdf_root.exists():
    st.error("PDF ルートが存在しません。パスを確認してください。")
    st.stop()

# ------------------------------------------------------------
# ① 上位フォルダ選択（organized/report/pdf 下）
# ------------------------------------------------------------
st.subheader("① 上位フォルダ選択（organized/report/pdf 下）")
st.caption("第1階層のフォルダ（例: 年）をチェック選択します。選ばれたフォルダ配下が処理対象になります。")

if "sel_top" not in st.session_state:
    st.session_state.sel_top = set()

top_folders = list_dirs(pdf_root)
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

# ------------------------------------------------------------
# ユーティリティ：sidecar の作成
# ------------------------------------------------------------
JST = timezone.utc  # Streamlit コンテナはTZ未設定のことがあるため isoformat() はUTCに固定し、"+00:00" を出力。
# ※ 必要なら Asia/Tokyo に変更可 → from datetime import timedelta; JST = timezone(timedelta(hours=9))

SIDE_SUFFIX = "_side.json"

def sidecar_path_for(pdf_path: Path) -> Path:
    return pdf_path.with_name(pdf_path.stem + SIDE_SUFFIX)

@st.cache_data(show_spinner=False)
def _info_for(p: Path) -> dict:
    """quick_pdf_info の薄いラッパ（キャッシュ付）"""
    return quick_pdf_info(str(p), p.stat().st_mtime_ns)

def write_sidecar_if_needed(pdf_path: Path, ocr_state: str, *, force: bool=False) -> tuple[bool, Optional[str]]:
    """
    画像PDFであれば sidecar を作成（既存ならスキップ）。
    戻り値: (作成したか, ステータス文字列)
    """
    try:
        info = _info_for(pdf_path)
        kind = info.get("kind")
    except Exception as e:
        return (False, f"quick_pdf_info 失敗: {e}")

    if kind != "画像PDF":
        return (False, "テキストPDF/その他のため対象外")

    sc_path = sidecar_path_for(pdf_path)
    if sc_path.exists() and not force:
        return (False, "sidecar 既存のためスキップ")

    payload = {
        "type": "image_pdf",
        "created_at": datetime.now(tz=JST).isoformat(),
        "ocr": ocr_state,
    }
    try:
        sc_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return (True, None)
    except Exception as e:
        return (False, f"sidecar 書き込み失敗: {e}")

# ------------------------------------------------------------
# ② 走査 & sidecar 生成ロジック（上書きなし・欠損のみ作成・作成結果のみ表示）
# ------------------------------------------------------------
run_col1 = st.columns(1)[0]
with run_col1:
    dry_run = st.checkbox("ドライラン（作成せずログだけ）", value=False)

start = st.button("▶️ 処理を始める", type="primary", use_container_width=True)

st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

if start:
    if not st.session_state.sel_top:
        st.warning("先に ① で上位フォルダを選択してください。")
        st.stop()

    # 対象PDF収集
    targets: List[Path] = []
    for tname in sorted(st.session_state.sel_top):
        tdir = pdf_root / tname
        if not tdir.exists():
            continue
        for sdir in list_dirs(tdir):
            for p in list_pdfs(sdir):
                if is_skip_name(p):
                    continue
                targets.append(p)

    if not targets:
        st.info("対象となる PDF が見つかりませんでした。")
        st.stop()

    prog = st.progress(0.0, text="スキャン開始")
    made_candidates: List[tuple[Path, Path, str]] = []  # (pdf, sidecar_path, ocr_state)
    err_cnt = 0

    total = len(targets)
    for i, pdf in enumerate(sorted(targets)):
        try:
            partner_ocr = dest_ocr_path(pdf)
        except Exception:
            partner_ocr = pdf.with_name(pdf.stem + "_ocr" + pdf.suffix)

        if is_ocr_name(pdf):
            ocr_state_for_this = "done"
        else:
            ocr_state_for_this = "done" if partner_ocr.exists() else "unprocessed"

        # PDF種別判定
        try:
            info = _info_for(pdf)
            kind = info.get("kind")
        except Exception as e:
            err_cnt += 1
            continue

        if kind != "画像PDF":
            prog.progress((i + 1) / total, text=f"判定中 {i+1}/{total}")
            continue

        sc_path = sidecar_path_for(pdf)
        if sc_path.exists():
            prog.progress((i + 1) / total, text=f"判定中 {i+1}/{total}")
            continue

        # 作成対象（dry_run or 実行）
        if dry_run:
            made_candidates.append((pdf, sc_path, ocr_state_for_this))
        else:
            created, status = write_sidecar_if_needed(pdf, ocr_state_for_this, force=False)
            if created:
                made_candidates.append((pdf, sc_path, ocr_state_for_this))
            else:
                err_cnt += 1

        prog.progress((i + 1) / total, text=f"処理中 {i+1}/{total}")

    prog.empty()

    # === 結果表示 ===
    if dry_run:
        st.success("✅ ドライラン完了：作成予定の side.json 一覧を表示します。")
    else:
        st.success("✅ 処理完了：新規に作成した side.json 一覧を表示します。")

    st.metric("作成対象（または作成済）", len(made_candidates))
    st.metric("エラー", err_cnt)

    if made_candidates:
        with st.expander("📋 作成された（または作成予定の）side.json 一覧", expanded=True):
            for pdf, sc_path, ocr_state in made_candidates:
                st.text(f"{pdf.relative_to(pdf_root)} → {sc_path.name} (ocr={ocr_state})")
    else:
        st.info("新規作成（または作成予定）の side.json はありません。")


else:
    st.markdown("""
    > 『▶️ **処理を始める**』を押すと、選択フォルダ配下の PDF を走査して，画像PDFに対して，そのsidecar（side.json） を作成します。   
    > 既存の `side.json` がある場合はスキップします。
    > 
名前は，`<basename>_side.json` とします．
JSON の構造は次のとおりです．
```json
{
  "type": "image_pdf",
  "created_at": "2025-10-07T08:42:00+09:00",
  "ocr": "unprocessed"
}             
ここで，"ocr": "unprocessed"は未処理という意味です．
未処理の画像pdfファイルに対しては，[OCR処理]タブで，ocrを行って，対応するテキストpdfを作成します．
``` 
```json
③では，画像pdfと判定されているがテキストpdfである可能性があるファイルの調査し，テキストpdfであることがわかった場合には，
 "ocr": "text"               
とタグを付け替える処理を行います． このタグが付いているファイルはocr処理で無視されます．_ocrが付随されたファイルが作成されないので，
ベクトル化処理では，テキストpdfと見なされて，テキストがファイルから抽出され，ベクトルファイルに埋め込まれます．  
[チェックしたものをテキストPDFと判定]のボタンで行う．
```  
```json
また，③では，図面などのocr処理およびベクトル化処理から外したいファイルを判断し，   
"ocr": "skipped"               
とタグを付け替える処理を行います．      
[チェックしたものをskippedに更新]のボタンで行う（チェックしたものを表示しないとこのボタンは出ない）
``` 
""")


# ------------------------------------------------------------
# ③ unprocessed 一覧＋skip更新セクション
# ------------------------------------------------------------
st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
st.subheader("③ ocr=unprocessed のPDFを表示し、skip設定")

def sidecar_path_for(pdf_path: Path) -> Path:
    return pdf_path.with_name(pdf_path.stem + "_side.json")

def get_sidecar_state(pdf_path: Path) -> Optional[str]:
    sc_path = sidecar_path_for(pdf_path)
    if not sc_path.exists():
        return None
    try:
        data = json.loads(sc_path.read_text(encoding="utf-8"))
        return data.get("ocr")
    except Exception:
        return None

def update_sidecar_state(pdf_path: Path, new_state: str) -> bool:
    sc_path = sidecar_path_for(pdf_path)
    if not sc_path.exists():
        return False
    try:
        data = json.loads(sc_path.read_text(encoding="utf-8"))
        data["ocr"] = new_state
        sc_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        st.error(f"{pdf_path.name}: 更新失敗 — {e}")
        return False

# ------------------------------------------------------------
# 走査：unprocessed の side.json を持つPDFを探す（lib/pdf/text.py を使用）
# ------------------------------------------------------------
from lib.pdf.text import analyze_pdf_texts  # ★このpyを使用

unprocessed_pdfs: List[Path] = []
for tname in sorted(st.session_state.sel_top):
    tdir = pdf_root / tname
    for sdir in list_dirs(tdir):
        for pdf in list_pdfs(sdir):
            if get_sidecar_state(pdf) == "unprocessed":
                unprocessed_pdfs.append(pdf)

if not unprocessed_pdfs:
    st.info("ocr=unprocessed のPDFは見つかりませんでした。")
else:
    st.write(f"対象 {len(unprocessed_pdfs)} 件。対象PDFにチェックを入れてください。")

    

    # --- チェックリスト（ページ数付き） ---
    @st.cache_data(show_spinner=False)
    def get_page_count(p: Path) -> Optional[int]:
        """quick_pdf_info から pages を取得"""
        try:
            info = quick_pdf_info(str(p), p.stat().st_mtime_ns)
            return info.get("pages")
        except Exception:
            return None

    to_act: List[Path] = []
    for p in unprocessed_pdfs:
        rel = p.relative_to(pdf_root)
        pages = get_page_count(p)
        label = f"{rel}（{pages}p）" if pages else f"{rel}（p不明）"
        if st.checkbox(label, key=f"chk_{rel}"):
            to_act.append(p)

    # --- (1) テキスト抽出ボタンと注意書き（lib/pdf/text.py の analyze_pdf_texts を使用） ---
    st.markdown("---")  # ← 横線を引く
    st.markdown(
        "> **注意**: ここで抽出したテキストを確認して、"
        "「画像PDFと**簡易判定**されたものが、実は**テキストPDFではないか**」を**最終判定**してください。"
    )
    col_tx_left, col_tx_right = st.columns([1, 2])
    with col_tx_right:
        sample_pages = st.slider("抽出する先頭Nページ", 1, 20, 6, 1, key="extract_pages")

    if col_tx_left.button("📝 チェックしたものからテキスト抽出"):
        if not to_act:
            st.warning("抽出対象が選ばれていません。PDFにチェックを入れてください。")
        else:
            st.info(f"{len(to_act)} 件からテキストを抽出します（先頭 {sample_pages} ページ）。")
            for p in to_act:
                rel = p.relative_to(pdf_root)
                try:
                    info = analyze_pdf_texts(
                        str(p),
                        p.stat().st_mtime_ns,
                        mode="sample",
                        sample_pages=int(sample_pages),
                    )
                    pages = info.get("pages", [])
                    with st.expander(f"🔎 {rel}", expanded=False):
                        if not pages:
                            st.text("（抽出テキストは見つかりませんでした）")
                        else:
                            for row in pages:
                                st.markdown(f"**p.{row['page']}**")
                                st.text((row.get("text") or "")[:1000] or "（このページでテキストは検出されませんでした）")
                except Exception as e:
                    with st.expander(f"🔎 {rel}", expanded=False):
                        st.text(f"（抽出に失敗しました: {e}）")

    # st.markdown("---")

    # --- (2) テキストPDFと判定 → side.json の ocr を 'text' に更新 ---
    if st.button("✅ チェックしたものをテキストPDFと判定（ocr = 'text' に更新）（ocrしないで，テキストを単に抽出する）",type="primary"):
        if not to_act:
            st.warning("更新対象が選ばれていません。PDFにチェックを入れてください。")
        else:
            updated = 0
            for p in to_act:
                if update_sidecar_state(p, "text"):
                    updated += 1
            st.success(f"{updated} 件の side.json を 'text' に更新しました。")

    st.markdown("---")


# --- (3) チェックしたものを表示（ビューア） ---
st.markdown(
    "> **確認フロー**: 図面など **OCRをスキップしたい候補** は、まず "
    "『👁 チェックしたものを表示』で実際のPDFを確認 → 問題なければ "
    "下の『💾 チェックしたものを skipped に更新』で除外してください。"
)

# ビューア設定
viewer_ctl_l, viewer_ctl_r = st.columns([1, 2])
with viewer_ctl_r:
    v_width = st.slider("表示幅(px)", 600, 1400, 900, 20, key="vw_checked")
    v_height = st.slider("表示高(px)", 400, 1400, 820, 20, key="vh_checked")

# --- 💾 skipped 更新ボタンをここに配置（👁ボタンより前に） ---
if st.button("💾 チェックしたものを skipped に更新（図面や発注書などの画像データ）（ocrやベクトル化から除く）", type="primary"):
    if not to_act:
        st.warning("更新対象が選ばれていません。PDFにチェックを入れてください。")
    else:
        updated = 0
        for p in to_act:
            if update_sidecar_state(p, "skipped"):
                updated += 1
        st.success(f"{updated} 件の side.json を 'skipped' に更新しました。")

# 表示ボタン
if viewer_ctl_l.button("👁 チェックしたものを表示"):
    if not to_act:
        st.warning("表示対象が選ばれていません。PDFにチェックを入れてください。")
    # 次回リラン後も維持できるよう session_state に格納
    st.session_state._checked_to_show = [str(p) for p in to_act]

# セッションから表示対象を復元
to_show_paths = [Path(s) for s in st.session_state.get("_checked_to_show", [])]

if to_show_paths:
    st.subheader("👁 ビューア（チェックしたPDFを同時表示）")
    from lib.pdf.io import read_pdf_bytes  # 既存ヘルパー

    # 同時表示の上限とレイアウト
    MAX_VIEW = 12
    items = to_show_paths[:MAX_VIEW]
    labels = [str(p.relative_to(pdf_root)) for p in items]

    # グリッド列数と余白調整
    lay_l, lay_r = st.columns([1, 3])
    with lay_r:
        grid_cols = st.slider("グリッド列数", 1, 4, 2, 1, key="vw_cols_checked")

    # クリアボタン（表示対象をリセット）
    if lay_l.button("🧹 表示をクリア"):
        st.session_state._checked_to_show = []
        # Streamlit 1.24 以降は st.rerun、旧版は experimental_rerun
        if hasattr(st, "rerun"):
            st.rerun()
        else:
            st.experimental_rerun()

    # グリッド表示
    rows = (len(items) + grid_cols - 1) // grid_cols
    idx = 0
    for _ in range(rows):
        cols = st.columns(grid_cols)
        for c in range(grid_cols):
            if idx >= len(items):
                break
            p = items[idx]
            lab = labels[idx]
            idx += 1
            with cols[c]:
                st.markdown(f"**{lab}**")
                try:
                    data = read_pdf_bytes(str(p), p.stat().st_mtime_ns)
                    st.pdf(data, height=int(v_height), key=f"stpdf_{p.name}_{p.stat().st_mtime_ns}")
                    with open(p, "rb") as fh:
                        st.download_button("📥 このPDFをダウンロード", data=fh.read(), file_name=p.name, mime="application/pdf")
                except Exception as e:
                    st.error(f"{p.name} の表示に失敗しました: {e}")

    if len(to_show_paths) > MAX_VIEW:
        st.info(f"表示は先頭 {MAX_VIEW} 件までです。残り {len(to_show_paths) - MAX_VIEW} 件。")



    # # 既存: skipped に更新
    # if st.button("💾 チェックしたものを skipped に更新", type="primary"):
    #     if not to_act:
    #         st.warning("更新対象が選ばれていません。PDFにチェックを入れてください。")
    #     else:
    #         updated = 0
    #         for p in to_act:
    #             if update_sidecar_state(p, "skipped"):
    #                 updated += 1
    #         st.success(f"{updated} 件の side.json を 'skipped' に更新しました。")
