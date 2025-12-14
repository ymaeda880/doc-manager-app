# -*- coding: utf-8 -*-
# lib/pdf_organization/explanation.py
#
# PDF整理（処理判定）アプリのロジックと使い方をまとめた expander 群

from __future__ import annotations
import streamlit as st


def render_pdf_organization_expander() -> None:
    '''
    PDF整理（処理判定）アプリのロジックと使い方を説明する expander を描画します。
    '''
    with st.expander('ℹ️ PDF整理（処理判定）アプリのロジックと使い方（クリックで展開）', expanded=False):
        st.markdown(
            '''
🧩 **PDF整理（処理判定）— 画像PDFに sidecar JSON を付与して OCR フローを管理**

このアプリは `organized_docs_root/report/pdf` 配下の PDF を対象に，

- 上位フォルダ（例：年フォルダ）を選択して処理対象の範囲を決め，
- `quick_pdf_info` を用いて **画像PDFかどうか** を判定し，
- 画像PDFに対して `<basename>_side.json`（sidecar）を自動生成し，
- sidecar の `"ocr"` を  
  - `unprocessed`（未処理）  
  - `done`（`*_ocr.pdf` が存在）  
  - `text`（画像と判定されたが実際にはテキストPDFだった）  
  - `skipped`（図面等で OCR / ベクトル化の対象外とする）  
  の 4 種で管理し，
- `ocr = "unprocessed"` の PDF を一覧し，テキスト抽出または目視確認により `"text"` または `"skipped"` に更新する，

という **PDF の分類〜OCR 対象の選別〜プレビュー** のワークフローを統合的に扱うユーティリティです。  
ここで設定された `ocr` ステータスは，後段の **OCR 処理タブ** や **PDF ベクトル化アプリ** から参照されます。

---

## 1. 上位フォルダ選択（organized/report/pdf 下の第1階層）

- `list_dirs(pdf_root)` により，`organized_docs_root/report/pdf` 直下の **第1階層フォルダ（例：年）** を列挙します。
- 画面上には複数列のチェックボックスとして表示されます。
- ユーザーがチェックしたフォルダ名は `st.session_state.sel_top`（`set[str]`）に保持され，  
  以後の処理（sidecar 生成，unprocessed 一覧，ビューアなど）の **対象範囲** になります。
- フォルダが 1 つも見つからない場合は「上位フォルダが見つかりません」と表示して処理を停止します。

---

## 2. sidecar（_side.json）の作成ロジック

### 2-1. quick_pdf_info による画像PDF判定

- 各 PDF について `quick_pdf_info(path, mtime_ns)` を呼び出し，戻り値の `dict` から `"kind"` を参照します。
- `"kind" == "画像PDF"` の場合のみ，**画像PDF** とみなして sidecar 付与の対象にします。
- `"kind"` がその他（テキストPDFなど）の場合は，「テキストPDF/その他のため対象外」としてスキップします。

### 2-2. sidecar JSON の仕様

sidecar のファイル名と JSON 構造は以下の通りです。

- ファイル名：`<basename>_side.json`  
  例：`report_001.pdf` → `report_001_side.json`
- JSON 構造：
  ```json
  {
    "type": "image_pdf",
    "created_at": "2025-10-07T08:42:00+00:00",
    "ocr": "unprocessed"
  }
  ```

- `"type"` は常に `"image_pdf"` です。
- `"created_at"` には sidecar を生成した日時を **ISO8601 形式の文字列**（UTC 固定）で記録します。
- `"ocr"` には OCR 状態を表すステータスを格納します。後述するように，  
  初期値は `"unprocessed"` または `"done"`，その後 `"text"` / `"skipped"` へ更新されます。

### 2-3. 初期状態の `"ocr"` 判定ルール

`write_sidecar_if_needed(pdf_path, ocr_state)` を呼ぶ前に，次のように `ocr_state` を決めます。

- ファイル名が `*_ocr.pdf` である場合：  
  - その PDF 自身が「OCR 済み PDF」とみなされるため，`ocr_state = "done"` とします。
- ファイル名が `*_ocr.pdf` でない場合：  
  - `dest_ocr_path(pdf)` により「対応する OCR 版（`*_ocr.pdf`）」のパスを推定し，  
    それが存在する場合は `"done"`，存在しない場合は `"unprocessed"` とします。

`write_sidecar_if_needed` では，

- `"kind" != "画像PDF"` → 何もせず終了  
- `<basename>_side.json` 既存 かつ `force=False` → 上書きせず「既存のためスキップ」  
- それ以外 → 上記の JSON 構造で sidecar を新規作成  

という動作を行います。

---

## 3. 「▶ 処理を始める」ボタンの実行内容

画面中央にある「▶️ 処理を始める」ボタンを押すと，次の処理が実行されます。

1. **対象 PDF の収集**
   - `st.session_state.sel_top` に入っている上位フォルダ（例：年）ごとに，
     - その直下のサブフォルダを `list_dirs` で列挙し，
     - 各サブフォルダ配下の PDF を `list_pdfs` で集めます。
   - ファイル名が `*_skip.pdf` のものは `is_skip_name(p)` により除外されます（後述）。
   - こうして集めた PDF を `targets` リストに格納します。

2. **画像PDF判定と sidecar 生成**
   - `targets` を順に処理し，先述のルールに従って
     - 画像PDFかどうかを判定し，
     - sidecar が存在しない場合に限り，新規作成します。
   - プログレスバーで進捗（`i+1 / total`）を表示します。

3. **結果のサマリ表示**
   - ドライラン（`dry_run = True`）の場合  
     → 実際にはファイルを書き込まず，作成予定の `<pdf> → <side.json> (ocr=...)` をリスト表示します。
   - 通常モード（`dry_run = False`）の場合  
     → 新規に作成できた sidecar の一覧を表示します。
   - 併せて，
     - 「作成対象（または作成済）」件数
     - 「エラー」件数  
     を `st.metric` で表示します。

---

## 4. ocr = "unprocessed" 一覧と管理（text／skipped の付け替え）

### 4-1. unprocessed の抽出

`③ ocr=unprocessed のPDFを表示し、skip設定` セクションでは，

- まず `st.session_state.sel_top` で選ばれた上位フォルダ配下の PDF を再度走査し，
- 各 PDF に対して `get_sidecar_state(pdf)` を呼び，
- `ocr == "unprocessed"` のものだけを `unprocessed_pdfs` に集約します。

`get_sidecar_state(pdf)` は，

- `<basename>_side.json` が無い場合 → `None`
- JSON の読み込みに失敗した場合 → `None`
- 正常に読み込めた場合 → `data["ocr"]`（例：`"unprocessed"`）

という動作をします。  
`None` の場合は **このセクションの対象外** です（先に ② の sidecar 生成を実行してください）。

### 4-2. チェックリストとページ数表示

`unprocessed_pdfs` が 1 件以上ある場合，

- 各 PDF に対して `get_page_count(p)` を呼び，ページ数を取得します（`quick_pdf_info` のラッパ）。
- ラベルは `相対パス（NNp）` の形式で表示されます。
- ユーザーがチェックした PDF は `to_act` リストに格納され，後続の  
  - テキスト抽出  
  - `text` 更新  
  - `skipped` 更新  
  - プレビュー表示  
  の対象となります。

### 4-3. テキスト抽出（sample）による「実はテキストPDF」の判定

「📝 チェックしたものからテキスト抽出」ボタンを押すと，

- スライダーで指定した先頭 N ページ（1〜20）について `analyze_pdf_texts` を実行します。
- 戻り値の `info["pages"]` には，
  - `{"page": ページ番号, "text": 抽出テキスト}`  
    の配列が入っている想定です。
- 各 PDF ごとに `expander` を開き，
  - ページ番号ごとにテキスト冒頭（最大 1000 文字）を表示します。
  - テキストが十分に抽出できている場合，「画像PDFとして認識されているが実態はテキストPDF」の可能性が高いと判断できます。

抽出に失敗した場合は，  
「抽出に失敗しました: ...」というメッセージをその PDF 用 expander 内に表示します。

### 4-4. text への更新（テキストPDFと確定）

「✅ チェックしたものをテキストPDFと判定（ocr = 'text' に更新）」ボタンを押すと，

- `to_act` に入っている PDF について，
  - `update_sidecar_state(pdf, "text")` を呼び出し，
  - sidecar の `"ocr"` を `"text"` に更新します。
- `"text"` に更新された PDF は，
  - 今後の OCR バッチ処理では **対象外**（OCR しない）となり，
  - ベクトル化処理では **テキストPDFとして直接テキスト抽出** されます。
- 成功した件数をカウントし，「X 件の side.json を 'text' に更新しました。」と表示します。

### 4-5. skipped への更新（OCR・ベクトル化対象から除外）

図面や票，印影中心の書類など，**OCRやベクトル化のコスパが悪い PDF** については，

- 「💾 チェックしたものを skipped に更新（図面や発注書などの画像データ）（ocrやベクトル化から除く）」ボタンで，
  - `update_sidecar_state(pdf, "skipped")` を実行し，
  - sidecar の `"ocr"` を `"skipped"` に更新します。
- `"skipped"` に更新された PDF は，
  - 以後，OCR 処理・ベクトル化処理の **両方から除外** する前提で扱われます。

---

## 5. PDFプレビュー（👁）とダウンロード

「👁 チェックしたものを表示」ボタンは，チェック対象の PDF を **同時プレビュー** するための機能です。

- ボタン押下時，`to_act` の中身を文字列パスリストとして `st.session_state._checked_to_show` に保存します。
- 以降のリランでも，このセッション変数を参照して表示対象を復元します。
- プレビューセクションでは：
  - 最大表示件数 `MAX_VIEW = 12` を上限として，PDF をグリッド状に並べて表示します。
  - グリッド列数（1〜4）と表示高さはスライダーで調整できます。
  - 각 PDF について `read_pdf_bytes` でバイト列を取得し，`st.pdf` で埋め込み表示します。
  - 併せて `st.download_button` を設置し，「📥 このPDFをダウンロード」からローカル保存できます。
- 「🧹 表示をクリア」ボタンを押すと，
  - `st.session_state._checked_to_show` を空にし，
  - `st.rerun()`（または古いバージョンでは `st.experimental_rerun()`）で画面を再読込します。

---

## 6. sidecar／OCRワークフローの推奨運用

このアプリは，「どの PDF を OCR するか／しないか」を **事前に人間が整理するためのハブ** として位置付けられています。  
典型的な運用フローは次のようになります。

1. **sidecar 生成フェーズ**
   - ② の「処理を始める」で画像PDFに対して sidecar を一括生成します。
   - `_ocr.pdf` が存在するものは初期状態で `"done"` とマークされます。

2. **unprocessed の仕分けフェーズ**
   - ③ の一覧から `ocr = "unprocessed"` の PDF を確認し，
   - まず「📝 テキスト抽出」でテキストPDFの可能性をチェックします。
   - テキストが十分に抽出できるものは `"text"` に更新します。
   - 図面・票・印影・スキャン写真中心などは `"skipped"` に更新します。
   - 判定を保留したいものは `"unprocessed"` のまま残し，後日再確認します。

3. **後段アプリへの引き継ぎ**
   - OCR 専用タブや PDF ベクトル化アプリでは，
     - `"unprocessed"` / `"done"` のみを OCR 対象とする，
     - `"text"` のものはテキストPDFとして直接抽出する，
     - `"skipped"` は完全に除外する，  
     といったポリシーで処理を分岐させることができます。

このように，**sidecar の `"ocr"` 値を使って OCR コストとデータ品質のバランスを人手でコントロールする**のがこのアプリの役割です。

---

## 7. 例外処理・安全性に関する考え方

- sidecar 未存在  
  - `get_sidecar_state` は `None` を返し，③セクションの対象には入りません。  
  - その場合は，まず ② の sidecar 生成を実行することが前提です。
- JSON 読み込み失敗  
  - 読み込み例外は握り潰し，`None` として扱います（対象外）。  
  - 壊れた JSON によって画面全体が落ちないようにしています。
- sidecar 更新失敗  
  - `update_sidecar_state` 内で `st.error` により，
    - ファイル名
    - 例外メッセージ  
    を表示しつつ `False` を返します。
- テキスト抽出失敗  
  - 個別の PDF について，テキスト抽出 expander 内に
    - 「抽出に失敗しました: ...」
    を表示します。他の PDF の処理は継続されます。
- 権限不足・ロック  
  - `sidecar` 書き込み時に OS からエラーが返された場合，`st.error` で通知します。
- PDF 表示エラー  
  - `read_pdf_bytes` や `st.pdf` 周辺で例外が発生した場合も，
    - 「<ファイル名> の表示に失敗しました: ...」
    として個別にエラー表示し，全体の処理は継続します。

---

## 8. パフォーマンス対策

このアプリでは，以下のような工夫でパフォーマンスを確保しています。

- `quick_pdf_info` と `get_page_count`  
  - `@st.cache_data` を付けており，
    - ファイルパス
    - 最終更新時刻  
    をキーに結果をキャッシュします。
  - 同じ PDF を何度もスキャンする場合でも，I/O 負荷を抑えることができます。
- プレビュー件数の上限  
  - 同時プレビューの上限を `MAX_VIEW = 12` とし，  
    それ以上の件数が選ばれたときは「先頭 12 件のみ表示」としています。
- チェックボックス key の設計  
  - `chk_<相対パス>` のように相対パスを含めて生成し，  
    同名ファイルが異なるフォルダにあっても key が衝突しないようにしています。

---

## 9. 特別なファイル名規則（*_skip.pdf／*_ocr.pdf／_side.json）

このアプリや関連アプリでは，ファイル名・拡張子に基づいた特別な意味付けを行っています。

- `*_skip.pdf`
  - `is_skip_name(p)` により検出される **スキップ専用 PDF** です。
  - 例：`sample_skip.pdf` → 「意図的に OCR / ベクトル化の対象から外したいファイル」。
  - sidecar 生成フェーズ（②）でも，`*_skip.pdf` は完全に対象外としています。
  - 既に明示的に「このファイルは処理しない」と決めたものを表す，強い除外フラグの位置づけです。
- `*_ocr.pdf`
  - OCR 後に作成されたテキストPDFを表す命名規則です。
  - 元の画像PDF `foo.pdf` に対して OCR 済みの `foo_ocr.pdf` が存在する場合，
    - `foo.pdf` の sidecar `"ocr"` は `"done"` とみなされます。
  - `foo_ocr.pdf` 自身についても，画像PDFであれば sidecar を作成し， `"ocr": "done"` をセットします。
- `<basename>_side.json`
  - 本アプリが生成する **sidecar JSON** です。
  - `"ocr"` フィールドによって OCR フロー全体の状態を管理し，  
    画像PDFの扱いを「未処理／OCR 済み／テキスト扱い／完全除外」に分類するためのメタデータとして機能します。

これらの命名規則により，**ファイル名だけでおおよその処理方針を判別できる** ようになっており，  
人手での整理作業と後続の自動処理（OCR・ベクトル化）の橋渡しをシンプルにしています。

---

以上が，**PDF整理（処理判定）アプリのロジックと使い方**の詳細な説明です。  
画像PDFの分類，OCR 対象の管理，sidecar の更新，テキスト抽出，プレビュー表示をひとつのアプリにまとめることで，  
後続の OCR・ベクトル化パイプラインに入る前の「整理・仕分け」作業を効率的に行えるように設計しています。
            '''
        )

