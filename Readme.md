# 概要

`fetch_md_images.py` は、Markdown（.md）ファイル内に埋め込まれた **外部画像 URL** を自動でダウンロードし、  
ローカルパスへ変換するコマンドラインツールです。

特に、

*   **Azure DevOps (ADO) Work Item 添付ファイル**
*   `_apis/wit/attachments/...` の認証付き画像
*   GitHub / Web 上の画像

といった URL 画像をドキュメント化するときに非常に便利です。

***

# 🚀 主な機能

### ✔ Markdown 内の画像 URL を自動検出

以下すべてに対応：

*   `https://...`（インライン画像）
*   `![alt][id]` + `https://...`（参照形式）
*   `https://...`（HTML画像タグ）

### ✔ 画像をローカルへ自動保存

*   デフォルトでは **md ファイルの隣に `images/`** フォルダを作成
*   同じ URL は一度だけダウンロードして再利用（重複保存しない）

### ✔ Markdown 内の画像パスをローカル相対パスへ書き換え

例：

```md
https://dev.azure.com/.../attachment?fileName=test.png
```

👇 自動変換：

```md
images/test_3a1b2c4d5e.png
```

### ✔ Azure DevOps の PAT 認証に対応（必須）

ADO の添付画像は通常 401/403 のため  
`--azdo-pat` または 環境変数 `AZDO_PAT` を使用して認証できます。

### ✔ ディレクトリ内の Markdown を再帰処理

複数ファイルの一括変換が可能。

***

# 📦 インストール

必要ライブラリは `requests` のみ：

```bash
pip install requests
```

***

# 🛠 使い方

## 1. 単一の Markdown を変換

```bash
python fetch_md_images.py README.md
```

変換結果は：

*   `README.md.converted`（元を残したい場合）
*   `images/` フォルダへ画像保存

***

## 2. 元のファイルを上書きする

```bash
python fetch_md_images.py README.md --overwrite
```

***

## 3. 保存先ディレクトリを指定する

```bash
python fetch_md_images.py README.md --out-dir assets/img --overwrite
```

***

## 4. ディレクトリ配下の .md をすべて変換

```bash
python fetch_md_images.py docs/ --out-dir docs/images --overwrite
```

***

## 5. Azure DevOps の画像（認証付き）を扱う場合

### （推奨）環境変数に PAT を設定

**Windows PowerShell**

```powershell
$env:AZDO_PAT = "<YOUR_PAT>"
```

**実行**

```powershell
python fetch_md_images.py README.md --overwrite
```

環境変数がセットされていれば `--azdo-pat` は省略可能です。

***

### 直接渡す方法（履歴に残るので非推奨）

```bash
python fetch_md_images.py README.md --azdo-pat "<YOUR_PAT>" --overwrite
```

***

# 🔧 スクリプトの概要（アーキテクチャ）

### 🧩 1. 画像 URL の検出

正規表現で以下を抽出：

*   `url`
*   `![alt][id]` + `url`
*   `url`

### 🧩 2. HTTP ダウンロード

Azure DevOps PAT がある場合：

*   Authorization: Basic（base64(":PAT")）

ダウンロード成功後：

*   Content-Type から拡張子推定
*   URL の SHA1 ハッシュを付けたユニークファイル名生成

### 🧩 3. Markdown パス書き換え

Markdown の構文（alt / title）は保持しつつ URL を相対パスへ置換。

***

# 📝 オプション一覧

| オプション         | 説明                                   |
| ------------- | ------------------------------------ |
| `--out-dir`   | 画像保存先（デフォルト: images）                 |
| `--overwrite` | 元のファイルを上書き                           |
| `--azdo-pat`  | Azure DevOps の Personal Access Token |
| `--timeout`   | HTTP タイムアウト（秒）                       |
| `--retries`   | リトライ回数                               |

***

