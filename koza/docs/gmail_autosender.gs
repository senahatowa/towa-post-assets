/**
 * 講座ライン Gmail 自動送信（凍結しないペースで"送りまくる"）
 * ─────────────────────────────────────────────
 * これは Google Apps Script。あなたのGmailから、
 * ・1日の上限を守って（既定18通/日）
 * ・7〜20時のあいだだけ、1通ごとに間隔をあけて
 * ・「停止」した相手や送信済みを自動でスキップして
 * 差し込み送信します。大量一括じゃないので凍結しにくい。
 *
 * ■ 使い方（5分）
 * 1) Googleスプレッドシートを新規作成。1行目に見出し：
 *      email | name | genre | segment | lp
 *    - segment は A か B（A=講座なし / B=講座あり）
 *    - lp は任意（空でOK。空ならLINE直行文になる）
 *    - 送るのは「個人のクリーンなアドレスだけ」。info@・大手・官公庁は入れない。
 * 2) 拡張機能 → Apps Script を開き、このコードを全部貼る。
 * 3) CONFIG の LINE_A / LINE_B は既にあなたの値。DAILY_LIMIT等は好みで。
 * 4) 初回だけ関数「installTrigger」を実行 → 権限を許可。
 *    これで平日休日問わず毎日、時間内に自動送信が回る。
 * 5) 止めたい時：関数「removeTriggers」を実行。
 *
 * ■ 複数アカウントで送りたい
 *    アカウントごとに別スプレッドシート＋別スクリプトで同じ設定。
 *    各アカウント DAILY_LIMIT を 15〜20 に。合計で50通/日を分散する。
 *
 * ■ 「停止」処理
 *    返信で「停止/不要/配信停止」が来た相手は、スプレッドシートの
 *    その行 email を「停止シート」に移すか status 列に stop と書けば二度と送らない。
 *    （下の SUPPRESS_LABEL の付いたスレッド送信元も自動除外）
 */

const CONFIG = {
  SHEET_NAME: 'sheet1',        // 差し込み元シート名
  DAILY_LIMIT: 18,             // 1日の送信上限（1アカウント）。15〜20推奨
  START_HOUR: 7,               // 送信開始（時）
  END_HOUR: 20,                // 送信終了（時）
  MIN_GAP_MIN: 12,             // 送信間隔の最小（分）※ばらつきで人間っぽく
  MAX_GAP_MIN: 34,             // 送信間隔の最大（分）
  LINE_A: 'https://lin.ee/P3cs6WG',   // 講座なし
  LINE_B: 'https://lin.ee/9mgPajcG',  // 講座あり
  SENDER_NAME: 'ニューリッチ',          // 差出人名（署名）
  SUPPRESS_LABEL: '停止',       // このラベルを付けたスレッドの相手は除外
  DRY_RUN: false,              // true にすると送らずログだけ（テスト用）
};

/** 毎日を回すトリガーを仕込む（初回1回だけ実行） */
function installTrigger() {
  removeTriggers();
  // 30分ごとに起動 → 時間内かつ本日未達なら1通送る
  ScriptApp.newTrigger('tick').timeBased().everyMinutes(30).create();
  Logger.log('トリガー設置OK。7〜20時に自動送信されます。');
}

function removeTriggers() {
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));
}

/** 30分ごとに呼ばれる本体 */
function tick() {
  const now = new Date();
  const h = now.getHours();
  if (h < CONFIG.START_HOUR || h >= CONFIG.END_HOUR) return; // 時間外

  const props = PropertiesService.getScriptProperties();
  const today = Utilities.formatDate(now, Session.getScriptTimeZone(), 'yyyy-MM-dd');
  if (props.getProperty('day') !== today) {            // 日付が変わったらリセット
    props.setProperty('day', today);
    props.setProperty('sentToday', '0');
    props.setProperty('nextAt', '0');
  }
  const sentToday = Number(props.getProperty('sentToday') || '0');
  if (sentToday >= CONFIG.DAILY_LIMIT) return;         // 本日分終了

  const nextAt = Number(props.getProperty('nextAt') || '0');
  if (now.getTime() < nextAt) return;                  // まだ間隔あけ中

  const sent = sendOne();
  if (sent) {
    props.setProperty('sentToday', String(sentToday + 1));
    const gap = (CONFIG.MIN_GAP_MIN + Math.floor(Math.random() * (CONFIG.MAX_GAP_MIN - CONFIG.MIN_GAP_MIN))) * 60000;
    props.setProperty('nextAt', String(now.getTime() + gap)); // 次の送信可能時刻
  }
}

