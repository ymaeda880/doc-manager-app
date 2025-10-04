# lib/fsnav/scan.py
# ============================================
#  ファイルシステム走査ユーティリティ（directory & file scanner）
#
#  目的:
#    - ディレクトリ走査（os.walk）でよく使う処理を関数化し、再利用性を高める。
#    - Streamlit 以外のスクリプトからも使えるよう、副作用は持たせない。
#
#  提供関数（public API）
#    - is_hidden_rel(rel_parts)        : 隠しパス判定（相対パスの各要素に'.'始まりが含まれるか）
#    - safe_stat_mtime(p)              : mtime（modification time）を例外安全に取得
#    - listdir_counts(p)               : ディレクトリ直下（非再帰）の files/dirs 件数
#    - iter_dirs(root, max_depth, ...) : 深さ制御付きのディレクトリ列挙ジェネレータ
#    - ext_key(path)                   : 拡張子の正規化（.pdf / <none>）
#    - walk_tree_collect(...)          : ツリー走査＋早期停止＋拡張子集計（ページの主処理を関数化）
# ============================================

#  提供関数（Public API）— ChatGPT向けクイックリファレンス
#  ------------------------------------------------------------------
#  この断片（セクション）だけを貼っても、ChatGPTが使い方を再構築できるように、
#  関数シグネチャ、引数、戻り値スキーマ、最小実行例、LLM向け指示例を含めています。
#
#  モジュールの想定配置:
#      lib/fsnav/scan.py   （インポート例: `from lib.fsnav.scan import ...`）
#
#  1) 関数とシグネチャ
#  ------------------------------------------------------------------
#  is_hidden_rel(rel_parts: tuple[str, ...]) -> bool
#      相対パスの各要素に '.' 始まり（hidden）が含まれるか判定。
#
#  safe_stat_mtime(p: pathlib.Path) -> float
#      パス p の mtime（UNIX epoch秒, float）を例外安全に取得。失敗時は 0.0。
#
#  listdir_counts(p: pathlib.Path) -> tuple[int, int]
#      ディレクトリ p の「直下（非再帰）」の (files, dirs) 件数を返す。symlink除外。
#
#  iter_dirs(root: pathlib.Path, max_depth: int, *, ignore_hidden: bool=True) -> Iterator[pathlib.Path]
#      root配下のディレクトリを深さ max_depth まで列挙（root自身は含まない）。
#      隠しフォルダ（'.'始まり）は列挙せず配下にも潜らない（prune, followlinks=False）。
#
#  ext_key(path: pathlib.Path) -> str
#      拡張子を「ドット付き・小文字」で返す。拡張子なしは '<none>'。
#
#  walk_tree_collect(
#      base_root: pathlib.Path,
#      *,
#      max_depth: int,
#      ignore_hidden: bool = True,
#      name_filter: str = "",
#      compute_counts: bool = False,
#      max_rows_total: int = 10_000,
#  ) -> tuple[list[dict], list[dict], dict[str, int], int, int]
#      ディレクトリ/ファイルを走査し、ページ表示に必要な構造を一括生成する上位API。
#      （深さ制御 / 隠しフォルダpruning / 名前部分一致 / 早期停止 / 拡張子集計）
#
#  2) 戻り値スキーマ（walk_tree_collect）
#  ------------------------------------------------------------------
#      rows_dirs: list[dict]   # 例: {
#          "kind": "dir",
#          "path": "<base_rootからの相対パス:str>",
#          "name": "<フォルダ名:str>",
#          "depth": <int>,                          # base_root直下=1
#          "parent": "<親の相対パス:str|''>",
#          "modified": <datetime|None>,             # mtime=0.0ならNone
#          "files_direct": <int|None>,              # compute_counts=True時のみ
#          "dirs_direct": <int|None>,               # 同上
#      }
#
#      rows_files: list[dict]  # 例: {
#          "kind": "file",
#          "path": "<相対パス:str>",
#          "name": "<ファイル名:str>",
#          "depth": <int>,                          # 親フォルダの深さ
#          "parent": "<親の相対パス:str|''>",
#          "modified": <datetime|None>,
#          "size_bytes": <int|None>,                # 存在確認の上取得
#          "ext": "<'.pdf' 等|'<none>'>",           # ext_keyで正規化
#      }
#
#      filetype_counts: dict[str, int]  # 例: {'.pdf': 1234, '.txt': 98, '<none>': 3}
#      total_rows: int                  # rows_dirs + rows_files の合計（早期停止で頭打ち可）
#      max_depth_found: int             # 実際に検出した最大深さ（dir/fileの最大）
#
#  3) 最小実行例（コピー＆ペースト可）
#  ------------------------------------------------------------------
#  from pathlib import Path
#  from lib.fsnav.scan import walk_tree_collect, iter_dirs, listdir_counts, ext_key
#  import pandas as pd
#
#  base = Path("/path/to/docs")
#  rows_dirs, rows_files, counts, total, maxd = walk_tree_collect(
#      base_root=base,
#      max_depth=3,
#      ignore_hidden=True,
#      name_filter="",         # 例: "report" で部分一致
#      compute_counts=False,   # I/Oを抑えるならFalse
#      max_rows_total=50_000,  # 早期停止の上限
#  )
#
#  # DataFrame化とCSV保存
#  pd.DataFrame(rows_dirs).to_csv("dirs.csv", index=False)
#  pd.DataFrame(rows_files).to_csv("files.csv", index=False)
#
#  # 深さ1のフォルダ候補だけ欲しい場合
#  level1 = list(iter_dirs(base, max_depth=1))
#
#  4) 代表的なユースケース（LLMへの指示例）
#  ------------------------------------------------------------------
#  - 「深さ=2、隠しフォルダ除外、名前に 'pdf' を含む要素だけを列挙し、
#     合計行数が 5000 を超えたら早期停止してください。」
#  - 「拡張子別の件数（filetype_counts）を降順に並べ、上位5件を報告。
#     '.pdf' が何件かも明記してください。」
#  - 「compute_counts=True にして、各フォルダの直下 files/dirs をKPIとして表示用に集計してください。」
#
#  5) 実装上の注意点
#  ------------------------------------------------------------------
#  - os.walk(topdown=True, followlinks=False)。symlinkは追跡しません。
#  - 隠しフォルダ（'.' 始まり）は列挙せず配下にも潜りません（pruning）。
#  - name_filter はフォルダ名・ファイル名の双方に適用（case-insensitive）。
#  - 例外（権限/一時I/O）は握りつぶします。UI側で「不明」扱いの設計を想定。
#  - compute_counts=True は I/O が増えるため必要時のみ推奨。


