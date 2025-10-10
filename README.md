brew install ocrmypdf tesseract

brew install ocrmypdf tesseract qpdf ghostscript pngquant

# use_container_width 引数が非推奨（deprecated） になり、2025 年末で削除予定

### 新しい書き方

- 代わりに width 引数 を使います。
- use_container_width=True → width="stretch"
- use_container_width=False → width="content"

### サイドカーファイル（sidecar file）

- サイドカーファイルは画像 PDF であることを示す
- サイドカーファイルの名前は「<basename>\_side.json」
- json の構造は，

```
 {
 "type": "image_pdf",
 "created_at": "2025-10-07T08:42:00+09:00",
 "ocr": “unprocessed"
 }
```

- "ocr"の内容は以下の６種類
- "ocr": “unprocessed"：未処理（ocr を行う必要がある）
- "ocr": “done"：処理済（正常）
- "ocr": "text"：画像 pdf と判断されるが，テキスト pdf である場合につける．ocr 処理で無視される．ベクトル化には使用される．
- "ocr": "skipped"：ocr 処理およびベクトルかを行わない pdf ファイルを示す（図面，見積書などベクトル化する意味が無いファイル）
- "ocr": "failed"：ocr を行った時に，ocr 失敗したファイル示す．ベクトル化から外す．
- "ocr": "locked"：ロックがかかっている pdf ファイル．ベクトル化から外す

### `<basename>_ocr.pdf`

- ocr を行った時に作成される ocr 済みの pdf ファイル．このファイルがあるときはベクトルかの時にこのファイルが用いられる．

### `<basename>_skip.pdf`

- ocr 処理やベクトル化から省かれるファイル，一才処理されない（機密ファイルなど）