/** 未送信の1件を送る。送ったら true */
function sendOne() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sh = ss.getSheetByName(CONFIG.SHEET_NAME) || ss.getSheets()[0];
  const rng = sh.getDataRange();
  const values = rng.getValues();
  const head = values[0].map(String);
  const col = name => head.indexOf(name);
  const iEmail = col('email'), iName = col('name'), iGenre = col('genre'),
        iSeg = col('segment'), iLp = col('lp');
  let iStatus = col('status');
  if (iStatus === -1) { iStatus = head.length; sh.getRange(1, iStatus + 1).setValue('status'); }

  const suppressed = getSuppressedSet();

  for (let r = 1; r < values.length; r++) {
    const row = values[r];
    const email = String(row[iEmail] || '').trim();
    const status = String(row[iStatus] || '').trim().toLowerCase();
    if (!email || status === 'sent' || status === 'stop') continue;
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) { mark(sh, r, iStatus, 'bademail'); continue; }
    if (/^(info|contact|support|office|admin|mail)@/i.test(email)) { mark(sh, r, iStatus, 'skip-generic'); continue; }
    if (suppressed.has(email.toLowerCase())) { mark(sh, r, iStatus, 'stop'); continue; }

    const name = String(row[iName] || '').trim() || 'ご担当者';
    const genre = String(row[iGenre] || '').trim() || 'その専門';
    const seg = String(row[iSeg] || 'A').trim().toUpperCase();
    const lp = String(row[iLp] || '').trim();
    const { subject, body } = buildMail(seg, name, genre, lp);

    if (CONFIG.DRY_RUN) { Logger.log('[DRY] %s <%s>\n%s', name, email, body); mark(sh, r, iStatus, 'dry'); return true; }
    GmailApp.sendEmail(email, subject, body, { name: CONFIG.SENDER_NAME });
    mark(sh, r, iStatus, 'sent');
    return true;
  }
  return false; // 送る相手がもういない
}

function mark(sh, rowIdx, statusCol, val) {
  sh.getRange(rowIdx + 1, statusCol + 1).setValue(val);
}

/** SUPPRESS_LABEL の付いたスレッドの相手＋「停止」本文の相手を除外集合に */
function getSuppressedSet() {
  const set = new Set();
  try {
    const threads = GmailApp.search('label:' + CONFIG.SUPPRESS_LABEL + ' OR 停止 OR 配信停止 OR 不要', 0, 200);
    threads.forEach(t => t.getMessages().forEach(m => {
      const from = m.getFrom().match(/[^<\s]+@[^>\s]+/);
      if (from) set.add(from[0].toLowerCase());
    }));
  } catch (e) {}
  return set;
}

/** セグメント別の件名・本文（LPが空ならLINE直行文） */
function buildMail(seg, name, genre, lp) {
  const isB = seg === 'B';
  const line = isB ? CONFIG.LINE_B : CONFIG.LINE_A;
  const link = lp ? lp : line;
  const subject = isB
    ? 'その講座、“あなたが動き続けないと”止まりませんか'
    : 'その教え方、“あなたが動かないと”1円にもならないままですか';

  const painsA = {
    'コーチング': ['休んだ瞬間、収入が止まる。', '同じ話を、また一から説明する。', '値上げしても、結局は自分が動いた分だけ。', '頑張るほど、あなた自身がすり減っていく。'],
    '話し方':   ['呼ばれなければ、収入はゼロ。', '同じ内容を、毎回ゼロから。', '会場と日程に、縛られ続ける。', '話した時間の分しか、お金にならない。'],
    'Web集客':  ['手を止めれば、全部止まる。', '体はひとつ、1日は24時間。', '案件が増えるほど、休みは消える。', '結局、動いた分だけ。'],
    '税務':     ['申告期は、時間が足りない。', '同じ説明を、毎回繰り返す。', '価格で比較され、値下げを迫られる。', '顧問料は、件数の分しか増えない。'],
    '労務':     ['手続きと相談に、追われ続ける。', '同じ説明の、繰り返し。', '顧問先が増えるほど、時間は消える。', '動いた分しか、報酬にならない。'],
    '手続き':   ['件数が、そのまま収入。', '手を動かした分しか、入らない。', '価格で比較され、消耗する。', '依頼が増えるほど、休みは消える。'],
  };
  const pain = (painsA[genre] || painsA['コーチング']).join('\n');

  const bodyA =
`${name} 様

${genre}として、これまで教えてきた方へ。正直な話をします。

${pain}

——これ、そろそろ限界じゃないですか。

あなたが毎回教えている“その流れ”を、一度だけ形にする。
それだけで、あなたが寝ている間も、知識が代わりに教えてくれます。

その“設計図”を1枚にまとめました。見るだけ無料です。
▶ ${link}

「設計図」とだけ返信ください。あなた専用版を無料でお作りします。
売り込みはしません。合わなければ、受け取って終わりで大丈夫です。

──────────
${CONFIG.SENDER_NAME}
配信停止をご希望の場合は「停止」とだけご返信ください。以後お送りしません。`;

  const bodyB =
`${name} 様

すでに講座をお持ちの方へ。

講座は作った。なのに——
集客も、運営も、対応も、結局ぜんぶ自分。
受講生が増えるほど、休みは消える。
売上は上がった。でも、時間だけは一秒も増えていない。

——このまま、5年後も続けられますか。

必要なのは“もっと売る”ことじゃありません。
単価を上げて、あなたが動かなくする。しかも、受講生が“一緒に事業を回す仲間”になる。

その設計図を1枚にまとめました。見るだけ無料です。
▶ ${link}

「設計図」とだけ返信ください。あなた専用版を無料でお作りします。
売り込みはしません。合わなければ、受け取って終わりで大丈夫です。

──────────
${CONFIG.SENDER_NAME}
配信停止をご希望の場合は「停止」とだけご返信ください。以後お送りしません。`;

  return { subject, body: isB ? bodyB : bodyA };
}