from __future__ import annotations
from pathlib import Path
from typing import Iterator, Dict, Any, List, Tuple
import os
import datetime as dt

__all__ = [
    "is_hidden_rel",
    "safe_stat_mtime",
    "listdir_counts",
    "iter_dirs",
    "ext_key",
    "walk_tree_collect",
]

# -------- 基本 helpers --------

def is_hidden_rel(rel_parts: Tuple[str, ...]) -> bool:
    """
    相対パス要素に '.' 始まり（hidden）が含まれるか判定（UNIX慣習）。

    Parameters
    ----------
    rel_parts : tuple[str, ...]
        例: ROOT/foo/bar -> ("foo", "bar")

    Returns
    -------
    bool
        どれかが '.' 始まりなら True。

    Notes
    -----
    - 「隠しフォルダ（hidden directory, '.' leading）」の枝は探索対象から外す
      かどうかの判定に使う軽量ヘルパ（pruning の前判定）。

    ---- Usage (for AI/LLM) -----------------------------------
    • 入力は「ROOT からの相対パーツのタプル」。os.walk 中に
      Path(cur).relative_to(ROOT).parts として得られます。
    • True が返れば、その枝の子孫探索を打ち切る等の制御に利用可能。
    • 例:
        >>> is_hidden_rel(("normal", ".git", "objects"))
        True
        >>> is_hidden_rel(("documents", "reports"))
        False
    -----------------------------------------------------------
    """
    return any(p.startswith(".") for p in rel_parts)


