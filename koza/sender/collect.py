#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
燃料補充スクレイパー（あなたのPC or Codex で動かす。※GitHubの箱はネットに出られないのでここでは動かせない）

やること：士業/個人専門家の「事務所サイト」を巡回して、
  - 実在するメールアドレスをページから抽出（推測しない＝バウンス防止）
  - 個人・小規模っぽさ／A・B（講座あり）を簡易判定
  - koza/sender/prospects.csv に追記（重複・info@類は除外/フラグ）

使い方（Codexやローカルで）:
  pip install requests beautifulsoup4
  # seeds.txt に「事務所サイトのURL」を1行1件で用意（士業会名簿や検索から集めたURLでOK）
  python collect.py seeds.txt

  ★URLの集め方：士業会の会員名簿ページ、Google検索「税理士事務所 個人」等の結果URL、
    freelance-meikan / ストアカ の各プロフURL。これらを seeds.txt に貼るだけ。
"""
import csv, os, re, sys, time, html
from urllib.parse import urljoin, urlparse

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("先に: pip install requests beautifulsoup4"); sys.exit(1)

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "prospects.csv")

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
GENERIC = re.compile(r"^(info|contact|support|office|admin|mail|inquiry|form|webmaster|no-?reply)@", re.I)
CONTACT_HINTS = ["contact", "inquiry", "toiawase", "問い合わせ", "お問合", "company", "profile", "about", "gaiyou", "概要"]

# A/B・ジャンルの簡易判定キーワード
B_WORDS = ["講座", "スクール", "オンラインサロン", "受講生", "養成", "アカデミー", "セミナー生", "コース受講"]
GENRE_MAP = [
    (["税理士", "税務", "確定申告", "記帳"], "税務"),
    (["社会保険労務士", "社労士", "労務", "就業規則"], "労務"),
    (["司法書士", "行政書士", "登記", "相続", "許認可", "補助金"], "手続き"),
    (["コーチ", "コーチング", "ライフコーチ"], "コーチング"),
    (["話し方", "スピーチ", "プレゼン", "アナウンサー", "ボイス"], "話し方"),
    (["web集客", "webマーケ", "seo", "sns集客", "広告運用"], "Web集客"),
]

def fetch(url, timeout=12):
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0 (prospect-collector)"})
        if r.status_code == 200 and "text/html" in r.headers.get("content-type", ""):
            r.encoding = r.apparent_encoding
            return r.text
    except Exception:
        pass
    return ""

def find_contact_pages(base_url, home_html):
    soup = BeautifulSoup(home_html, "html.parser")
    urls = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        if any(h in href for h in CONTACT_HINTS):
            urls.add(urljoin(base_url, a["href"]))
    return list(urls)[:4]

def guess_name(text):
    m = re.search(r"(代表|所長|税理士|社労士|社会保険労務士|司法書士|行政書士|講師)[\s:：]*([一-龥]{2,4}\s?[一-龥]{2,4})", text)
    return (m.group(2).replace(" ", "") if m else "")

def classify(text):
    low = text.lower()
    genre = ""
    for kws, g in GENRE_MAP:
        if any(k.lower() in low for k in kws):
            genre = g; break
    seg = "B" if any(w in text for w in B_WORDS) else "A"
    return genre, seg

def emails_from(text):
    found = set(m.group(0) for m in EMAIL_RE.finditer(html.unescape(text)))
    # 画像/難読化されてない実メールのみ。パターン推測はしない。
    return {e for e in found if not e.lower().endswith((".png", ".jpg", ".gif"))}

def load_existing():
    seen = set()
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, encoding="utf-8") as f:
            for row in csv.reader(f):
                if row and "@" in row[0]:
                    seen.add(row[0].strip().lower())
    return seen

def main():
    if len(sys.argv) < 2:
        print("usage: python collect.py seeds.txt"); return
    with open(sys.argv[1], encoding="utf-8") as f:
        seeds = [l.strip() for l in f if l.strip() and not l.startswith("#")]

    seen = load_existing()
    rows = []
    for i, url in enumerate(seeds, 1):
        home = fetch(url)
        if not home:
            print(f"[{i}/{len(seeds)}] x {url}"); continue
        pages_text = home
        for cp in find_contact_pages(url, home):
            pages_text += "\n" + fetch(cp)
            time.sleep(1)
        emails = emails_from(pages_text)
        # 個人らしい(=info@等でない)アドレスを優先。無ければ generic を候補として拾い、フラグ。
        personal = sorted(e for e in emails if not GENERIC.match(e))
        pick = personal[0] if personal else (sorted(emails)[0] if emails else "")
        if not pick or pick.lower() in seen:
            print(f"[{i}/{len(seeds)}] - no new email: {url}"); continue
        seen.add(pick.lower())
        name = guess_name(pages_text) or "ご担当者"
        genre, seg = classify(pages_text)
        flag = "" if not GENERIC.match(pick) else "generic?"
        rows.append([pick, name, genre, seg, "", flag])
        print(f"[{i}/{len(seeds)}] + {pick}  {name}  {genre}/{seg} {flag}")
        time.sleep(1)

    if not rows:
        print("新規なし"); return
    newfile = not os.path.exists(CSV_PATH)
    with open(CSV_PATH, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if newfile:
            w.writerow(["email", "name", "genre", "segment", "lp", "status"])
        w.writerows(rows)
    print(f"\n{len(rows)}件を prospects.csv に追記。'generic?' の行は個人メールか確認してから使う。")

if __name__ == "__main__":
    main()
