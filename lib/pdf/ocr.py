# lib/pdf/ocr.py
"""
ocr.py
=================================
OCRmyPDF を用いた OCR 変換。

方針（重要）
------------
- **ページ進捗を出したい場合は CLI 実行が必須**（Python API はページ単位進捗を外に出せない）。
- ただし「Python API を捨てない」ために、次の優先順位にする：
    - progress_cb が **渡された場合**：CLI を最優先（ページ進捗が出せるため）
    - progress_cb が **無い場合**：Python API を最優先（速い/安定なため）→ 失敗時に CLI へ

強化点
------
- Tesseract 言語パックの存在チェックと自動フォールバック（jpn 未導入でも止まらない）
- 低DPI/ベクタPDF対策: image_dpi / oversample
- ページ単位のハング回避: tesseract_timeout
- CLI フォールバックは逐次ログ読取り＋ハードタイムアウト
- 失敗時は英語のみ（eng）で即リトライ
- 進捗表示用の progress_cb を任意で受け取り、外部UI（Streamlit等）に伝播可能
  - 推奨: progress_cb(msg, frac)（frac=0.0〜1.0）
  - 互換: progress_cb(msg)（自動判定）
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Callable
import os
import shutil
import subprocess
import time
import shlex
import inspect
import re

__all__ = ["run_ocr"]

# ============================================================
# progress callback（互換）
# ============================================================
# 推奨: progress_cb(msg: str, frac: Optional[float]) -> None
# 互換: progress_cb(msg: str) -> None

ProgressCB = Optional[Callable[..., None]]  # 1引数/2引数どちらでも許容


def _emit_progress(cb: ProgressCB, msg: str, frac: Optional[float] = None) -> None:
    """progress_cb を安全に呼ぶ（1引数/2引数の両対応）"""
    if cb is None:
        return
    try:
        sig = inspect.signature(cb)
        n_params = len([p for p in sig.parameters.values()
                        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)])
        if n_params >= 2:
            cb(msg, frac)
        else:
            cb(msg)
    except Exception:
        # フォールバック（とにかく落とさない）
        try:
            cb(msg, frac)
        except Exception:
            try:
                cb(msg)
            except Exception:
                pass


# ============================================================
# ページ進捗抽出（CLIログから cur/total を拾う）
# ============================================================
_PAGE_PATTERNS = [
    re.compile(r"(?:Page|page)\s+(\d+)\s*/\s*(\d+)", re.IGNORECASE),         # "Page 3/20"
    re.compile(r"(?:Page|page)\s+(\d+)\s+(?:of)\s+(\d+)", re.IGNORECASE),   # "Page 3 of 20"
    re.compile(r"\b(\d+)\s*/\s*(\d+)\s+pages?\b", re.IGNORECASE),           # "3/20 pages"
    re.compile(r"\b(\d+)\s+(?:of)\s+(\d+)\s+pages?\b", re.IGNORECASE),      # "3 of 20 pages"
    re.compile(r"(?:processing|process)\s+(?:page)\s+(\d+)\s+(?:of)\s+(\d+)", re.IGNORECASE),
]


def _extract_page_progress(line: str) -> Optional[tuple[int, int]]:
    """ログ1行から (cur, total) を抽出。取れなければ None。"""
    for pat in _PAGE_PATTERNS:
        m = pat.search(line)
        if m:
            try:
                cur = int(m.group(1))
                total = int(m.group(2))
                if total > 0:
                    return cur, total
            except Exception:
                pass
    return None


# ------------------------------
# 内部ユーティリティ
# ------------------------------
def _tesseract_has_lang(lang: str) -> bool:
    try:
        out = subprocess.check_output(
            ["tesseract", "--list-langs"],
            text=True,
            stderr=subprocess.STDOUT
        )
        langs = {ln.strip() for ln in out.splitlines()
                 if ln.strip() and not ln.startswith("List of")}
        return lang in langs
    except Exception:
        return False


def _pick_lang(requested: str) -> str:
    """
    "jpn+eng" のような指定から、実在するものだけを残す。
    何も残らなければ eng（存在すれば）にフォールバック。
    """
    parts = [p.strip() for p in (requested or "").split("+") if p.strip()]
    avail = [p for p in parts if _tesseract_has_lang(p)]
    if avail:
        return "+".join(avail)
    return "eng" if _tesseract_has_lang("eng") else (parts[0] if parts else "eng")


def _ocrmypdf_supports_progress_bar() -> bool:
    """ocrmypdf が --progress-bar をサポートするかを help 出力で検知。"""
    exe = shutil.which("ocrmypdf")
    if not exe:
        return False
    try:
        out = subprocess.check_output([exe, "--help"], text=True, stderr=subprocess.STDOUT)
        return "--progress-bar" in out
    except Exception:
        return False


# ------------------------------
# 公開 API
# ------------------------------
def run_ocr(
    src: Path,
    dst: Path,
    *,
    lang: str,
    optimize: int = 1,
    jobs: int = 2,
    rotate_pages: bool = True,
    sidecar_path: Optional[Path] = None,
    # ▼ 進捗：UI に進捗を返す任意コールバック
    #    推奨: progress_cb(msg, frac)  / 互換: progress_cb(msg)
    progress_cb: ProgressCB = None,
    # ▼ 安定化オプション
    image_dpi: int = 300,
    oversample: int = 300,
    tesseract_timeout_sec: int = 60,
    hard_timeout_sec: int = 3600,
) -> None:
    """
    OCR を実行。

    実行順（重要）
    -------------
    - progress_cb がある → CLI（ページ進捗を出せる）を最優先
    - progress_cb がない → Python API を最優先（速い/安定）→ 失敗時は CLI
    """
    lang_eff = _pick_lang(lang)
    _emit_progress(progress_cb, f"OCR 準備: lang={lang_eff}, optimize={optimize}, jobs={jobs}", 0.0)

    # ========================================================
    # A) progress_cb あり：CLI 優先（ページ進捗が欲しい）
    # ========================================================
    if progress_cb is not None:
        try:
            _emit_progress(progress_cb, f"[cli] start (lang={lang_eff})", 0.0)
            _run_cli_streaming(
                src, dst,
                lang=lang_eff,
                optimize=optimize,
                jobs=jobs,
                rotate_pages=rotate_pages,
                sidecar_path=sidecar_path,
                image_dpi=image_dpi,
                oversample=oversample,
                tesseract_timeout_sec=tesseract_timeout_sec,
                hard_timeout_sec=hard_timeout_sec,
                progress_cb=progress_cb,
            )
            _emit_progress(progress_cb, f"[cli] done (lang={lang_eff})", 1.0)
            return
        except Exception as e_cli:
            _emit_progress(progress_cb, f"[cli] failed with lang={lang_eff}: {e_cli}", None)

            # 英語だけで最後のリトライ
            if lang_eff != "eng" and _tesseract_has_lang("eng"):
                _emit_progress(progress_cb, "[cli] retry with eng only…", None)
                _run_cli_streaming(
                    src, dst,
                    lang="eng",
                    optimize=optimize,
                    jobs=jobs,
                    rotate_pages=rotate_pages,
                    sidecar_path=sidecar_path,
                    image_dpi=image_dpi,
                    oversample=oversample,
                    tesseract_timeout_sec=tesseract_timeout_sec,
                    hard_timeout_sec=hard_timeout_sec,
                    progress_cb=progress_cb,
                )
                _emit_progress(progress_cb, "[cli] done (lang=eng)", 1.0)
                return

            raise

    # ========================================================
    # B) progress_cb なし：Python API 優先 → 失敗時 CLI
    # ========================================================
    try:
        _run_python(
            src, dst,
            lang=lang_eff,
            optimize=optimize,
            jobs=jobs,
            rotate_pages=rotate_pages,
            sidecar_path=sidecar_path,
            image_dpi=image_dpi,
            oversample=oversample,
            tesseract_timeout_sec=tesseract_timeout_sec,
        )
        return
    except Exception as e_py:
        # ここは progress_cb が無い想定だが、念のため。
        _emit_progress(progress_cb, f"[python-api] failed: {e_py}. fallback to CLI…", None)

    _run_cli_streaming(
        src, dst,
        lang=lang_eff,
        optimize=optimize,
        jobs=jobs,
        rotate_pages=rotate_pages,
        sidecar_path=sidecar_path,
        image_dpi=image_dpi,
        oversample=oversample,
        tesseract_timeout_sec=tesseract_timeout_sec,
        hard_timeout_sec=hard_timeout_sec,
        progress_cb=progress_cb,
    )


# ------------------------------
# 実体：Python API
# ------------------------------
def _run_python(
    src: Path,
    dst: Path,
    *,
    lang: str,
    optimize: int,
    jobs: int,
    rotate_pages: bool,
    sidecar_path: Optional[Path],
    image_dpi: int,
    oversample: int,
    tesseract_timeout_sec: int,
) -> None:
    """
    OCRmyPDF の Python API を用いる実体処理。
    ※ Python API はページ進捗を外へ出せない。
    """
    import ocrmypdf
    kwargs = dict(
        language=lang,
        output_type="pdf",
        optimize=int(optimize),
        deskew=True,
        clean=True,
        progress_bar=False,
        jobs=int(jobs),
        skip_text=True,
        image_dpi=int(image_dpi),
        oversample=int(oversample),
        tesseract_timeout=int(tesseract_timeout_sec),
        pdf_renderer="sandwich",
    )
    if rotate_pages:
        kwargs["rotate_pages"] = True
    if sidecar_path is not None:
        kwargs["sidecar"] = str(sidecar_path)
    ocrmypdf.ocr(str(src), str(dst), **kwargs)


# ------------------------------
# 実体：CLI（逐次ログ＋タイムアウト＋ページ進捗％）
# ------------------------------
def _run_cli_streaming(
    src: Path,
    dst: Path,
    *,
    lang: str,
    optimize: int,
    jobs: int,
    rotate_pages: bool,
    sidecar_path: Optional[Path],
    image_dpi: int,
    oversample: int,
    tesseract_timeout_sec: int,
    hard_timeout_sec: int,
    progress_cb: ProgressCB,
) -> None:
    exe = shutil.which("ocrmypdf")
    if not exe:
        raise RuntimeError("ocrmypdf が見つかりません。")

    cmd = [
        exe,
        "--language", lang,
        "--output-type", "pdf",
        "--deskew", "--clean",
        "--optimize", str(int(optimize)),
        "--jobs", str(int(jobs)),
        "--skip-text",
        "--image-dpi", str(int(image_dpi)),
        "--oversample", str(int(oversample)),
        "--tesseract-timeout", str(int(tesseract_timeout_sec)),
        "--pdf-renderer", "sandwich",
    ]

    # ★ 存在検知してから付ける（古い ocrmypdf 互換）
    if _ocrmypdf_supports_progress_bar():
        # plain は "Page x/y" 系の文字列が出やすい
        cmd.extend(["--progress-bar", "plain"])

    if rotate_pages:
        cmd.append("--rotate-pages")
    if sidecar_path is not None:
        cmd.extend(["--sidecar", str(sidecar_path)])

    cmd.extend([str(src), str(dst)])

    env = dict(os.environ)
    env.setdefault("LANG", "C")

    # ここは UI で表示したいこともあるので出す（ただし progress_cb が無い場合は無害）
    _emit_progress(progress_cb, f"$ {shlex.join(cmd)}", 0.0)

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )

    start = time.time()
    last_out = start
    lines: list[str] = []

    last_frac: float = 0.0

    try:
        assert proc.stdout is not None

        while True:
            line = proc.stdout.readline()
            now = time.time()

            if line:
                line = line.rstrip("\n")
                lines.append(line)
                last_out = now

                prog = _extract_page_progress(line)
                if prog:
                    cur, total = prog
                    frac = max(0.0, min(cur / max(total, 1), 1.0))
                    last_frac = frac
                    # ★ UI 側が解釈しやすいように、ページ情報を必ず msg に含める
                    _emit_progress(progress_cb, f"Page {cur}/{total}", frac)
                    continue

                # ページ情報以外はノイズになりがちなので、進捗としては出さない（ただし最後のデバッグ用に保持）
                # 必要なら UI 側で msg を表示できるよう、frac は last_frac を添える。
                _emit_progress(progress_cb, line, last_frac)

            else:
                if proc.poll() is not None:
                    break

                # 無出力が長いときだけ軽く通知
                if (now - last_out) > 180:
                    _emit_progress(progress_cb, f"(no output for {int(now - last_out)}s… still working)", last_frac)

                if (now - start) > hard_timeout_sec:
                    try:
                        proc.kill()
                    finally:
                        raise TimeoutError(f"OCR timed out (> {hard_timeout_sec}s): {src}")

                time.sleep(0.2)

        rc = proc.returncode
        if rc != 0:
            msg = "\n".join(lines[-80:])  # 末尾だけ
            raise RuntimeError(f"ocrmypdf exit code {rc}\n{msg}")

    finally:
        try:
            if proc and proc.poll() is None:
                proc.kill()
        except Exception:
            pass