def safe_stat_mtime(p: Path) -> float:
    """
    パス p の mtime（modification time, UNIX epoch 秒）を例外安全に取得。
    失敗時は 0.0 を返す。

    Parameters
    ----------
    p : pathlib.Path
        対象のファイルまたはディレクトリ。

    Returns
    -------
    float
        UNIX epoch 秒（例外時は 0.0）。

    Notes
    -----
    - 権限・I/O・消失などの例外で失敗しても落とさない。
    - GUI 表示や並べ替えの都合で None ではなく 0.0 を返す設計。

    ---- Usage (for AI/LLM) -----------------------------------
    • 「ソートキー」や「更新日表示」の前処理として使用。
    • 0.0 は「取得不能」を意味する sentinel として扱い、表示側で
      “不明” 表示や末尾ソートなどに使うのが実務的。
    • 例:
        >>> from pathlib import Path
        >>> safe_stat_mtime(Path("/does/not/exist"))
        0.0
    -----------------------------------------------------------
    """
    try:
        return float(p.stat().st_mtime)
    except Exception:
        return 0.0


def listdir_counts(p: Path) -> Tuple[int, int]:
    """
    ディレクトリ p の直下（非再帰）の files/dirs 件数をカウント。
    symlink は除外。

    Parameters
    ----------
    p : pathlib.Path

    Returns
    -------
    (files, dirs) : tuple[int, int]

    Notes
    -----
    - os.scandir を用いるため高速・軽量（非再帰）。
    - 個々のエントリでの例外は握りつぶし、全体としては継続。

    ---- Usage (for AI/LLM) -----------------------------------
    • 「直下のファイル数」「直下のフォルダ数」の KPI を表示したい場合に使用。
    • 再帰でないので巨大ツリーでも安全。必要時のみ呼ぶ設計が望ましい。
    • 例:
        >>> files, dirs = listdir_counts(Path("/tmp"))
        >>> isinstance(files, int) and isinstance(dirs, int)
        True
    -----------------------------------------------------------
    """
    files = dirs = 0
    try:
        with os.scandir(p) as it:
            for e in it:
                try:
                    if e.is_symlink():
                        continue
                    if e.is_dir():
                        dirs += 1
                    elif e.is_file():
                        files += 1
                except Exception:
                    continue
    except Exception:
        pass
    return files, dirs


def iter_dirs(root: Path, max_depth: int, *, ignore_hidden: bool = True) -> Iterator[Path]:
    """
    root 配下のディレクトリを深さ max_depth まで列挙。

    Parameters
    ----------
    root : pathlib.Path
        探索の起点ディレクトリ。
    max_depth : int
        列挙する最大深さ（>=1）。
        depth=1 は root の直下、depth=2 は root/foo/bar のように定義。
    ignore_hidden : bool, default True
        '.' 始まりのフォルダを列挙せず、配下にも潜らない（prune）。

    Yields
    ------
    pathlib.Path
        列挙された各ディレクトリ（root 自身は含まない）。

    Notes
    -----
    - os.walk(topdown=True, followlinks=False) を使用。
    - dirs[:] への代入で子探索を in-place pruning。
    - シンボリックリンクは追跡しない。

    ---- Usage (for AI/LLM) -----------------------------------
    • 「深さ1の候補一覧」など、階層限定のフォルダ列挙に最適。
    • name フィルタは呼び出し側で実施（関数は純粋列挙に徹する）。
    • 例:
        >>> list(iter_dirs(Path("/tmp"), max_depth=1))  # doctest: +ELLIPSIS
        [...]
    -----------------------------------------------------------
    """
    if not root.exists():
        return
    for cur, dirs, files in os.walk(root, topdown=True, followlinks=False):
        cur_path = Path(cur)
        rel_parts = cur_path.relative_to(root).parts if cur_path != root else ()
        depth = 0 if cur_path == root else len(rel_parts)

        if ignore_hidden and rel_parts and is_hidden_rel(rel_parts):
            dirs[:] = []
            continue

        pruned = []
        for d in dirs:
            if ignore_hidden and d.startswith("."):
                continue
            child_rel_depth = (0 if cur_path == root else len(rel_parts)) + 1
            if child_rel_depth <= max_depth:
                pruned.append(d)
        dirs[:] = pruned

        if cur_path != root and 1 <= depth <= max_depth:
            yield cur_path


