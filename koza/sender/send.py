#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
講座ライン 完全自動送信（GitHub Actions のサーバー上で勝手に動く）
- あなたのPC不要・クリック不要。GitHubのcronが1日中まわす。
- 1回の起動で最大1通だけ送る（ドリップ）＝ 凍結しにくい。
- ウォームアップ（初週5通/日→段階的に増やす）、7〜20時(JST)だけ、
  info@等の窓口・停止リスト・送信済みを自動スキップ。
- 送信は Gmail SMTP。認証は GitHub Secrets の GMAIL_USER / GMAIL_APP_PASSWORD。
  （これだけは"あなたのGmailの許可"が要る＝誰にも代われない。1回セットすれば以後不要）
"""
import csv, json, os, re, ssl, smtplib, random
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "prospects.csv")
STATE_PATH = os.path.join(HERE, "state.json")
SUPPRESS_PATH = os.path.join(HERE, "suppress.txt")

LINE_A = "https://lin.ee/P3cs6WG"   # 講座なし
LINE_B = "https://lin.ee/9mgPajcG"  # 講座あり
SENDER_NAME = "ニューリッチ"
START_HOUR, END_HOUR = 7, 20        # JST
# ウォームアップ：稼働日数 -> その日の上限
def daily_cap(days):
    if days <= 3:  return 5
    if days <= 7:  return 10
    if days <= 14: return 15
    return 20

JST = timezone(timedelta(hours=9))

def now_jst():
    return datetime.now(JST)

def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"first_date": now_jst().strftime("%Y-%m-%d"), "per_day": {}}

def save_state(s):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)

def load_suppress():
    s = set()
    if os.path.exists(SUPPRESS_PATH):
        with open(SUPPRESS_PATH, encoding="utf-8") as f:
            for line in f:
                e = line.strip().lower()
                if e and not e.startswith("#"):
                    s.add(e)
    return s

PAINS_A = {
    "コーチング": ["休んだ瞬間、収入が止まる。", "同じ話を、また一から説明する。", "値上げしても、結局は自分が動いた分だけ。", "頑張るほど、あなた自身がすり減っていく。"],
    "話し方":   ["呼ばれなければ、収入はゼロ。", "同じ内容を、毎回ゼロから。", "会場と日程に、縛られ続ける。", "話した時間の分しか、お金にならない。"],
    "Web集客":  ["手を止めれば、全部止まる。", "体はひとつ、1日は24時間。", "案件が増えるほど、休みは消える。", "結局、動いた分だけ。"],
    "税務":     ["申告期は、時間が足りない。", "同じ説明を、毎回繰り返す。", "価格で比較され、値下げを迫られる。", "顧問料は、件数の分しか増えない。"],
    "労務":     ["手続きと相談に、追われ続ける。", "同じ説明の、繰り返し。", "顧問先が増えるほど、時間は消える。", "動いた分しか、報酬にならない。"],
    "手続き":   ["件数が、そのまま収入。", "手を動かした分しか、入らない。", "価格で比較され、消耗する。", "依頼が増えるほど、休みは消える。"],
}

def build_mail(seg, name, genre, lp):
    is_b = (seg or "A").strip().upper() == "B"
    line = LINE_B if is_b else LINE_A
    link = lp.strip() if lp and lp.strip() else line
    if is_b:
        subject = "その講座、“あなたが動き続けないと”止まりませんか"
        body = f"""{name} 様

すでに講座をお持ちの方へ。

講座は作った。なのに——
集客も、運営も、対応も、結局ぜんぶ自分。
受講生が増えるほど、休みは消える。
売上は上がった。でも、時間だけは一秒も増えていない。

——このまま、5年後も続けられますか。

必要なのは“もっと売る”ことじゃありません。
単価を上げて、あなたが動かなくする。しかも、受講生が“一緒に事業を回す仲間”になる。

