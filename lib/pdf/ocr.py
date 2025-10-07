"""
ocr.py
=================================
OCRmyPDF を用いた OCR 変換（Python API を優先、失敗時は CLI へフォールバック）。

強化点
------
- Tesseract 言語パックの存在チェックと自動フォールバック（jpn 未導入でも止まらない）
- 低DPI/ベクタPDF対策: image_dpi / oversample
- ページ単位のハング回避: tesseract_timeout
- CLI フォールバックは逐次ログ読取り＋ハードタイムアウト
- 失敗時は英語のみ（eng）で即リトライ
- 進捗表示用の progress_cb を任意で受け取り、外部UI（Streamlit等）に伝播可能
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional, Callable
import os
import shutil
import subprocess
import time
import shlex

__all__ = ["run_ocr"]

# ------------------------------
# 内部ユーティリティ
# ------------------------------
def _tesseract_has_lang(lang: str) -> bool:
    try:
        out = subprocess.check_output(["tesseract", "--list-langs"],
                                      text=True, stderr=subprocess.STDOUT)
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
    """
    ocrmypdf が --progress-bar をサポートするかを help 出力で検知。
    """
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
    # ▼ 追加：UI に進捗を返す任意コールバック（1行ずつ渡す）
    progress_cb: Optional[Callable[[str], None]] = None,
    # ▼ 追加：安定化オプション
    image_dpi: int = 300,
    oversample: int = 300,
    tesseract_timeout_sec: int = 60,
    hard_timeout_sec: int = 3600,
) -> None:
    """
    OCR を実行（Python API → 失敗時は CLI、さらに失敗時は eng で再試行）。

    progress_cb: 文字列ログを受け取る任意のコールバック（UI更新に使える）
    """
    # 実在する言語だけに整形
    lang_eff = _pick_lang(lang)

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
        # Python API 失敗 → CLI へ
        if progress_cb:
            progress_cb(f"[python-api] failed: {e_py}. fallback to CLI…")

    try:
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
        return
    except Exception as e_cli:
        # CLI も失敗 → 英語だけで最後のリトライ
        if lang_eff != "eng" and _tesseract_has_lang("eng"):
            if progress_cb:
                progress_cb(f"[cli] failed with lang={lang_eff}: {e_cli}. retry with eng only…")
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
            return
        raise

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
    ※ Python API はコールバックで逐次ログを取りづらいため、失敗時は CLI にフォールバック。
    """
    import ocrmypdf
    kwargs = dict(
        language=lang,
        output_type="pdf",
        optimize=int(optimize),
        deskew=True,
        clean=True,
        progress_bar=False,   # 逐次ログは CLI 側で対応
        jobs=int(jobs),
        force_ocr=True,
        # skip_text=False,
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
# 実体：CLI（逐次ログ＋タイムアウト）
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
    progress_cb: Optional[Callable[[str], None]],
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
        "--force-ocr",
        "--image-dpi", str(int(image_dpi)),
        "--oversample", str(int(oversample)),
        "--tesseract-timeout", str(int(tesseract_timeout_sec)),
        "--pdf-renderer", "sandwich",
    ]

    # ★ 存在検知してから付ける（古い ocrmypdf 互換）
    if _ocrmypdf_supports_progress_bar():
        cmd.extend(["--progress-bar", "plain"])

    if rotate_pages:
        cmd.append("--rotate-pages")
    if sidecar_path is not None:
        cmd.extend(["--sidecar", str(sidecar_path)])

    cmd.extend([str(src), str(dst)])

    env = dict(os.environ)
    env.setdefault("LANG", "C")

    if progress_cb:
        progress_cb(f"$ {shlex.join(cmd)}")

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
    lines = []

    try:
        while True:
            line = proc.stdout.readline()
            now = time.time()

            if line:
                line = line.rstrip("\n")
                lines.append(line)
                last_out = now
                if progress_cb:
                    # Tesseract の行はわかりやすく前置（任意）
                    if line.startswith("[tesseract]"):
                        progress_cb("Tesseract: " + line[12:].strip())
                    else:
                        progress_cb(line)
            else:
                if proc.poll() is not None:
                    break

                if (now - last_out) > 180 and progress_cb:
                    progress_cb(f"(no output for {int(now - last_out)}s… still working)")
                if (now - start) > hard_timeout_sec:
                    try:
                        proc.kill()
                    finally:
                        raise TimeoutError(f"OCR timed out (> {hard_timeout_sec}s): {src}")

                time.sleep(0.2)

        rc = proc.returncode
        if rc != 0:
            msg = "\n".join(lines[-50:])  # 末尾だけ
            raise RuntimeError(f"ocrmypdf exit code {rc}\n{msg}")

    finally:
        try:
            if proc and proc.poll() is None:
                proc.kill()
        except Exception:
            pass
