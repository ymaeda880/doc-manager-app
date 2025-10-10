"""
20_PDF_OCR変換.py
=================================
画像PDF → テキストPDF 変換（OCR）＋ 全PDFのテキスト(.txt)保存（Streamlitページ）

概要
----
- `secrets.toml` を `lib.app_paths.PATHS` で解決し、既定の入出力ルートを利用。
  - PDF 入力: `PATHS.pdf_root`
  - 変換PDF 出力: `PATHS.converted_root`
  - テキスト出力: `PATHS.text_root`
- 画像PDFのみを対象に OCR を実行し（テキスト層を付与した PDF を生成）、
  併せて全PDFのテキスト（.txt）を保存するユーティリティ。

機能
----
1) 対象PDFの列挙・フィルタ
   - 部分一致（ファイル名）／年フォルダ（例: "2024,2025"）
2) 軽量スキャンで「画像PDF」を判定（`quick_pdf_info`）
3) OCR 実行（`run_ocr`）
   - まず OCRmyPDF の Python API を試行、失敗時は CLI へ自動フォールバック
   - 言語・最適化レベル・並列数・自動回転・sidecar 出力の指定が可能
4) 実行ログ表示（成功／失敗／スキップ）
5) 全PDFのテキスト保存（`extract_text_pdf` → `write_text_file`）
   - 変換済みPDFが存在すればそれを優先
   - sidecar（`.sidecar.txt`）があればフォールバック読込
6) 環境チェック表示（`env_checks`）
   - `ocrmypdf`(Python/CLI)・`tesseract` の有無を表示

UI 項目
-------
- 入力／出力フォルダ（テキスト欄で上書き可。既定は `secrets.toml`）
- フィルタ: ファイル名部分一致・年フォルダ
- OCR 設定: `lang`, `optimize(0..3)`, `jobs`, `rotate_pages`, `sidecar` 保存
- オプション: 既存出力の上書き再変換、全PDFのテキスト保存

入出力規約
----------
- 変換後 PDF の命名: `<元stem>_converted.pdf`
  - パス計算は `make_converted_path()` を使用
- テキスト保存先の計算: `make_text_path()` を使用
- ログは画面表示のみ（ファイル出力は行わない）

依存
----
- PyMuPDF (`fitz`), OCRmyPDF, Tesseract, Streamlit

利用モジュール（lib/pdf/*）
---------------------------
- `quick_pdf_info`, `run_ocr`, `extract_text_pdf`, `write_text_file`
- `iter_pdfs`, `rel_from`, `make_converted_path`, `make_text_path`
- `env_checks`

注意
----
- OCR は「画像PDF」と判定されたもののみ対象。
- 出力PDFが既に存在し、上書き OFF の場合はスキップ。
- テキスト保存は OCR 実行とは独立して実行可能（ボタンで個別に実行）。
"""

from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Any

import streamlit as st

# 直接 lib/pdf/* を利用（互換レイヤ廃止）
from lib.pdf.info import quick_pdf_info
from lib.pdf.ocr import run_ocr
from lib.pdf.text import extract_text_pdf, write_text_file
from lib.pdf.paths import rel_from, iter_pdfs, make_converted_path, make_text_path
from lib.pdf.sysenv import env_checks

# プロジェクトの標準パス（secrets.toml から解決）
from lib.app_paths import PATHS

# ========= UI =========
st.set_page_config(page_title="画像PDF → テキストPDF 変換", page_icon="🧾", layout="wide")
st.title("🧾 画像PDF → テキストPDF 変換（OCR）＋ 全PDFテキスト保存")

with st.sidebar:
    st.header("対象と出力（既定は secrets.toml から）")
    src_root = Path(st.text_input("入力フォルダ", value=str(PATHS.pdf_root))).expanduser().resolve()
    dst_root = Path(st.text_input("変換PDF出力フォルダ", value=str(PATHS.converted_root))).expanduser().resolve()
    txt_root = Path(st.text_input("テキスト出力フォルダ", value=str(PATHS.text_root))).expanduser().resolve()

    st.caption("※ フィールドを編集すればその場で上書きできます。")

    st.subheader("フィルタ（任意）")
    name_filter = st.text_input("ファイル名フィルタ（部分一致）", value="").strip()
    year_filter = st.text_input("年フォルダ（例: 2024,2025）", value="").strip()

    st.subheader("OCR 設定")
    lang = st.text_input("言語（tesseract langs）", value="jpn+eng")
    optimize = st.select_slider("最適化（圧縮）", options=[0, 1, 2, 3], value=1)
    jobs = st.slider("並列ジョブ数", min_value=1, max_value=8, value=2, step=1)
    rotate_pages = st.checkbox("自動回転補正", value=True)
    save_sidecar = st.checkbox("sidecar 保存（.sidecar.txt）", value=True)

    overwrite_pdf = st.checkbox("変換PDFを上書き再変換", value=False)
    do_text_export = st.checkbox("全PDFをテキスト保存", value=True)

    st.divider()
    st.subheader("環境チェック")
    env = env_checks()
    st.write(f"ocrmypdf (Python): {'✅' if env['ocrmypdf_py'] else '❌'}")
    st.write(f"ocrmypdf (CLI)   : {'✅' if env['ocrmypdf_cli'] else '❌'}")
    st.write(f"tesseract        : {'✅' if env['tesseract'] else '❌'}")

