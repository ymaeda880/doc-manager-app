brew install ocrmypdf tesseract

brew install ocrmypdf tesseract qpdf ghostscript pngquant

# use_container_width 引数が非推奨（deprecated） になり、2025 年末で削除予定

### 新しい書き方

- 代わりに width 引数 を使います。
- use_container_width=True → width="stretch"
- use_container_width=False → width="content"
