# -*- coding: utf-8 -*-
# lib/report_organizer/explanation.py
#
# Streamlit 各ツールのロジックと使い方をまとめた expander 群
# - report 整理（pages/20_report整理.py）や SSD ビューア関連の説明をここに集約する

from __future__ import annotations
import streamlit as st


def render_report_organizer_expander() -> None:
    """
    report 整理（pages/20_report整理.py）のロジックと使い方を説明する expander を描画します。
    """
    with st.expander("ℹ️ report 整理ページのロジックと使い方（クリックで展開）", expanded=False):
        st.markdown(
            """
# 📂 report 整理 — original_docs_root/report 配下の一覧とコピー

このページは、外付け SSD 等に保存された **original_docs_root/report** を起点に、

1. report 直下のフォルダ構造を把握し  
2. フォルダ名から「年／プロジェクト番号」を整理・分類し  
3. Library(P) フォルダについては図書管理DBから年を補足し  
4. 選択した「年」の PDF を `<organized_docs_root>/report/pdf/<年>/<pno>/` にコピーし  
5. 別セクション（①.6）で、コピー結果と original の PDF を「ファイル名・容量ベース」で比較する  

という一連の作業を行うための **整理＋コピー＋比較ツール** です。

---

## 0. ルートパスと概要メッセージ

- `PATHS.original_docs_root` と `PATHS.organized_docs_root` を取得し、  
  それぞれの実パスを画面上部に表示します。
- ここで示されるのは、たとえば次のようなディレクトリです。  
  - original: `/Volumes/ExtremeSSD/original_docs`  
  - organized: `/Volumes/ExtremeSSD/organized_docs`
- 下の案内文では、original を「元本ファイル」、organized を「作業ファイル」として説明しています。

---

## 1. report 直下のフォルダ一覧（①）

### 1-1. サイドバーの設定

サイドバーでは次のオプションを指定できます。

- `隠しフォルダを除外`  
  - ON の場合、フォルダ名が `.` で始まるものを一覧から除外します。
- `直下の件数を計算`  
  - ON の場合、各フォルダ直下にある **ファイル数／サブフォルダ数** を数えます。
- 名称フィルタ（部分一致、ケース無視）  
  - 指定した文字列を含むフォルダだけを対象にします。
- `プロジェクト内の再帰集計を計算する`（①.5 で利用）  
  - ON にすると、各フォルダ配下の全ファイルを再帰走査して拡張子別の件数と容量を計算します。

### 1-2. 深さ1フォルダ一覧（report 直下）

- `iter_dirs(REPORT_ROOT, max_depth=1, ignore_hidden=...)` により、  
  `original_docs_root/report` 直下のフォルダのみを列挙します。
- 各フォルダについて、次の情報を DataFrame にまとめて表示します。
  - `path`（report からの相対パス）
  - `name`（フォルダ名）
  - `modified`（更新日時）
  - `files_direct`／`dirs_direct`（直下のファイル数／サブフォルダ数、必要に応じて計算）

---

## 2. 年／プロジェクト別の拡張子・容量集計（①.5）

### 2-1. フォルダ名の解釈 `_parse_folder_name`

各フォルダ名を以下の規則で解析し、`year` と `pno` を付与します。

- `YYYYPPP`（7桁数字）  
  - 例：`2019003` → year=2019, pno=3
- `HNNPPP`（平成）  
  - 西暦は `1988 + NN`
- `SNNPPP`（昭和）  
  - 西暦は `1925 + NN`
- `P...`  
  - 図書館管理として `year=9999, pno=999`
- 上記以外は `other` として `year=None, pno=None`

このうち **numeric7 / Heisei / Showa** を「プロジェクト」として扱い、  
後続の集計やコピー・比較の対象にします。

### 2-2. 再帰走査による拡張子別集計 `_ext_stats_recursive_cached`

- 各プロジェクトフォルダに対して、`os.walk` で **再帰的に全ファイル** を走査し、
  - 拡張子ごとの件数（`count`）
  - 拡張子ごとの総バイト数（`bytes`）
  - ディレクトリ全体のファイル数・総容量
  を集計します。
- 関数には `@st.cache_data` を付けており、
  - パス (`path_str`)
  - 最終更新時刻 (`mtime`)
  - `ignore_hidden` フラグ
  をキーにキャッシュすることで、繰り返し実行を高速化しています。
- `TARGET_EXTS = ["pdf","docx","pptx","xlsx","csv","txt","jpg","jpeg","png"]` を代表拡張子として、
  各 ext ごとに `件数` と `サイズ表記`（KB/MB/GB など）が列として並びます。

### 2-3. DataFrame 表示

- 列の基本構成は次の通りです。  
  - `year`, `pno`, `files_total`, `size_total`  
  - `pdf`, `pdf_size`, `docx`, `docx_size`, ...  
  - `other`, `other_size`（TARGET_EXTS 以外の合算）  
  - `folder`（元のフォルダ名）  
  - `relpath`（report からの相対パス）
- これにより、「どの年・どのプロジェクトに、どの拡張子がどれだけあるか」を一望できます。

---

## 3. organized 配下との PDF 比較（①.6）

このセクションでは、①.5 の結果を **organized_docs_root/report/pdf** 配下の PDF と比較します。

### 3-1. 比較対象のベースパス

- コピー・比較のベースとなるパスは  
  `DEST_BASE_16 = organized_docs_root / "report" / "pdf"` として扱います。
- 画面には「比較対象の organized ベース」として表示されます。

### 3-2. original 側の「PDF基準集合」を構成

- ②で使った `parsed_for_grid`（numeric7/Heisei/Showa）を元に、  
  year/pno ごとのバケット `(year, pno)` を作り、
- 各プロジェクトフォルダ配下を `_walk_pdfs_under` で再帰的に走査して
  - `src["names"]`（PDF ファイル名の集合）
  - `src["bytes"]`（合計バイト数）
  を収集します。
- `_walk_pdfs_under` では
  - 隠しファイル（先頭が `.` のファイル）を除外するため、  
    macOS が作成する `._◯◯.pdf` のような **AppleDouble ファイルは自動的に除外**されます。
  - さらに、`*_ocr.pdf` は比較対象から外しています（organized 側との比較時にノイズとならないようにするため）。

### 3-3. organized 側の格納先判定 `_resolve_dest_bucket`

organized 側の PDF は、プロジェクトごとに以下のどちらかの構成をとっている前提です。

1. `DEST_BASE_16/<year>/<pno:03d>/`  
2. `DEST_BASE_16/<pno:03d>/`（pno 直下構成）

`_resolve_dest_bucket` は、上記の順に存在を確認し、最初に見つかった方を「格納先」とみなします。  
どちらも存在しない場合は `None` を返し、そのプロジェクトは「organized に存在しない」と判断されます。

### 3-4. year/pno ごとの比較

1. original 側の名前集合・総容量と、organized 側の集合・総容量を比較し、
2. 次の情報を `rows_cmp` に蓄積します。
   - `src_count`, `src_size`, `src_bytes`  
   - `dst_count`, `dst_size`, `dst_bytes`  
   - `missing_list`（original にあるが organized に無い）  
   - `extra_list`（organized にあるが original に無い）  
   - `match` フラグ（件数・容量・差分がすべて一致しているか）
3. `missing_list`／`extra_list` の要素数は、それぞれ `missing_count`／`extra_count` として  
   年単位のサマリーにも利用されます。

### 3-5. 年別サマリーと詳細出力

- `df_year`  
  - year ごとに `src_count`／`dst_count`、総容量、差分件数などを集計し、  
    年単位で整合しているか（`match`）を表示します。
- 「年を指定して詳細を出力」欄で年を入力し「▶ 出力」を押すと、
  - その年に絞った year/pno ごとの比較表
  - 差分 PDF 一覧（1 ファイル 1 行）
  を表示します。
- 差分一覧は CSV でもダウンロードでき、  
  「どのファイルが足りない／余分か」を外部ツールで確認することができます。

---

## 4. フォルダ名 → 年／プロジェクト番号の分類（②）

このセクションでは、①で列挙したフォルダを

- `numeric7`（7桁数値）
- `Heisei`（平成）
- `Showa`（昭和）
- `Library(P)`
- `other`

に分類し、年ごとに表示します。

### 4-1. 年単位のチェックボックス

- 各年のヘッダ行にチェックボックスを用意し、  
  チェックした年を `st.session_state["selected_years_for_copy"]` に保存します。
- この **選択された年の集合** が、後述する ④ の「コピー対象年」となります。
- 9999年は Library(P) のプレースホルダとして扱われます（実際のコピー対象は 7桁数値フォルダのみ）。

---

## 5. Library(P) フォルダと図書管理DB（③）

### 5-1. 図書管理DBの読み込み

- `PATHS.library_root/図書管理DB.xlsx` の `Sheet1` を読み込み、
  - `登録番号`
  - `発行年`
  の列から、登録番号→発行年（4桁）の辞書 `regno_to_year` を作成します。
- 発行年の表記ゆれ（`1981/3`, `1977.2`, 全角数字など）は  
  `parse_year_field` によって正規化され、4桁年に変換できない場合は `9999` となります。

### 5-2. Library(P) フォルダ内の PDF 解析

- `category == "Library(P)"` のフォルダだけを対象に、
  その直下の PDF について
  - ファイル名先頭の「登録番号-…」部分から登録番号を抽出し、
  - 図書管理DB から発行年を取得します（無ければ `9999`）。
- pno には **登録番号の下3桁** を採用し、
  year/pno 付きのレコードとして `lib_parsed_rows` に保存します。

### 5-3. Library(P) の年単位チェック

- Library 補足結果も年ごとにまとめて表示し、  
  年ヘッダにチェックボックスを付けて  
  `st.session_state["selected_years_libdb"]` に選択状態を保持します。
- こちらは将来の処理用のフラグとして使えるよう設計されています（現行コードでは表示のみ）。

---

## 6. ②で選択した年の <年>/<pno>/ へ PDF コピー（④）

このセクションが **実際のコピー処理** です。

### 6-1. コピー先ベースの指定

- 入力欄「コピー先ベース」に  
  既定値として `organized_docs_root/report/pdf` を設定しています。
- ここで指定したパスを `DEST_BASE` とし、  
  コピー先は常に `DEST_BASE/<year>/<pno:03d>/` となります。

### 6-2. コピー対象の選定

- ②で選ばれた `picked_years` のうち、数値の年だけを対象とします。
- `parsed_rows`（①で分類したフォルダ一覧）から  
  - `year` が `picked_years` に含まれ、かつ  
  - フォルダ名が `^{year}\d{3}$` という 7桁数値（`YYYYPPP`）  
  のものだけをコピー対象とします。
- `pno` が取れない場合（理論上 numeric7 では起こらない）はスキップします。

### 6-3. コピー処理 `_iter_pdfs_under` と `shutil.copy2`

- `_iter_pdfs_under(src_dir)` で、ソースフォルダ配下の PDF を再帰列挙します。
  - ここでも `ignore_hidden=True` のため、`._◯◯.pdf` のような  
    AppleDouble は **コピー対象外** になります。
- 各 PDF について
  - コピー先フォルダ `DEST_BASE/<year>/<pno:03d>/` を `mkdir(parents=True, exist_ok=True)` で作成し、
  - もし同名ファイルがすでに存在すれば「skipped」としてカウントし、上書きはしません。
  - 存在しなければ `shutil.copy2` でコピーし、タイムスタンプも保持します。

### 6-4. 結果サマリ

- 全体の
  - `Copied (total)`  
  - `Skipped (total)`  
  - `Errors (total)`  
  を `st.metric` で表示し、
- 年/pno ごとの内訳は DataFrame（`year_pno`／`copied`／`skipped`／`errors`）として表示します。

---

## 7. 典型的な使い方の流れ

1. ページを開き、original／organized のルートパスが正しいことを確認する。
2. ① で report 直下のフォルダ一覧と拡張子別集計（①.5）を確認し、  
   どの年・プロジェクトを整理するかの目安をつかむ。
3. ② で対象年にチェックを入れる。
4. Library(P) に関連する資料があれば、③で図書管理DBの分類結果を確認する。
5. ④ でコピー先ベースを確認し、「📥 コピー実行」ボタンを押して PDF を organized 側へコピーする。
6. コピー後、①.6 の「比較」セクションで year/pno ごとの PDF を比較し、  
   original と organized の整合性（不足ファイルや余剰ファイルが無いか）をチェックする。

このようにして、**original（元本）から organized（作業用）への PDF 整理コピーと、その後の整合性チェック**を  
1 つのページで一通り行えるようにしたのが、`pages/20_report整理.py` です。
"""
        )