# 入力ファイル列挙
src_files = iter_pdfs(src_root)
if name_filter:
    src_files = [p for p in src_files if name_filter.lower() in p.name.lower()]
if year_filter:
    years = {y.strip() for y in year_filter.split(",") if y.strip()}
    if years:
        # 先頭のフォルダ名(例: 2025/xxx.pdf) 等で年を判断
        filtered = []
        for p in src_files:
            try:
                parts = p.relative_to(src_root).parts
            except ValueError:
                parts = p.parts
            if any(part in years for part in parts[:2]):  # 年/サブ年 くらいまで見る
                filtered.append(p)
        src_files = filtered

if not src_files:
    st.warning("対象PDFが見つかりません。")
    st.stop()

# OCR対象リストを作成
rows: List[Dict[str, Any]] = []
with st.spinner("画像PDF 判定中…"):
    for p in src_files:
        if p.stem.endswith("_converted"):
            continue
        info = quick_pdf_info(str(p), p.stat().st_mtime_ns)
        if info.get("kind") != "画像PDF":
            continue
        out_path = make_converted_path(p, src_root, dst_root)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        status = "未変換"
        if out_path.exists():
            status = "出力あり（スキップ）" if not overwrite_pdf else "上書き対象"
        rows.append({
            "src_rel": rel_from(p, src_root),
            "dst_rel": rel_from(out_path, dst_root),
            "pages": info.get("pages", 0),
            "status": status,
            "src": p,
            "dst": out_path
        })

if rows:
    st.markdown(f"### OCR 対象: {len(rows)} 件")
    st.dataframe(
        [{"入力": r["src_rel"], "出力": r["dst_rel"], "pages": r["pages"], "status": r["status"]} for r in rows],
        width="stretch",
        height=400,
    )
else:
    st.info("画像PDFは見つかりませんでした（テキスト保存のみ実行したい場合は下のボタンを押してください）。")

# 実行
do_convert = st.button("🧾 OCR 実行", type="primary", width="stretch")
if do_convert:
    ok, ng, skip = 0, 0, 0
    logs: List[str] = []
    for r in rows:
        src, dst = r["src"], r["dst"]
        if dst.exists() and not overwrite_pdf:
            skip += 1
            logs.append(f"⏭️ スキップ: {r['src_rel']}")
            continue
        try:
            sidecar_path = dst.with_suffix(".sidecar.txt") if save_sidecar else None
            run_ocr(
                src, dst,
                lang=lang, optimize=int(optimize), jobs=int(jobs),
                rotate_pages=rotate_pages, sidecar_path=sidecar_path
            )
            ok += 1
            logs.append(f"✅ 完了: {r['src_rel']}")
        except Exception as e:
            ng += 1
            logs.append(f"❌ 失敗: {r['src_rel']} : {e}")
    st.success(f"OCR 完了: 成功 {ok} / 失敗 {ng} / スキップ {skip}")
    st.code("\n".join(logs))

# 全PDFテキスト保存（任意）
if st.button("📝 全PDFテキスト保存を実行", width="stretch") or (do_convert and do_text_export):
    text_ok, text_skip, text_ng = 0, 0, 0
    for p in src_files:
        # 変換済みがあればそれを優先
        spdf = p if p.stem.endswith("_converted") else make_converted_path(p, src_root, dst_root)
        if not spdf.exists():
            spdf = p
        txt_path = make_text_path(spdf, src_root, dst_root, txt_root)
        if txt_path.exists():
            text_skip += 1
            continue
        sidecar = spdf.with_suffix(".sidecar.txt")
        txt = extract_text_pdf(spdf, sidecar)
        if txt:
            write_text_file(txt_path, txt)
            text_ok += 1
        else:
            text_ng += 1
    st.success(f"テキスト保存: 成功 {text_ok} / スキップ {text_skip} / 失敗 {text_ng}")
