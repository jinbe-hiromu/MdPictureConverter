#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import base64
import hashlib
import os
import mimetypes
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, unquote

import requests

# --- 正規表現パターン ---
# インライン画像: ![alt](URL "title")
MD_IMG_INLINE = re.compile(
    r'!\[(?P<alt>[^\]]*)\]\('
    r'(?P<url>\S+?)'
    r'(?:\s+"(?P<title>[^"]*)")?'
    r'\)',
    flags=re.IGNORECASE,
)

# 参照形式: ![alt][id]
MD_IMG_REF = re.compile(
    r'!\[(?P<alt>[^\]]*)\]\[(?P<id>[^\]]+)\]',
    flags=re.IGNORECASE,
)

# 参照定義: [id]: URL "title"
MD_REF_DEF = re.compile(
    r'^\[(?P<id>[^\]]+)\]:\s*(?P<url>\S+)'
    r'(?:\s+"(?P<title>[^"]*)")?\s*$',
    flags=re.IGNORECASE | re.MULTILINE,
)

# HTML <img ... src="URL" ...>
HTML_IMG = re.compile(
    r'<img\b[^>]*?\bsrc=(?P<q>["\'])(?P<src>.+?)\1[^>]*?>',
    flags=re.IGNORECASE | re.DOTALL,
)

HTTP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/121.0 Safari/537.36"
)


def is_http_url(url: str) -> bool:
    try:
        p = urlparse(url)
        return p.scheme in ("http", "https")
    except Exception:
        return False


def safe_filename_from_url(url: str, content_type: str | None) -> str:
    """
    URL からファイル名を推定。拡張子が無ければ Content-Type から補完。
    URL の SHA1 を付与して衝突を回避。
    """
    parsed = urlparse(url)
    name = os.path.basename(unquote(parsed.path)) or "image"
    root, ext = os.path.splitext(name)

    if not ext and content_type:
        ext_guess = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if ext_guess:
            ext = ext_guess

    if not ext:
        ext = ".bin"

    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    return f"{root}_{h}{ext}"


def build_session(azdo_pat: str | None) -> requests.Session:
    """
    Azure DevOps の PAT があれば Authorization: Basic を付与。
    形式は base64(":"+PAT)。
    """
    s = requests.Session()
    s.headers.update({"User-Agent": HTTP_UA})

    if azdo_pat:
        token_bytes = (":" + azdo_pat).encode("utf-8")
        b64 = base64.b64encode(token_bytes).decode("ascii")
        s.headers.update({"Authorization": f"Basic {b64}"})
    return s


def download(url: str, out_dir: Path, session: requests.Session,
             max_retries: int = 2, timeout: int = 20) -> Path | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            with session.get(url, stream=True, timeout=timeout) as resp:
                # 429/5xx はリトライ対象
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"{resp.status_code} {resp.reason}")
                resp.raise_for_status()

                ctype = resp.headers.get("Content-Type", "")
                fname = safe_filename_from_url(url, ctype)
                out_path = out_dir / fname

                if out_path.exists() and out_path.stat().st_size > 0:
                    return out_path

                with open(out_path, "wb") as f:
                    for chunk in resp.iter_content(8192):
                        if chunk:
                            f.write(chunk)
                return out_path
        except Exception as e:
            last_exc = e
            if attempt < max_retries:
                time.sleep(0.7 * (attempt + 1))
            else:
                sys.stderr.write(f"[WARN] download failed: {url} -> {e}\n")
    return None


def process_inline(text: str, out_dir: Path, session: requests.Session,
                   cache: dict[str, str], md_base_dir: Path) -> str:
    def _repl(m: re.Match):
        alt = m.group("alt") or ""
        url = m.group("url")
        title = m.group("title")
        if not is_http_url(url):
            return m.group(0)

        if url in cache:
            local_rel = cache[url]
        else:
            saved = download(url, out_dir, session)
            if not saved:
                return m.group(0)
            local_rel = os.path.relpath(saved, start=md_base_dir)
            cache[url] = local_rel

        # Markdown 構文を維持して URL のみ置換
        if title:
            return f'![{alt}]({local_rel} "{title}")'
        else:
            return f'![{alt}]({local_rel})'
    return MD_IMG_INLINE.sub(_repl, text)


def parse_ref_defs(text: str) -> dict[str, tuple[str, str | None]]:
    defs: dict[str, tuple[str, str | None]] = {}
    for m in MD_REF_DEF.finditer(text):
        defs[m.group("id")] = (m.group("url"), m.group("title"))
    return defs