その設計図を1枚にまとめました。見るだけ無料です。
▶ {link}

「設計図」とだけ返信ください。あなた専用版を無料でお作りします。
売り込みはしません。合わなければ、受け取って終わりで大丈夫です。

──────────
{SENDER_NAME}
配信停止をご希望の場合は「停止」とだけご返信ください。以後お送りしません。"""
    else:
        pain = "\n".join(PAINS_A.get((genre or "").strip(), PAINS_A["コーチング"]))
        subject = "その教え方、“あなたが動かないと”1円にもならないままですか"
        body = f"""{name} 様

{genre or 'その専門'}として、これまで教えてきた方へ。正直な話をします。

{pain}

——これ、そろそろ限界じゃないですか。

あなたが毎回教えている“その流れ”を、一度だけ形にする。
それだけで、あなたが寝ている間も、知識が代わりに教えてくれます。

その“設計図”を1枚にまとめました。見るだけ無料です。
▶ {link}

「設計図」とだけ返信ください。あなた専用版を無料でお作りします。
売り込みはしません。合わなければ、受け取って終わりで大丈夫です。

──────────
{SENDER_NAME}
配信停止をご希望の場合は「停止」とだけご返信ください。以後お送りしません。"""
    return subject, body

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
GENERIC_RE = re.compile(r"^(info|contact|support|office|admin|mail|inquiry|form)@", re.I)

def main():
    now = now_jst()
    if now.hour < START_HOUR or now.hour >= END_HOUR:
        print(f"[skip] out of window {now.hour}h JST"); return
    if now.weekday() is not None:  # 土日も送る（曜日で止めない）
        pass

    user = os.environ.get("GMAIL_USER", "").strip()
    pw = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
    if not user or not pw:
        print("[stop] GMAIL_USER / GMAIL_APP_PASSWORD secrets not set. Nothing sent."); return

    if not os.path.exists(CSV_PATH):
        print("[stop] prospects.csv not found."); return

    state = load_state()
    today = now.strftime("%Y-%m-%d")
    first = datetime.strptime(state.get("first_date", today), "%Y-%m-%d").date()
    days = (now.date() - first).days + 1
    cap = daily_cap(days)
    sent_today = state.get("per_day", {}).get(today, 0)
    if sent_today >= cap:
        print(f"[done] today {sent_today}/{cap} (day {days}) reached."); return

    suppress = load_suppress()

    with open(CSV_PATH, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("[stop] no prospects."); return
    fields = list(rows[0].keys())
    if "status" not in fields:
        fields.append("status")
        for r in rows: r.setdefault("status", "")

    target = None
    for r in rows:
        email = (r.get("email") or "").strip()
        st = (r.get("status") or "").strip().lower()
        if not email or st.startswith("sent") or st == "stop": continue
        if not EMAIL_RE.match(email): r["status"] = "bademail"; continue
        if GENERIC_RE.match(email):   r["status"] = "skip-generic"; continue
        if email.lower() in suppress: r["status"] = "stop"; continue
        target = r; break

    if target is None:
        # 書き戻し（skip判定の更新だけでも保存）
        with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
        print("[done] no more sendable prospects."); return

    name = (target.get("name") or "ご担当者").strip() or "ご担当者"
    genre = (target.get("genre") or "").strip()
    seg = (target.get("segment") or "A").strip()
    lp = (target.get("lp") or "").strip()
    subject, body = build_mail(seg, name, genre, lp)

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header(SENDER_NAME, "utf-8")), user))
    msg["To"] = target["email"].strip()

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as s:
        s.login(user, pw)
        s.sendmail(user, [target["email"].strip()], msg.as_string())

    target["status"] = "sent:" + today
    state.setdefault("per_day", {})[today] = sent_today + 1
    save_state(state)
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
    print(f"[sent] {target['email']} ({seg}) — today {sent_today+1}/{cap} day {days}")

if __name__ == "__main__":
    main()
