# 完全自動送信（GitHub Actions｜あなたのPC・クリック不要で回る）

これは**GitHubのサーバー上で勝手に動く**自動送信。一度セットすれば、あなたは何もしない。

## 仕組み
- `koza-sender.yml` が30分ごとに起動 → `send.py` が **7〜20時(JST)なら最大1通だけ**送る（ドリップ＝凍結対策）。
- **ウォームアップ**：初週5通/日 → 10 → 15 → 15日目以降20通/日。いきなり大量に送らない。
- `info@`等の窓口・`suppress.txt`（停止）・送信済みは**自動スキップ**。
- 送信結果は自動でリポジトリに記録（`state.json` / `prospects.csv`）。

## あなたが一度だけやること（これだけは代われない＝Gmailの許可）
> メールを「あなたとして」送る以上、Gmailの許可が1回だけ要る。これは世界中どのツールでも同じ（他人が勝手に送れない安全のため）。**1回セットすれば以後ずっと不要。**

1. Gmailで**アプリパスワード**を発行（2段階認証ON → myaccount.google.com/apppasswords → 16桁をコピー）
2. GitHub → このリポジトリ → **Settings → Secrets and variables → Actions → New repository secret** で2つ登録：
   - `GMAIL_USER` = 送信元のGmailアドレス
   - `GMAIL_APP_PASSWORD` = さっきの16桁
3. これで完了。次のcronから自動で送り始める。（`Actions`タブの `koza-cold-sender` → `Run workflow` で即テストも可）

## 送る相手（`prospects.csv`）
- 1行1件で **個人のクリーンなメールだけ**足す。`info@`・大手・官公庁・プレースホルダは入れない。
- 列：`email,name,genre,segment,lp,status`（statusは空のまま＝自動でsentになる）
- ※このCSVを埋めるのが唯一の"燃料"。ここが空だと送るものが無い。

## 止め方・調整
- **止める**：`Settings → Actions` でワークフロー無効化、or アプリパスワードを失効。
- **上限/時間帯**：`send.py` 冒頭の `daily_cap` / `START_HOUR` / `END_HOUR` を編集。
- **複数アカウントで50通/日**：アカwントごとに別リポジトリ（or 別Secrets＋matrix）で同じ設定。各垢15〜20/日に分散。

## 正直な注意（デリバラビリティ）
GitHubのIPからのGmail送信は、Googleに「知らない場所からのログイン」と見なされ**一時ブロックされることがある**。その場合の安全策：
- 初回テスト送信の直後にGmailのセキュリティ通知を「本人」承認しておく。
- それでも不安なら、同梱の `gmail_autosender.gs`（Google自身のサーバーで動く版＝到達性◎）を使う。動かすのに一度だけ手作業が要るが、ブロックされにくい。