def process_ref(text: str, out_dir: Path, session: requests.Session,
                cache: dict[str, str], md_base_dir: Path) -> str:
    # 本文側はそのまま、定義側([id]: URL)を置き換えるアプローチ
    defs = parse_ref_defs(text)

    def _repl_def(m: re.Match):
        ref_id = m.group("id")
        url = m.group("url")
        title = m.group("title")
        if not is_http_url(url):
            return m.group(0)

        if url in cache:
            local_rel = cache[url]
        else:
            saved = download(url, out_dir, session)
            if not saved:
                return m.group(0)
            local_rel = os.path.relpath(saved, start=md_base_dir)
            cache[url] = local_rel

        if title:
            return f'[{ref_id}]: {local_rel} "{title}"'
        else:
            return f'[{ref_id}]: {local_rel}'

    return MD_REF_DEF.sub(_repl_def, text)


def process_html(text: str, out_dir: Path, session: requests.Session,
                 cache: dict[str, str], md_base_dir: Path) -> str:
    def _repl(m: re.Match):
        src = m.group("src")
        q = m.group("q")
        if not is_http_url(src):
            return m.group(0)

        if src in cache:
            local_rel = cache[src]
        else:
            saved = download(src, out_dir, session)
            if not saved:
                return m.group(0)
            local_rel = os.path.relpath(saved, start=md_base_dir)
            cache[src] = local_rel

        tag = m.group(0)
        return re.sub(r'\bsrc=(["\']).*?\1', f'src={q}{local_rel}{q}', tag, count=1)

    return HTML_IMG.sub(_repl, text)


def process_md_file(md_path: Path, out_dir: Path, overwrite: bool,
                    session: requests.Session) -> Path:
    text = md_path.read_text(encoding="utf-8")

    # out_dir が相対なら MD の場所基準に解決
    if not out_dir.is_absolute():
        out_dir = (md_path.parent / out_dir).resolve()

    cache: dict[str, str] = {}
    base = md_path.parent.resolve()

    text1 = process_inline(text, out_dir, session, cache, base)
    text2 = process_ref(text1, out_dir, session, cache, base)
    text3 = process_html(text2, out_dir, session, cache, base)

    out_path = md_path if overwrite else md_path.with_suffix(md_path.suffix + ".converted")
    out_path.write_text(text3, encoding="utf-8")
    return out_path


def find_md(target: Path) -> list[Path]:
    if target.is_file() and target.suffix.lower() in (".md", ".markdown"):
        return [target]
    if target.is_dir():
        return [p for p in target.rglob("*") if p.suffix.lower() in (".md", ".markdown")]
    return []


def main():
    parser = argparse.ArgumentParser(
        description="Markdown の画像 URL をダウンロードしてローカル参照へ書き換えます（Azure DevOps 認証対応）。"
    )
    parser.add_argument("target", type=str, help=".md ファイルまたはディレクトリ")
    parser.add_argument("--out-dir", type=str, default="images", help="画像保存先（既定: images）")
    parser.add_argument("--overwrite", action="store_true", help="元の .md を上書き")
    parser.add_argument(
        "--azdo-pat",
        type=str,
        default=os.environ.get("AZDO_PAT"),  # ← 環境変数があれば既定で使う
        help="Azure DevOps Personal Access Token（環境変数 AZDO_PAT でも可）"
    )
    parser.add_argument("--timeout", type=int, default=20, help="HTTP タイムアウト秒（既定: 20）")
    parser.add_argument("--retries", type=int, default=2, help="HTTP リトライ回数（既定: 2）")
    args = parser.parse_args()

    target = Path(args.target).resolve()
    out_dir = Path(args.out_dir)
    session = build_session(args.azdo_pat)

    # グローバルの download 設定を上書きしたい場合は、部分的に関数を書き換えるか、
    # download をラップする実装に差し替えるなど拡張してください。
    # （簡潔さのため、ここでは download の引数は固定のまま）

    files = find_md(target)
    if not files:
        sys.stderr.write("[INFO] 対象の Markdown が見つかりませんでした。\n")
        sys.exit(1)

    for md in files:
        try:
            outp = process_md_file(md, out_dir, args.overwrite, session)
            print(f"[OK] {md} -> {outp}")
        except Exception as e:
            sys.stderr.write(f"[ERROR] {md}: {e}\n")
            # 続行

if __name__ == "__main__":
    main()