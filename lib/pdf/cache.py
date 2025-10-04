"""
cache.py
=================================
Streamlit の `st.cache_data` が利用可能な場合はそれを返し、
ない場合は no-op（何もしない）デコレータを返す小さなヘルパです。

目的
----
- UI 依存をライブラリ層から排除し、headless / batch 実行を可能にする。

使い方
------
    from lib.pdf.cache import cache_data

    @cache_data()(show_spinner=False)
    def heavy_func(...):
        ...

仕組み
------
- `cache_data()` は「関数」を返す“ファクトリ”です。
- Streamlit 環境では `st.cache_data` をそのまま返す。
- それ以外の環境では「何もしないデコレータ（no-op）」を返す。

公開関数一覧
------------
- cache_data() -> Callable  
    Streamlit 環境では `st.cache_data`、それ以外では no-op デコレータを返す。
"""


from __future__ import annotations


def cache_data():
    """`st.cache_data` 互換デコレータを返すファクトリ。

    Returns
    -------
    Callable
        Streamlit 環境では `st.cache_data`、それ以外では no-op デコレータ。
    """
    try:
        import streamlit as st  # type: ignore
        return st.cache_data
    except Exception:
        def _decorator(*args, **kwargs):
            def _wrap(func):
                return func  # 何もしない
            return _wrap
        return _decorator
