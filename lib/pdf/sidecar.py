# lib/pdf/sidecar.py
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
import json

SIDE_SUFFIX = "_side.json"
# 既定は Asia/Tokyo (+09:00)。UTC にしたい場合は timezone.utc に置き換え可。
JST = timezone(timedelta(hours=9))

def sidecar_path_for(pdf_path: Path) -> Path:
    """<basename>.pdf → <basename>_side.json のパスを返す"""
    return pdf_path.with_name(pdf_path.stem + SIDE_SUFFIX)

def normalize_json_text(s: str) -> str:
    """スマート引用符など JSON として不正な記号を標準の記号に変換"""
    return s.replace("“", "\"").replace("”", "\"").replace("’", "'")

def load_sidecar_dict(sc_path: Path) -> Optional[dict]:
    """side.json を dict で読み取る（失敗時 None）。スマート引用符耐性あり。"""
    if not sc_path.exists():
        return None
    raw = sc_path.read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except Exception:
        try:
            return json.loads(normalize_json_text(raw))
        except Exception:
            return None

def read_ocr_state_for_pdf(pdf_path: Path) -> Optional[str]:
    """PDF に対応する side.json の 'ocr' 値を返す（無ければ None）"""
    data = load_sidecar_dict(sidecar_path_for(pdf_path))
    if isinstance(data, dict) and data.get("type") == "image_pdf":
        return data.get("ocr")
    return None

def find_pdf_for_sidecar(sc_path: Path) -> Optional[Path]:
    """
    *_side.json から元PDFを推定。拡張子の大小文字差異に対応。
    """
    stem = sc_path.stem  # e.g. 'REP10_01_side'
    base = stem[:-5] if stem.endswith("_side") else stem  # 'REP10_01'
    # 代表的なバリエーション
    for ext in [".pdf", ".PDF", ".Pdf", ".pDf", ".pdF"]:
        cand = sc_path.with_name(base + ext)
        if cand.exists():
            return cand
    # 念のため親フォルダを走査
    for p in sc_path.parent.glob(base + ".*"):
        if p.suffix.lower() == ".pdf":
            return p
    return None

def ensure_sidecar(pdf_path: Path, ocr_state: str, *, overwrite: bool=False) -> Tuple[bool, str]:
    """
    規定構造の side.json を作成/維持する。
    - overwrite=False かつ既存がある場合は上書きしない（'exists' 返却）
    戻り値: (変更があったか, 'created'|'updated'|'exists')
    """
    sc = sidecar_path_for(pdf_path)
    if sc.exists() and not overwrite:
        return (False, "exists")

    payload = {
        "type": "image_pdf",
        "created_at": datetime.now(tz=JST).isoformat(),
        "ocr": ocr_state,
    }
    sc.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return (True, "created")

def update_sidecar_ocr(pdf_path: Path, new_state: str) -> Tuple[bool, str]:
    """
    side.json の 'ocr' を new_state に更新。
    無ければ規定構造で新規作成（created）。
    戻り値: (変更があったか, 'created'|'updated')
    """
    sc = sidecar_path_for(pdf_path)
    data = load_sidecar_dict(sc) or {}
    if not isinstance(data, dict):
        data = {}

    changed = False
    if "type" not in data:
        data["type"] = "image_pdf"; changed = True
    if "created_at" not in data:
        data["created_at"] = datetime.now(tz=JST).isoformat(); changed = True
    if data.get("ocr") != new_state:
        data["ocr"] = new_state; changed = True

    sc.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return (True, "created" if "ocr" not in data else "updated")
