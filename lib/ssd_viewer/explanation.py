# -*- coding: utf-8 -*-
# lib/ssd_viewer/explanation.py
#
# Streamlit 各ツールのロジックと使い方をまとめた expander 群
# - SSD ビューア（pages/15_SSDビューア.py）用の説明などをここに集約する

from __future__ import annotations
import streamlit as st


def render_ssd_viewer_expander() -> None:
    """
    SSDビューア（pages/15_SSDビューア.py）のロジックと使い方の説明を expander で描画します。
    """
    with st.expander("ℹ️ SSDビューアのロジックと使い方（クリックで展開）", expanded=False):
        st.markdown(
            """
# 📂 SSDビューア（original と organized の PDF 集計・照合）

このツールは、外付け SSD 等に保存された **original 文書群** と  
それを整理・加工した **organized 側の PDF 群** の対応関係を、次の観点から確認するためのビューアです。

- 年代 → 年 → プロジェクト番号という階層で、original のフォルダ構造を閲覧する  
- 各プロジェクトについて、**同名ファイルを 1 回だけ数える** 形で拡張子別ファイル数を集計する  
- organized 側（`report/pdf`, `report_skip/pdf`）についても同様のルールで集計する  
- original 側の PDF 本数と、organized 側の PDF 本数（skip を含む）が一致しているかを自動チェックする  
- 特定の年・プロジェクト番号を指定して、1 件だけ詳細に original / organized を比較する  

---

## 1. 前提ディレクトリ構造とパス設定

このページでは、`lib.app_paths.PATHS` の設定を前提としています。

- `PATHS.original_docs_root`  
  - 例：`/Volumes/Extreme_SSD/original_docs`  
  - この下の `report/` 配下に、年次報告書などの原本フォルダが並びます。
- `PATHS.organized_docs_root`  
  - 例：`/Volumes/Extreme_SSD/organized_docs`  
  - この下に  
    - `report/pdf/<year>/<project>/`（通常解析対象）  
    - `report_skip/pdf/<year>/<project>/`（解析から除外したもの）  
    が置かれている想定です。

画面上部には、これらのパスが情報カードとして表示され、  
**今どの SSD / ルートを対象にしているか** が一目で分かるようになっています。

---

## 2. original/report のフォルダ名の解釈ロジック

`original_docs_root/report/` 直下のフォルダ名を解析し、  
年・プロジェクト番号ごとのマップを構成します（`scan_report_dirs` / `parse_folder_name`）。

### 📁 フォルダ名の分類

- `YYYYPPP`（7桁の数字）  
  - 例：`2015023` → year = 2015, project = 23  
  - 種別 `"year"` として扱い、`years_to_pnos[2015]` に `23` を追加。
- `HxxPPP`（平成表記）  
  - 例：`H07xxx` → 1988 + 7 = 1995 年として扱う。
- `SxxPPP`（昭和表記）  
  - 例：`S60xxx` → 1925 + 60 = 1985 年として扱う。
- `P...` で始まるもの  
  - 図書館用フォルダ（library）として `library_names` に格納。
- その他  
  - 命名規則に当てはまらないものは `"その他"` として `others` に格納。

この結果として得られるのが：

- `years_to_pnos: {year -> [project_no, ...]}`  
- `proj_dir_map: {(year, pno) -> Path("original/report/YYYYPPP")}`  
- `library_names, others`（図書館フォルダとその他フォルダ）

です。

---

## 3. 拡張子別のファイル数集計（★同名ファイルは 1 回だけ）

### 🔢 `count_unique_exts_recursive(dirpath: Path)`

- `dirpath` 以下を再帰的に `rglob("*")` で走査します。
- ファイル名（拡張子込み）を **小文字化した名前で一意集合 `seen_names` に登録** し、
  - すでに同じ名前が別フォルダで見つかっていれば「重複」と見なしてスキップします。
- その上で拡張子ごとのカウントを行います。
- 拡張子がない場合は `(noext)` として集計します。

これにより、

- 例：  
  - `foo/report.pdf`  
  - `foo/sub/report.pdf`  
  という 2 ファイルがあっても、**`report.pdf` として 1 件だけカウント**します。

### 📊 `build_df_from_pairs(pairs: list[tuple[str, Path]])`

- `pairs = [(プロジェクト表示名, プロジェクトフォルダ Path), ...]` を受け取り、
- 各フォルダに対して `count_unique_exts_recursive` を適用し、
- `project`, `total`, 各拡張子列を持つ DataFrame を構成します。
- 典型的に使用する拡張子（pdf, docx, xlsx, jpg, png…）は `PREFERRED_COLS` として  
  列順を優先的に揃え、それ以外は動的列として後ろに並べます。

---

## 4. PDF の種別別カウント（ocr/skip/side_json）

### 🔢 `count_pdf_categories(dirpath: Path)`

`organized` 側でも `original` 側でも共通で使える、  
**PDF 関連ファイルの分類カウント**関数です（ただし整合性チェックでは主に organized 側で使用）。

- 集計するキーは次の 4 種類です：
  - `"pdf"`       : 通常の `.pdf`（`*_ocr.pdf`・`*_skip.pdf` 以外の `.pdf`）  
  - `"skip_pdf"`  : `*_skip.pdf`  
  - `"ocr_pdf"`   : `*_ocr.pdf`（OCR 実行後の PDF）  
  - `"side_json"` : `*_side.json`（補助情報 JSON）

ここでも `seen_names` により **同名ファイルは 1 回だけカウント**します。

> 💡 整合性チェックでは現在、  
> - original 側：通常 `.pdf` 本数  
> - organized 側：`pdf + skip_pdf` の合計  
> を比較しています。`ocr_pdf` は別枠で個数を保持しており、  
> 必要に応じて将来的に整合性判定に組み込めるようにしてあります。

---

## 5. 年代 → 年 → プロジェクト UI

画面中央の UI は、まず **年代ラジオボタン → 年ラジオボタン** の 2 段階構造です。

### ⏱ 年代ラジオの選択肢

- 1970年代, 1980年代, …, 2020年代
- 図書館（`P...` フォルダ群）
- その他（命名規則に当てはまらないフォルダ）

`years_to_pnos` に実データが存在する最初の年代が、デフォルト選択になります。

### 📅 年ラジオ

年代を選ぶと、その年代に属する年（例：1983, 1984, …）の一覧を表示し、  
さらに **年ラジオ（"1983年" など）** から 1 年を選択します。

---

## 6. original 側の集計表示（拡張子別テーブル）

選択された年 `chosen_year` について、

- `years_to_pnos[chosen_year]` に含まれるプロジェクト番号から
- `proj_dir_map[(chosen_year, pno)]` で `original/report/YYYYPPP` の Path を取得し、
- それらを `build_df_from_pairs` に渡して DataFrame を作成します。

画面には：

- プロジェクト番号（001, 002, …）ごとに  
- total（同名除外後の総ファイル数）と拡張子別カウント

が表示され、CSV としてダウンロードすることもできます。

---

## 7. organized 側の集計表示（report/pdf, report_skip/pdf）

`render_organized_year_section` により、organized 側の

- `report/pdf/<year>/<project>/`
- `report_skip/pdf/<year>/<project>/`

を original 側と同じルール（同名除外）で拡張子別に集計して表示します。

- `report_skip/pdf` 側は  
  「分析から除外しているプロジェクト」という注記を付けて表示します。
- 各テーブルも CSV ダウンロードが可能です。

---

## 8. 年内プロジェクトの整合性チェック（original vs organized）

### 🎯 目的

同じ年の中で、各プロジェクトについて

> original の `.pdf` 本数  
> vs  
> organized 側（`report/pdf` + `report_skip/pdf`）の `.pdf` + `*_skip.pdf` 本数

が一致しているかどうかを自動判定します。

### 📌 チェック対象プロジェクト集合の作り方

- `projects_original`  
  - `years_to_pnos[chosen_year]` から得られるプロジェクト番号集合。
- `projects_org_report`  
  - `organized/report/pdf/<year>/` に存在するプロジェクトフォルダ名集合。
- `projects_org_report_skip`  
  - `organized/report_skip/pdf/<year>/` に存在するプロジェクトフォルダ名集合。

これらを和集合にして、**年内に登場するあらゆるプロジェクトをチェック対象**とします。

### 🧮 original 側のカウント

- `proj_dir_map[(chosen_year, int(proj))]` から `original/report/YYYYPPP` を取得。
- その配下の `.pdf` を再帰的に走査し、ファイル名ベースで同名除外してカウント。

### 🧮 organized 側のカウント

各プロジェクト `proj` について：

- `organized/report/pdf/<year>/<proj>` に対して `count_pdf_categories` を実行し、
  - `"pdf"` と `"skip_pdf"` を合計 → `org_report_sum`
- `organized/report_skip/pdf/<year>/<proj>` に対しても同様に  
  `"pdf"` と `"skip_pdf"` の合計 → `org_report_skip_sum`
- 最後に  
  `organized_count = org_report_sum + org_report_skip_sum` として **organized 側の総数** とみなします。

### ✅／⚠️ 一致判定

- `original_count == organized_count` なら `"✅一致"`
- 異なれば `"⚠️不一致"`

というフラグを立て、次の列を持つ DataFrame として表示します。

- チェック結果（✅ / ⚠️）
- プロジェクト番号
- original総数
- organized(report)
- organized(report_skip)
- organized総数

⚠️ 不一致プロジェクトが 1 件でもあれば、画面上部に警告メッセージも表示されます。

---

## 9. 年・プロジェクト番号を指定した個別確認

画面下部の「🧮 個別プロジェクト確認」では、  
ユーザーが任意の

- 年（例：2015）
- プロジェクト番号（例：123）

を入力して「集計」ボタンを押すことで、その 1 件だけを詳細に比較できます。

1. original 側  
   - `original/report/YYYYPPP` に対して `count_pdf_categories` を適用し、  
     `"pdf"` のみを original 総数とする。
2. organized 側  
   - `organized/report/pdf/<year>/<proj>`  
   - `organized/report_skip/pdf/<year>/<proj>`  
   に対して `count_pdf_categories` を適用し、`pdf + skip_pdf` の合計を organized 総数とする。
3. その結果を 1 行だけの DataFrame として表示し、
   - 一致していれば ✅ メッセージ
   - 不一致であれば ⚠️ メッセージ

を表示します。

---

## 10. このツールの使いどころ

- original の PDF 群と、整理済み organized ディレクトリが **本当に 1:1 で対応しているか** のチェック
- 特定の年やプロジェクトだけ整理漏れ・重複・skip の扱いがおかしくなっていないかの確認
- 大規模な文書整理・ベクトル化パイプラインの「入り口・出口」の整合性確認

などに活用できます。

---

## 11. original 側で PDF 数が想定より多くなる理由（`._◯◯.pdf` の存在）

macOS では、外付け SSD（exFAT / FAT32 / NTFS など）にファイルを書き込む際に、  
AppleDouble（`._◯◯`）と呼ばれる **隠しメタデータファイル** が自動生成されることがあります。

例として、あるプロジェクトフォルダ内に次のようなファイルが存在している場合を考えます。

- `2019009/PDF/いずみ墓園2019委託業務報告書.pdf`  
- `2019009/PDF/いずみ墓園第8回事後調査報告書_公開版.pdf`  
- `2019009/PDF/いずみ墓園第8回事後調査報告書_非公開版.pdf`  
- `2019009/PDF/._いずみ墓園2019委託業務報告書.pdf`  
- `2019009/PDF/._いずみ墓園第8回事後調査報告書_非公開版.pdf`  

このうち **先頭 3 つが本物の PDF** であり、  
後ろ 2 つの `._〜.pdf` は Finder 情報や拡張属性を保存するための  
**AppleDouble（隠しメタデータファイル）** であって、PDF コンテンツそのものではありません。

しかし現在の整合性チェックでは、

- 拡張子が `.pdf` であれば PDF とみなしてカウントしているため、
- `._〜.pdf` も誤って PDF としてカウントされ、  

結果として

- 本物 PDF：3 個  
- AppleDouble（偽 PDF）：2 個  
- → original総数 = 5  

のように、**目視の感覚（3 個）より多い数字** が表示されることがあります。

### 💡 対策（コード側）

original 側の PDF を数える処理に、次の条件を追加することで AppleDouble を除外できます。

```python
if f.name.startswith("._"):
    continue
これにより ._〜.pdf はカウント対象から外れ、
original の PDF 本数が 実際の「本物 PDF」の数 に一致するようになります。

"""
)