def ext_key(path: Path) -> str:
    """
    拡張子を「ドット付き・小文字」で返す。拡張子なしは '<none>'。

    Parameters
    ----------
    path : pathlib.Path

    Returns
    -------
    str
        例: '.pdf', '.txt', '<none>' など。

    Notes
    -----
    - 集計やフィルタのキーとして安定的に扱うための正規化ヘルパ。
    - 空拡張子の区別が必要な UI のため '<none>' を採用。

    ---- Usage (for AI/LLM) -----------------------------------
    • filetype 集計や拡張子フィルタの前処理として使用。
    • 例:
        >>> from pathlib import Path
        >>> ext_key(Path("Report.PDF"))
        '.pdf'
        >>> ext_key(Path("README"))
        '<none>'
    -----------------------------------------------------------
    """
    s = path.suffix.lower()
    return s if s else "<none>"


# -------- 上位ユーティリティ：ページの主処理を関数化 --------

def walk_tree_collect(
    base_root: Path,
    *,
    max_depth: int,
    ignore_hidden: bool = True,
    name_filter: str = "",
    compute_counts: bool = False,
    max_rows_total: int = 10_000,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int], int, int]:
    """
    ディレクトリ/ファイルを走査し、ページ表示に必要な構造を一括生成する。
    ・深さ制御、隠しフォルダ pruning、名前の部分一致フィルタ、
      早期停止（合計行数上限）、拡張子集計を一度に行う上位 API。

    Parameters
    ----------
    base_root : pathlib.Path
        探索の基点（ROOT または SUBROOT）。
    max_depth : int
        最大深さ（>=1）。
    ignore_hidden : bool, default True
        '.' 始まりの隠しフォルダを探索対象から除外。
    name_filter : str, default ""
        フォルダ名・ファイル名の部分一致フィルタ（case-insensitive）。
    compute_counts : bool, default False
        True の場合、各フォルダの直下件数（files/dirs, 非再帰）を計算。
    max_rows_total : int, default 10000
        フォルダ+ファイル出力の総上限（到達で早期停止）。

    Returns
    -------
    rows_dirs : list[dict]
        各要素は以下のキーを持つ辞書:
        - kind: 'dir'
        - path: base_root からの相対パス（str）
        - name: フォルダ名（str）
        - depth: 階層の深さ（int）
        - parent: 親の相対パス（str, ルート直下は ""）
        - modified: datetime | None（mtime が 0.0 の場合は None）
        - files_direct: int | None（compute_counts=True のときに直下 files）
        - dirs_direct: int | None（compute_counts=True のときに直下 dirs）
    rows_files : list[dict]
        各要素は以下のキーを持つ辞書:
        - kind: 'file'
        - path: base_root からの相対パス（str）
        - name: ファイル名（str）
        - depth: 親フォルダの深さ（int）
        - parent: 親の相対パス（str, ルート直下は ""）
        - modified: datetime | None
        - size_bytes: int | None（存在確認のうえ取得）
        - ext: 正規化拡張子（'.pdf' など。無しは '<none>'）
    filetype_counts : dict[str, int]
        拡張子（ext_key）→ 件数（int）の集計結果。
    total_rows : int
        生成した rows_dirs + rows_files の件数合計（早期停止により上限で打ち切り得る）。
    max_depth_found : int
        実際に見つかった最大深さ（dir/file のうち最大）。

    Notes
    -----
    - os.walk(topdown=True, followlinks=False) を使用。symlink は追跡しない。
    - 隠しフォルダ配下の探索を完全に切ることで負荷を抑制。
    - name_filter はフォルダ名・ファイル名の双方に適用。

    ---- Usage (for AI/LLM) -----------------------------------
    • 典型フロー（UI 側）:
        rows_dirs, rows_files, counts, total, maxd = walk_tree_collect(
            base_root=Path("/data/docs"),
            max_depth=3,
            ignore_hidden=True,
            name_filter="report",    # 空文字なら無条件
            compute_counts=False,    # I/O コストを抑えたい時は False
            max_rows_total=50_000,   # 早期停止の上限
        )
        # → pandas.DataFrame(rows_files) で表にして CSV 保存など

    • LLM プロンプトでの指示例:
        - 「深さは 2、隠しフォルダを除外、'pdf' を名前に含む要素のみ列挙し、
           合計 5000 行までで打ち切るように関数を呼んでください。」
        - 「拡張子別件数を counts から降順で上位 5 件、'.pdf' が何件か報告してください。」

    • エラー/制約の扱い:
        - 権限や一時 I/O の例外は握りつぶす設計。
        - max_rows_total 到達時は探索ループを break して早期停止。
        - compute_counts=True は I/O が増えるため必要時のみ推奨。
    -----------------------------------------------------------
    """
    name_q = (name_filter or "").lower()
    rows_dirs: List[Dict[str, Any]] = []
    rows_files: List[Dict[str, Any]] = []
    filetype_counts: Dict[str, int] = {}
    total_rows = 0
    max_depth_found = 0

    for cur, dirs, files in os.walk(base_root, topdown=True, followlinks=False):
        cur_path = Path(cur)
        rel_parts = cur_path.relative_to(base_root).parts if cur_path != base_root else ()
        depth = 0 if cur_path == base_root else len(rel_parts)

        # prune hidden subtree
        if ignore_hidden and rel_parts and any(p.startswith(".") for p in rel_parts):
            dirs[:] = []
            continue

        # prune by depth + hidden child
        pruned = []
        for d in dirs:
            if ignore_hidden and d.startswith("."):
                continue
            child_depth = (0 if cur_path == base_root else len(rel_parts)) + 1
            if child_depth <= max_depth:
                pruned.append(d)
        dirs[:] = pruned

        # dir row (exclude base_root)
        if cur_path != base_root and 1 <= depth <= max_depth:
            name = cur_path.name
            if (not name_q) or (name_q in name.lower()):
                mtime = safe_stat_mtime(cur_path)
                files_cnt, dirs_cnt = listdir_counts(cur_path) if compute_counts else (None, None)
                rows_dirs.append(
                    {
                        "kind": "dir",
                        "path": str(cur_path.relative_to(base_root)),
                        "name": name,
                        "depth": depth,
                        "parent": "" if cur_path.parent == base_root else str(cur_path.parent.relative_to(base_root)),
                        "modified": dt.datetime.fromtimestamp(mtime) if mtime else None,
                        "files_direct": files_cnt,
                        "dirs_direct": dirs_cnt,
                    }
                )
                total_rows += 1
                max_depth_found = max(max_depth_found, depth)
                if total_rows >= max_rows_total:
                    break

        # file rows
        for fname in files:
            if ignore_hidden and fname.startswith("."):
                continue
            if name_q and (name_q not in fname.lower()):
                continue
            fpath = cur_path / fname
            mtime = safe_stat_mtime(fpath)
            ex = ext_key(fpath)
            filetype_counts[ex] = filetype_counts.get(ex, 0) + 1
            rows_files.append(
                {
                    "kind": "file",
                    "path": str(fpath.relative_to(base_root)),
                    "name": fname,
                    "depth": depth,
                    "parent": "" if cur_path == base_root else str(cur_path.relative_to(base_root)),
                    "modified": dt.datetime.fromtimestamp(mtime) if mtime else None,
                    "size_bytes": fpath.stat().st_size if fpath.exists() else None,
                    "ext": ex,
                }
            )
            total_rows += 1
            max_depth_found = max(max_depth_found, depth)
            if total_rows >= max_rows_total:
                break

        if total_rows >= max_rows_total:
            break

    return rows_dirs, rows_files, filetype_counts, total_rows, max_depth_found
