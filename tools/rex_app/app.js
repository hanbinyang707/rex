// 录音台的页面逻辑。只负责画界面、把按钮翻译成请求；判断和改文件都在 rex_app.py / proofread.py 里。
'use strict';

const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const AUDIO_EXT = ['m4a', 'wav', 'qta', 'mp3', 'aac', 'flac', 'ogg', 'opus', 'caf', 'aiff', 'aif', 'm4b', 'webm', 'mp4', 'mov', 'm4v', 'mkv'];
const PALETTE = ['#3b5bdb', '#d9480f', '#2b8a3e', '#ae3ec9', '#0c8599', '#e67700', '#c2255c'];

// 界面语言：服务端按 REX_LANG 把 <html lang> 设成 en 或 zh-CN。T('中文', 'English') 按它挑一个；
// index.html 里的静态文字写 data-en（以及 data-en-placeholder / data-en-title），载入时换成英文
const EN = document.documentElement.lang === 'en';
const T = (zh, en) => (EN ? en : zh);

// 英文界面：把 index.html 里写好的 data-en* 换上去。HTML 里的 <title> 必须一直是「录音台」（rex.sh 靠这个
// 确切的字符串认出端口上是录音台），英文标题在这里设
if (EN) {
  document.title = 'Rex · Recording Desk';
  document.querySelectorAll('[data-en]').forEach(el => { el.textContent = el.dataset.en; });
  document.querySelectorAll('[data-en-placeholder]').forEach(el => { el.placeholder = el.dataset.enPlaceholder; });
  document.querySelectorAll('[data-en-title]').forEach(el => { el.title = el.dataset.enTitle; });
}

// 任务状态是服务端的固定值（排队 / 进行中 / 完成 / 出错），比较都拿它比；只有显示时才翻
const JOB_STATE_EN = { '排队': 'Queued', '进行中': 'Running', '完成': 'Done', '出错': 'Failed' };
// 英文的单复数：plural(1, 'line') → 1 line，plural(3, 'line') → 3 lines
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

const S = {
  list: [], sel: null, rex: null, tab: 'text', focus: 0, results: null, recording: { on: false },
  sig: '', lastScroll: 0, colors: {}, phoneLoaded: false,
  picked: new Set(), join: null, joinWatch: null,   // ⌘ 点选的几条；「合成一条」对话框；等着合成好的那条
};

// ---------------------------------------------------------------- 工具

async function api(path, body) {
  const opt = body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Rex-App': '1' }, body: JSON.stringify(body),
  };
  let r, j;
  try { r = await fetch(path, opt); } catch (e) { return { ok: false, msg: T('连不上录音台服务（rex app 关了？）', "Can't reach the Recording Desk server (is rex app stopped?)") }; }
  try { j = await r.json(); } catch (e) { j = { ok: false, msg: T('服务没回应', 'No response from the server') }; }
  if (r.status === 403 && j.auth) {
    // 口令对不上就重开一次页面拿新口令；但别无限刷（浏览器禁了 cookie、同时开着两个端口的录音台都会这样）
    let n = 0;
    try { n = +(sessionStorage.getItem('rex_reloads') || 0); sessionStorage.setItem('rex_reloads', n + 1); } catch (e) { /* 没有就算 */ }
    if (n < 3) { location.reload(); return { ok: false, msg: T('重新连接…', 'Reconnecting…') }; }
    return { ok: false, msg: T('口令对不上：在终端里跑 rex app 重新打开这一页', 'Token mismatch: run rex app in a terminal to reopen this page') };
  }
  if (r.ok) { try { sessionStorage.removeItem('rex_reloads'); } catch (e) { /* 没有就算 */ } }
  return j;
}

function toast(msg, kind = '', ms = 5000) {
  const el = document.createElement('div');
  el.className = 'toast ' + kind;
  el.textContent = msg;
  $('#toasts').appendChild(el);
  setTimeout(() => el.remove(), ms);
}

function fmt(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60;
  const p = n => String(n).padStart(2, '0');
  return h ? `${h}:${p(m)}:${p(s)}` : `${p(m)}:${p(s)}`;
}

const mb = n => (n / 1048576).toFixed(n < 10485760 ? 1 : 0) + ' MB';

function dur(sec) {
  if (!sec) return '';
  if (sec < 60) return T(`${sec} 秒`, `${sec} s`);
  const m = Math.round(sec / 60);
  return m < 60 ? T(`${m} 分钟`, `${m} min`) : T(`${Math.floor(m / 60)} 小时 ${m % 60} 分`, `${Math.floor(m / 60)} h ${m % 60} min`);
}

// 两路录音的说话人：中文稿子是「我 / 对方」，英文稿子是「Me / Other」。认哪种跟界面语言无关，稿子是哪种就是哪种
function color(who) {
  if (!who) return 'inherit';
  if (!S.colors[who]) {
    if (who === '我' || who === 'Me') S.colors[who] = PALETTE[0];
    else if (who === '对方' || who === 'Other') S.colors[who] = PALETTE[1];
    else {
      const n = parseInt((who.match(/\d+/) || ['0'])[0], 10);
      S.colors[who] = PALETTE[(n || Object.keys(S.colors).length) % PALETTE.length];
    }
  }
  return S.colors[who];
}

function dayLabel(when) {
  const d = (when || '').slice(0, 10);
  const today = new Date();
  const iso = x => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`;
  const y = new Date(today); y.setDate(today.getDate() - 1);
  if (d === iso(today)) return T('今天', 'Today');
  if (d === iso(y)) return T('昨天', 'Yesterday');
  return d || T('没有日期', 'No date');
}

// 在一行字里标出若干片段（第一次出现的位置，互不重叠）。先切段再逐段转义，别在转义过的字符串上找
function marked(text, marks) {
  const spans = [];
  for (const m of marks) {
    if (!m.s) continue;
    let from = 0, i;
    while ((i = text.indexOf(m.s, from)) >= 0) {
      if (!spans.some(x => i < x.end && i + m.s.length > x.start)) { spans.push({ start: i, end: i + m.s.length, m }); break; }
      from = i + 1;
    }
  }
  spans.sort((a, b) => a.start - b.start);
  let out = '', at = 0;
  for (const sp of spans) {
    out += esc(text.slice(at, sp.start));
    out += `<span class="${sp.m.cls}" title="${esc(sp.m.title)}">${esc(text.slice(sp.start, sp.end))}</span>`;
    at = sp.end;
  }
  return out + esc(text.slice(at));
}

// 最小的 Markdown：标题、粗体、行内代码、列表、表格、引用、分隔线、段落。时间戳变成能点的
function md(src) {
  const inline = s => esc(s)
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/(^|[^\d:])((?:\d{1,2}:)?\d{1,2}:\d{2})(?![\d:])/g, (all, pre, t) => {
      const p = t.split(':').map(Number);
      const sec = p.length === 3 ? p[0] * 3600 + p[1] * 60 + p[2] : p[0] * 60 + p[1];
      return `${pre}<span class="tlink" data-t="${sec}">${t}</span>`;
    });
  const lines = src.replace(/\r/g, '').split('\n');
  let out = '', i = 0;
  while (i < lines.length) {
    const ln = lines[i];
    if (/^```/.test(ln)) {
      let code = ''; i++;
      while (i < lines.length && !/^```/.test(lines[i])) code += lines[i++] + '\n';
      out += `<pre><code>${esc(code)}</code></pre>`; i++; continue;
    }
    let m;
    if ((m = ln.match(/^(#{1,6})\s+(.*)$/))) { out += `<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`; i++; continue; }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(ln)) { out += '<hr>'; i++; continue; }
    if (/^\s*\|.*\|\s*$/.test(ln)) {
      const rows = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(lines[i++]);
      const cells = r => r.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim());
      const body = rows.filter(r => !/^\s*\|[\s:|-]+\|\s*$/.test(r));
      out += '<table>' + body.map((r, k) => '<tr>' + cells(r).map(c => k === 0 ? `<th>${inline(c)}</th>` : `<td>${inline(c)}</td>`).join('') + '</tr>').join('') + '</table>';
      continue;
    }
    if (/^\s*>/.test(ln)) {
      let q = '';
      while (i < lines.length && /^\s*>/.test(lines[i])) q += lines[i++].replace(/^\s*>\s?/, '') + ' ';
      out += `<blockquote>${inline(q)}</blockquote>`; continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(ln)) {
      const ordered = /^\s*\d+\./.test(ln);
      let items = '';
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) items += `<li>${inline(lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, ''))}</li>`;
      out += ordered ? `<ol>${items}</ol>` : `<ul>${items}</ul>`; continue;
    }
    if (!ln.trim()) { i++; continue; }
    let para = '';
    while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|```|\s*\||\s*>|\s*([-*]|\d+\.)\s)/.test(lines[i])) para += lines[i++] + '\n';
    out += `<p>${inline(para.trim()).replace(/\n/g, '<br>')}</p>`;
  }
  return out;
}

// ---------------------------------------------------------------- 左边：列表

function chips(r) {
  const c = [];
  if (r.busy) c.push(`<span class="chip busy"><span class="spin"></span> ${T('处理中', 'Processing')}</span>`);
  if (r.parts > 1) c.push(`<span class="chip" title="${T(`由 ${r.parts} 段录音合成`, `Joined from ${r.parts} recordings`)}">${T(`${r.parts} 段`, `${r.parts} parts`)}</span>`);
  if (!r.transcribed) c.push(`<span class="chip">${T('没转写', 'Not transcribed')}</span>`);
  else if (r.dialogue) c.push(`<span class="chip ok">${r.speakers.length > 1 ? r.speakers.length + T(' 人', ' speakers') : T('对话稿', 'Transcript')}</span>`);
  if (r.proof) {
    if (r.proof.failed) c.push(`<span class="chip bad">${T(`${r.proof.failed} 行没校`, `${plural(r.proof.failed, 'line')} not proofread`)}</span>`);
    if (r.proof.unsure) c.push(`<span class="chip warn">${T(`待确认 ${r.proof.unsure}`, `${r.proof.unsure} to confirm`)}</span>`);
    else if (!r.proof.failed) c.push(`<span class="chip ok">${T('校对 ✓', 'Proofread ✓')}</span>`);
  }
  if (r.analyzed) c.push(`<span class="chip ok">${T('分析 ✓', 'Analysis ✓')}</span>`);
  return c.join('');
}

function renderList() {
  const el = $('#list');
  if (S.results) {
    if (!S.results.length) { el.innerHTML = `<div class="group">${T('没搜到', 'No results')}</div>`; return; }
    el.innerHTML = `<div class="group">${T('搜索结果', 'Search results')}</div>` + S.results.map(r => `
      <div class="item ${r.key === S.sel ? 'sel' : ''}" data-key="${esc(r.key)}">
        <div class="t">${esc(r.title)}</div>
        <div class="m">${esc(r.when)}</div>
        ${r.hits.map(h => `<div class="hit"><span class="ts" data-key="${esc(r.key)}" data-t="${h.t == null ? '' : h.t}">${h.t == null ? '' : fmt(h.t)}</span>${esc(h.text)}</div>`).join('')}
      </div>`).join('');
    return;
  }
  if (!S.list.length) { el.innerHTML = `<div class="group">${T('还没有录音', 'No recordings yet')}</div>`; return; }
  let html = '', last = '';
  for (const r of S.list) {
    const g = dayLabel(r.when);
    if (g !== last) { html += `<div class="group">${esc(g)}</div>`; last = g; }
    // source 是服务端按界面语言给的标签（rex_app.py 的 L('导入', 'Imported')），这里比较用同一对
    const meta = [r.when.slice(11), r.source + (r.origin && r.source === T('导入', 'Imported') ? '' : ''), dur(r.duration)].filter(Boolean).join(' · ');
    html += `<div class="item ${r.key === S.sel ? 'sel' : ''} ${S.picked.has(r.key) ? 'picked' : ''}" data-key="${esc(r.key)}" title="${T('双击移到废纸篓 · ⌘ 点选几条可以合成一条', 'Double-click to move to the Trash · ⌘-click several to join them into one')}">
      <div class="t">${esc(r.title)}</div>
      <div class="m">${esc(meta)} ${chips(r)}</div></div>`;
  }
  el.innerHTML = html;
}

// ⌘ 点选了几条：列表上面一条横栏，「合成一条…」打开对话框
function renderPickbar() {
  const el = $('#pickbar'), n = S.picked.size;
  el.hidden = !n;
  if (!n) return;
  el.innerHTML = `<span>${T(`已选 ${n} 条`, `${n} selected`)}</span>
    <button class="primary" data-act="join" ${n < 2 ? 'disabled' : ''}>${T('合成一条…', 'Join into one…')}</button>
    <button class="ghost" data-act="unpick">${T('取消', 'Cancel')}</button>
    ${n < 2 ? `<span class="muted">${T('再 ⌘ 点一条', '⌘-click one more')}</span>` : ''}`;
}

function togglePick(k) {
  if (!S.picked.size && S.sel && S.sel !== k) S.picked.add(S.sel);    // 和访达一样：⌘ 点是「再加一条」，开着的那条也算
  if (S.picked.has(k)) S.picked.delete(k); else S.picked.add(k);
  renderList(); renderPickbar();
}

function renderJobs(jobs, inbox) {
  const el = $('#jobs');
  const parts = [];
  if (inbox && inbox.busy) {
    parts.push(`<div class="job"><div class="h"><span class="chip busy"><span class="spin"></span> ${T('收件箱', 'Inbox')}</span> ${T('正在处理', 'processing')}</div>
      ${inbox.tail.length ? `<pre>${esc(inbox.tail.slice(-5).join('\n'))}</pre>` : ''}</div>`);
  }
  if (inbox && inbox.waiting && inbox.waiting.length && !inbox.busy) {
    const n = inbox.waiting.length;
    parts.push(`<div class="job"><div class="h"><span class="chip warn">${T('收件箱', 'Inbox')}</span> ${T(`${n} 个文件在等`, `${plural(n, 'file')} waiting`)}</div></div>`);
  }
  for (const j of jobs.slice().reverse()) {
    if (j.state === '完成' && Date.now() / 1000 - j.ended > 600) continue;
    const cls = { '排队': '', '进行中': 'busy', '完成': 'ok', '出错': 'bad' }[j.state] || '';
    parts.push(`<div class="job"><div class="h"><span class="chip ${cls}">${j.state === '进行中' ? '<span class="spin"></span> ' : ''}${esc(T(j.state, JOB_STATE_EN[j.state] || j.state))}</span> ${esc(j.label)}</div>
      ${j.state !== '完成' && j.tail.length ? `<pre>${esc(j.tail.slice(-4).join('\n'))}</pre>` : ''}</div>`);
  }
  el.innerHTML = parts.join('') || `<span class="muted">${T('没有', 'None')}</span>`;
}

function renderRecording(r) {
  S.recording = r;
  $('#recbar').classList.toggle('on', !!r.on);
  $('#recbar').classList.toggle('busy', !!r.stopping);
  $('#recmode').textContent = r.on ? ' · ' + ({ sys: T('只录电脑声音', 'Computer audio only'), both: T('我 + 对方', 'Me + other side'), mic: T('只录我', 'Only me') }[r.mode] || r.mode)
    : (r.stopping ? T(' · 上一条正在收尾…', ' · finishing the last recording…') : '');
  // 每一路一根电平条：录进文件的是什么就显示什么（audiocap 每半秒写一次）。你的麦克风出数字零、
  // 或者哪一路采集停了，当场标红——别等录完才发现（2026-10-13 那次 47 分钟没录上，录的时候看不出来）
  const parts = [];
  if (r.lost) {
    // 连不上服务就说连不上：别让页面停在最后一次「正常」上，电平条看着是绿的、实际没人在看
    parts.push(`<span class="meter bad">${T('连不上录音台服务，录音状态未知', "can't reach the Recording Desk server; recording status unknown")}</span>`);
  }
  const want = r.lost ? [] : ({ both: ['mic', 'sys'], sys: ['sys'], mic: ['mic'] }[r.mode] || ['mic', 'sys']);
  for (const [tag, who] of [['mic', T('我', 'Me')], ['sys', T('对方', 'Other')]]) {
    if (!r.on || !want.includes(tag)) continue;
    const lv = r.levels ? r.levels[tag] : null;
    // 该有的那一路连电平文件都没有：标红，不是不画
    if (!lv) { parts.push(`<span class="meter bad">${who}<span class="bar"><i style="width:0%"></i></span>${T('没数据', 'no data')}</span>`); continue; }
    // 用本机时钟判新鲜度：服务端的 now 是上一次回应时的，回应停了它就不走了，永远不会「过期」
    const now = Date.now() / 1000;
    const stale = now - (lv.last_frame_t || lv.t) > 10;   // 文件还在刷、帧却不来了，也算停了
    const zero = lv.zero_since > 0 ? now - lv.zero_since : 0;
    let cls = '', txt = '';
    if (stale) { cls = 'bad'; txt = T('采集停了', 'capture stopped'); }
    else if (tag === 'mic' && zero >= 3) { cls = 'bad'; txt = T('没信号', 'no signal'); }
    else if (zero >= 2) { cls = 'quiet'; txt = T('没声音', 'silent'); }
    const w = stale || lv.db <= -60 ? 0 : Math.round((lv.db + 60) / 60 * 100);
    parts.push(`<span class="meter ${cls}" title="${T(`${who}这一路：峰值 ${lv.db} dB`, `${who} track: peak ${lv.db} dB`)}">${who}<span class="bar"><i style="width:${w}%"></i></span>${txt}</span>`);
  }
  $('#meters').innerHTML = parts.join('');
  tickClock();
}

function tickClock() {
  const r = S.recording;
  if (r && r.on) $('#recclock').textContent = fmt(Date.now() / 1000 - r.start);
}

// ---------------------------------------------------------------- 右边：一条录音

function pending() { return (S.rex && S.rex.proof && S.rex.proof.unsure) || []; }

function renderDetail() {
  const r = S.rex, el = $('#detail');
  if (!r) return;
  const p = r.proof;
  const nPend = p ? p.unsure.length : 0;
  const failed = p ? p.failed.reduce((n, x) => n + x[1] - x[0] + 1, 0) : 0;
  let action = '';
  if (r.busy) action = `<button disabled><span class="spin"></span> ${T('处理中', 'Processing')}</button>`;
  else if (!r.entries.length) action = `<button class="primary" data-act="go">${T('开始处理', 'Process')}</button>`;
  else if (failed) action = `<button class="primary" data-act="go">${T(`补校没校的 ${failed} 行`, `Proofread the remaining ${plural(failed, 'line')}`)}</button>`;
  else if (!p || !r.analysis) action = `<button class="primary" data-act="go">${!p ? T('补做校对和分析', 'Run proofreading and analysis') : T('补做分析', 'Run analysis')}</button>`;
  const speakersN = new Set(r.entries.map(e => e.who).filter(Boolean)).size;
  const meta = [r.when, r.source + (r.origin && r.origin !== r.title ? T('：', ': ') + r.origin : ''),
    r.parts.length ? T(`由 ${r.parts.length} 段合成`, `joined from ${r.parts.length} recordings`) : '',
    speakersN > 1 ? speakersN + T(' 人', ' speakers') : '', r.kw && r.kw !== r.title ? T('关键词：', 'Keywords: ') + r.kw : ''].filter(Boolean).join(' · ');
  const tabs = `
        <button class="tab ${S.tab === 'text' ? 'on' : ''}" data-tab="text">${T('稿子', 'Transcript')}</button>
        <button class="tab ${S.tab === 'proof' ? 'on' : ''}" data-tab="proof">${T('校对', 'Proofreading')}${nPend ? `<span class="n">${nPend}</span>` : ''}</button>
        <button class="tab ${S.tab === 'analysis' ? 'on' : ''}" data-tab="analysis">${T('分析', 'Analysis')}</button>
        <button class="tab ${S.tab === 'chat' ? 'on' : ''}" data-tab="chat">${T('接着问', 'Ask')}${r.chat.length ? ` (${r.chat.length})` : ''}</button>`;
  // 同一条再画：只换按钮、标签和内容区。整页重画会把音频打断、把滚动位置甩回顶部——
  // 看到第 50 条按一下 Y 就回到开头，没法用
  if (el.dataset.key === r.key && $('#pane')) {
    $('#dact').innerHTML = action;
    $('#tabs').innerHTML = tabs;
    const top = el.scrollTop;
    renderPane();
    el.scrollTop = top;
    return;
  }
  el.dataset.key = r.key;
  el.innerHTML = `
    <div class="dhead">
      <div class="dtitle"><h2>${esc(r.title)}</h2><span id="dact">${action}</span><button class="ghost" data-act="reveal" title="${T('在访达中显示', 'Show in Finder')}">${T('访达', 'Finder')}</button><button class="ghost" data-act="export-docx" title="${T('把稿子下载成 Word', 'Download the transcript as Word')}">Word</button><button class="ghost" data-act="export-srt" title="${T('下载字幕（.srt，带名字、校对过）', 'Download subtitles (.srt, with names, proofread)')}">${T('字幕', 'Subtitles')}</button><button class="ghost" data-act="trash" title="${T('移到废纸篓（双击左边列表里的这一条也行）', 'Move to the Trash (or double-click it in the list on the left)')}">${T('删除', 'Delete')}</button></div>
      <div class="dmeta">${esc(meta)}</div>
      ${r.audio.length ? `<audio id="player" controls preload="metadata" data-key="${esc(r.key)}" data-i="0" src="/media?k=${encodeURIComponent(r.key)}&i=0${r.parts.length ? '&p=' + r.parts.length : ''}"></audio>
        ${r.audio.length > 1 ? `<div class="tracks">${T('分轨录音：', 'Separate tracks: ')}${r.audio.map((a, i) => `<button class="ghost" data-track="${i}">${/-sys/.test(a) ? T('电脑声音那轨', 'Computer audio track') : T('麦克风那轨', 'Microphone track')}</button>`).join('')}</div>` : ''}` : `<div class="muted">${T('没有音频文件', 'No audio file')}</div>`}
      <div class="tabs" id="tabs">${tabs}</div>
    </div>
    <div class="pane" id="pane"></div>`;
  bindPlayer();
  renderPane();
}

function renderPane() {
  const r = S.rex, el = $('#pane');
  if (!r || !el) return;
  if (S.tab === 'text') el.innerHTML = paneText(r);
  else if (S.tab === 'proof') el.innerHTML = paneProof(r);
  else if (S.tab === 'analysis') el.innerHTML = paneAnalysis(r);
  else el.innerHTML = paneChat(r);
  if (S.tab === 'chat') { const t = $('#ask'); if (t) t.focus(); }
}

function paneText(r) {
  if (!r.entries.length) return `<div class="notice info">${T('还没有转写。点右上角「开始处理」，或者在终端里 <code>rex go</code>。', 'Not transcribed yet. Click “Process” at the top right, or run <code>rex go</code> in a terminal.')}</div>`;
  const fixes = {}, pend = {};
  if (r.proof) {
    for (const x of r.proof.applied) (fixes[x.id] = fixes[x.id] || []).push(x);
    for (const x of r.proof.unsure) (pend[x.id] = pend[x.id] || []).push(x);
  }
  const parts = r.parts;
  let pi = 0;
  return r.entries.map(e => {
    let sep = '';
    while (pi < parts.length && e.a >= parts[pi].start - 0.5) sep += partSep(parts[pi], pi++);
    // by 是存在 .校对.json 里的固定值（claude / 你 / 你撤销），不翻译，照原样比
    const marks = (fixes[e.id] || []).map(x => ({ s: x.new, cls: 'fix', title: T(`原来是「${x.old}」${x.by === '你' ? '（你采纳的）' : ''}`, `Originally “${x.old}”${x.by === '你' ? ' (accepted by you)' : ''}`) }))
      .concat((pend[e.id] || []).map(x => ({ s: x.old, cls: 'pend', title: T(`可能是「${x.new}」：${x.why}`, `Maybe “${x.new}”: ${x.why}`) })));
    return sep + `<div class="line" id="L${e.id}" data-a="${e.a}"><span class="ts" data-t="${e.a}">${fmt(e.a)}</span>
      <div>${e.who ? `<span class="who" style="color:${color(e.who)}">${esc(e.who)}</span>` : ''}${marked(e.text, marks)}</div></div>`;
  }).join('');
}

// 几段合成的稿子：每段开头一条分隔，写着是第几段、什么时候录的、原来叫什么
function partSep(p, i) {
  const was = (p.name || '').replace(/\.[^.]+$/, '');
  return `<div class="partsep"><span>${T(`第 ${i + 1} 段`, `Part ${i + 1}`)}</span>${esc([p.recorded, dur(Math.round(p.duration || 0)),
    was ? T(`原来叫「${was}」`, `was “${was}”`) : ''].filter(Boolean).join(' · '))}</div>`;
}

function lineText(r, id) {
  const e = r.entries[id - 1];
  return e ? e.text : '';
}

// 长句只留那几个字前后各 40 字，不然一张卡片铺满半屏
function around(text, s, n = 40) {
  const i = text.indexOf(s);
  if (i < 0 || text.length <= s.length + 2 * n) return text;
  const a = Math.max(0, i - n), b = Math.min(text.length, i + s.length + n);
  return (a > 0 ? '…' : '') + text.slice(a, b) + (b < text.length ? '…' : '');
}

function paneProof(r) {
  const p = r.proof;
  if (!p) return `<div class="notice info">${T('还没有校对。', 'Not proofread yet.')}${r.entries.length ? T('点右上角的按钮补做。', ' Use the button at the top right to run it.') : ''}</div>`;
  const failed = p.failed.reduce((n, x) => n + x[1] - x[0] + 1, 0);
  let h = `<div class="sum"><span><span class="big">${p.applied.length}</span>${T('处改了', ' corrected')}</span>
    <span class="chip warn">${T(`待确认 ${p.unsure.length}`, `${p.unsure.length} to confirm`)}</span>
    ${p.rejected.length ? `<span class="chip">${T(`你没采纳 ${p.rejected.length}`, `${p.rejected.length} rejected`)}</span>` : ''}
    ${p.missed.length ? `<span class="chip">${T(`没对上原文 ${p.missed.length}`, `${p.missed.length} unmatched`)}</span>` : ''}</div>`;
  if (failed) {
    const ranges = p.failed.map(x => x[0] + T('~', '–') + x[1]).join(T('、', ', '));
    h += `<div class="notice">${T(`还有 ${failed} 行没校成（第 ${ranges} 行）。`, `${plural(failed, 'line')} not proofread (lines ${ranges}).`)}<button data-act="go">${T('现在补', 'Proofread now')}</button></div>`;
  }
  if (p.runs && p.runs.length) h += `<div class="muted" style="font-size:12px">${p.runs.map(x => esc(x.when + (x.note ? T('，', ', ') + x.note : ''))).join('<br>')}</div>`;
  if (p.unsure.length) {
    S.focus = Math.min(S.focus, p.unsure.length - 1);
    h += T(`<div class="h3">待你确认 <small>${p.unsure.length} 处 · Claude 拿不准，稿子里还是原文</small>
      <button class="acceptall" data-act="acceptall" title="剩下的建议一次全部采纳；之后每一条都还能在「改了的」里单独撤销">全部采纳（${p.unsure.length}）</button>
      <span class="keys"><kbd>Y</kbd> 采纳 <kbd>N</kbd> 不采纳 <kbd>J</kbd>/<kbd>K</kbd> 上下 <kbd>空格</kbd> 听这一句</span></div>`,
    `<div class="h3">To confirm <small>${p.unsure.length} · Claude is uncertain; the transcript still has the original</small>
      <button class="acceptall" data-act="acceptall" title="Accept all remaining suggestions at once; you can still undo each one under “Corrected”">Accept all (${p.unsure.length})</button>
      <span class="keys"><kbd>Y</kbd> Accept <kbd>N</kbd> Reject <kbd>J</kbd>/<kbd>K</kbd> Next/previous <kbd>Space</kbd> Play this line</span></div>`);
    h += p.unsure.map((x, i) => `
      <div class="card ${i === S.focus ? 'focus' : ''}" id="C${i}" data-i="${i}">
        <div class="ch"><span class="ts" data-t="${x.t}">${fmt(x.t)}</span> ${x.who ? `<span class="who" style="color:${color(x.who)}">${esc(x.who)}</span>` : ''}
          <del>${esc(x.old)}</del> → <ins>${esc(x.new)}</ins></div>
        <div class="acts"><button data-rid="${x.rid}" data-do="accept">${T('采纳', 'Accept')}</button><button class="ghost" data-rid="${x.rid}" data-do="reject">${T('不采纳', 'Reject')}</button></div>
        <div class="why">${esc(x.why)}</div>
        <div class="ctx">${marked(around(lineText(r, x.id), x.old), [{ s: x.old, cls: 'pend', title: '' }])}</div>
      </div>`).join('');
  }
  if (p.applied.length) {
    h += T(`<div class="h3">改了的 <small>${p.applied.length} 处 · 点「撤销」就改回原文</small></div>`,
      `<div class="h3">Corrected <small>${p.applied.length} · click “Undo” to restore the original</small></div>`);
    h += p.applied.map(x => `<div class="row"><span class="ts" data-t="${x.t}">${fmt(x.t)}</span>
      <div class="ch"><del>${esc(x.old)}</del> → <ins>${esc(x.new)}</ins><span class="why">${esc(x.why)}${x.by === '你' ? T(' · 你采纳的', ' · accepted by you') : ''}</span></div>
      <button class="ghost" data-rid="${x.rid}" data-do="undo">${T('撤销', 'Undo')}</button></div>`).join('');
  }
  if (p.rejected.length) {
    h += T(`<div class="h3">你没采纳的 <small>${p.rejected.length} 处</small></div>`,
      `<div class="h3">Rejected <small>${p.rejected.length}</small></div>`);
    h += p.rejected.map(x => `<div class="row"><span class="ts" data-t="${x.t}">${fmt(x.t)}</span>
      <div class="ch"><del>${esc(x.old)}</del> → <ins>${esc(x.new)}</ins><span class="why">${esc(x.why)}</span></div>
      <button class="ghost" data-rid="${x.rid}" data-do="accept">${T('采纳', 'Accept')}</button></div>`).join('');
  }
  if (p.missed.length) {
    h += T(`<div class="h3">没对上原文的 <small>Claude 引的原文在那一行里找不到，没改</small></div>`,
      `<div class="h3">Unmatched <small>the original Claude quoted isn't in that line; not changed</small></div>`);
    h += p.missed.map(x => `<div class="row"><span class="ts" data-t="${x.t}">${fmt(x.t)}</span>
      <div class="ch">${esc(x.old)} → ${esc(x.new)}<span class="why">${esc(x.why)}</span></div><span></span></div>`).join('');
  }
  return h;
}

function paneAnalysis(r) {
  if (!r.analysis) return `<div class="notice info">${T('还没有分析。点右上角的按钮补做。', 'No analysis yet. Use the button at the top right to run it.')}</div>`;
  const cut = r.analysis.indexOf('\n---\n');
  const head = cut >= 0 ? r.analysis.slice(0, cut) : '';
  const body = cut >= 0 ? r.analysis.slice(cut + 5) : r.analysis;
  // 报告头是 analyze.py 按它当时的语言写的，和现在界面是什么语言无关：两种都认
  const used = (head.match(/^- (?:用量：|Usage: )(.*)$/m) || [])[1];
  return (used ? `<div class="muted" style="font-size:12px;margin-bottom:8px">${T('用量：', 'Usage: ')}${esc(used)}</div>` : '') +
    `<div class="md">${md(body)}</div>`;
}

function paneChat(r) {
  if (!r.has_session) return `<div class="notice info">${T('这条还没有分析，先处理它，分析会开一个能接着问的会话。', 'No analysis yet. Process it first: the analysis opens a session you can keep asking questions in.')}</div>`;
  return `<div class="chat">
    ${r.chat.length ? '' : `<div class="muted">${T('分析那个会话里有整份稿子、校对报告和第一轮分析。问什么都行：「第 40 分钟那段他到底什么意思」「把我说的计划列出来」。', 'The analysis session has the whole transcript, the proofreading report and the first analysis. Ask anything: “What did he really mean around minute 40?” “List the plans I mentioned.”')}</div>`}
    ${r.chat.map(t => `<div class="q">${esc(t.q)}</div><div class="a md">${md(t.a)}</div>`).join('')}
    <div class="ask"><textarea id="ask" placeholder="${T('问点什么…（⌘↩ 发送）', 'Ask something… (⌘↩ to send)')}"></textarea><button class="primary" id="send">${T('问', 'Ask')}</button></div>
    ${r.chat.length ? `<label class="fresh" title="${T('从分析刚做完的那一刻分叉出一个新会话再问：前面这些问答不再带进去（跑偏了、答非所问时用）。原来的会话和问答都留着', 'Fork a new session from the moment the analysis finished, then ask: the questions above are left out (use it when the chat went off track). The old session and answers are kept')}"><input type="checkbox" id="fresh"> ${T('从分析重新开始', 'Start over from the analysis')}</label>` : ''}
  </div>`;
}

// ---------------------------------------------------------------- 播放

function player() { return $('#player'); }

function seek(t, play = true) {
  const a = player();
  if (!a || t === '' || t == null) return;
  a.currentTime = Number(t);
  if (play) a.play();
}

function bindPlayer() {
  const a = player();
  if (!a) return;
  a.addEventListener('timeupdate', () => {
    if (S.tab !== 'text' || !S.rex) return;
    const t = a.currentTime, es = S.rex.entries;
    let lo = 0, hi = es.length - 1, k = -1;
    while (lo <= hi) { const mid = (lo + hi) >> 1; if (es[mid].a <= t + 0.05) { k = mid; lo = mid + 1; } else hi = mid - 1; }
    const cur = document.querySelector('.line.now');
    const el = k >= 0 ? document.getElementById('L' + es[k].id) : null;
    if (cur === el) return;
    if (cur) cur.classList.remove('now');
    if (el) {
      el.classList.add('now');
      if (!a.paused && Date.now() - S.lastScroll > 4000) {
        const box = $('#detail').getBoundingClientRect(), r = el.getBoundingClientRect();
        if (r.top < box.top + 160 || r.bottom > box.bottom - 40) el.scrollIntoView({ block: 'center', behavior: 'smooth' });
      }
    }
  });
}

function flashLine(t) {
  if (!S.rex) return;
  const es = S.rex.entries;
  let best = null;
  for (const e of es) { if (e.a <= t + 0.5) best = e; else break; }
  if (!best) return;
  const el = document.getElementById('L' + best.id);
  if (!el) return;
  el.scrollIntoView({ block: 'center' });
  el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash');
}

// ---------------------------------------------------------------- 数据

async function refresh() {
  const j = await api('/api/state');
  if (!j.ok) {
    S.fails = (S.fails || 0) + 1;
    if (S.fails >= 2 && S.recording) renderRecording({ ...S.recording, lost: true });
    return;
  }
  S.fails = 0;
  S.list = j.recordings;
  const nPicked = S.picked.size;
  for (const k of [...S.picked]) if (!S.list.some(r => r.key === k)) S.picked.delete(k);
  if (S.picked.size !== nPicked) renderPickbar();     // 没变就别重画：正要点「合成一条…」时按钮被换掉，这一下就丢了
  renderRecording(j.recording);
  renderJobs(j.jobs, j.inbox);
  if (!S.results) renderList();
  if (S.want) {                       // 打开页面时网址里带着某一条（见 syncHash）
    const w = S.want; S.want = null;
    if (!S.sel && S.list.some(r => r.key === w.key)) { S.pendingTab = w.tab; select(w.key); }
  }
  if (S.joinWatch) followJoin(j.jobs);
  // 转写完会按关键词改名（X → X_关键词）；合成一条之后，原来那几条收进了「已合并」。
  // 选中的那条从列表里消失了，就跟到新名字上、合成的那条上
  if (S.sel && !S.list.some(r => r.key === S.sel)) {
    const moved = S.list.find(r => r.key.startsWith(S.sel + '_')) || S.list.find(r => r.joined_from.includes(S.sel));
    if (moved) { S.sel = moved.key; $('#detail').dataset.key = ''; if (!S.results) renderList(); loadDetail(S.sel, true); return; }
  }
  if (S.sel && S.rex) {
    const cur = S.list.find(r => r.key === S.sel);
    if (cur && stale(cur, S.rex)) loadDetail(S.sel, true);
  }
}

// 列表里这条的状态和右边显示的对不上吗（处理完了、别处改了报告……）
function stale(cur, rex) {
  const p = rex.proof;
  const shown = [rex.busy, rex.entries.length > 0, !!rex.analysis, rex.chat.length,
    p ? p.applied.length : -1, p ? p.unsure.length : -1, rex.parts.length];
  const now = [cur.busy, cur.transcribed, cur.analyzed, cur.chats,
    cur.proof ? cur.proof.applied : -1, cur.proof ? cur.proof.unsure : -1, cur.parts];
  return JSON.stringify(shown) !== JSON.stringify(now);
}

async function loadDetail(key, keepTab) {
  const j = await api('/api/rex?k=' + encodeURIComponent(key));
  if (!j.ok) { toast(j.msg || T('打不开这条', "Couldn't open this recording"), 'bad'); return; }
  if (S.sel !== key) return;
  if (!keepTab) { S.tab = S.pendingTab || 'text'; S.pendingTab = null; S.focus = 0; }
  if (S.rex && S.rex.key === key && S.rex.parts.length !== j.rex.parts.length) $('#detail').dataset.key = '';  // 换成了合成的那条：整个重画
  S.rex = j.rex;
  renderDetail();
  syncHash();
}

// 网址里记着选中的是哪条、哪一页（#录音名/页签）：刷新页面还停在原处，也能直接打开某一条
const TABS = ['text', 'proof', 'analysis', 'chat'];
function syncHash() {
  const h = S.sel ? '#' + encodeURIComponent(S.sel) + (S.tab && S.tab !== 'text' ? '/' + S.tab : '') : '';
  if (location.hash !== h) history.replaceState(null, '', h || location.pathname);
}
function wantedFromHash() {
  const [k, tab] = location.hash.slice(1).split('/');
  try { return k ? { key: decodeURIComponent(k), tab: TABS.includes(tab) ? tab : 'text' } : null; } catch (e) { return null; }
}

function select(key, t) {
  if (S.sel !== key) {
    S.sel = key; S.rex = null;
    $('#detail').dataset.key = '';
    renderList();
    $('#detail').innerHTML = '<div class="empty"><span class="spin"></span></div>';
    loadDetail(key).then(() => { if (t !== undefined && t !== '') { S.tab = 'text'; renderDetail(); seek(t, false); flashLine(Number(t)); } });
  } else if (t !== undefined && t !== '') {
    S.tab = 'text'; renderDetail(); seek(t, false); flashLine(Number(t));
  }
}

// 整条录音（音频、稿子、校对、分析）移到废纸篓。先问一句；录着的、正在处理的服务端会拒绝
async function trashRec(key) {
  if (!key) return;
  const r = S.list.find(x => x.key === key) || {};
  if (!confirm(T(`把「${r.title || key}」移到废纸篓？\n\n音频和它的稿子、校对、分析会一起移走。删错了可以在访达的废纸篓里「放回原处」。`,
    `Move “${r.title || key}” to the Trash?\n\nThe audio goes together with its transcript, proofreading and analysis. If this was a mistake, open the Trash in Finder and use “Put Back”.`))) return;
  const j = await api('/api/trash', { key });
  toast(j.msg, j.ok ? 'ok' : 'bad', j.ok ? 7000 : 5000);
  if (!j.ok) return;
  if (S.sel === key) {
    S.sel = null; S.rex = null; syncHash();
    $('#detail').dataset.key = '';
    $('#detail').innerHTML = `<div class="empty">${T('选一条录音', 'Select a recording')}</div>`;
  }
  refresh();
}

// 「全部采纳」：剩下的建议一次收下。先问一句；原文找不到、或者在那一行出现不止一次的，服务端会跳过、留在待确认里
// 下载 Word / 字幕。先取回来再存：直接跳到下载地址的话，没有稿子时整页会换成一段报错
async function exportRec(fmt) {
  const key = S.sel;
  if (!key) return;
  let r;
  try { r = await fetch('/api/export?fmt=' + fmt + '&k=' + encodeURIComponent(key)); } catch (e) {
    toast(T('连不上录音台服务（rex app 关了？）', "Can't reach the Recording Desk server (is rex app stopped?)"), 'bad'); return;
  }
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    toast(j.msg || ('HTTP ' + r.status), 'bad'); return;
  }
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement('a');
  a.href = url; a.download = key + '.' + fmt;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
  if (fmt === 'docx') toast(T('Word 也存了一份在录音旁边', 'A copy of the Word file is also saved next to the recording'), 'ok');
}

async function acceptAll() {
  const n = pending().length;
  if (!n) return;
  if (!confirm(T(`把剩下的 ${n} 条建议全部采纳？\n\n稿子会照着改。之后在「改了的」里，每一条都还能单独撤销。`,
                 `Accept all ${n} remaining suggestions?\n\nThe transcript will be changed accordingly. You can still undo each one under “Corrected”.`))) return;
  const j = await api('/api/decide_all', { key: S.sel, action: 'accept' });
  toast(j.msg, j.ok ? (j.skipped ? '' : 'ok') : 'bad', j.ok ? 7000 : 5000);
  if (!j.ok && !j.done) return;
  S.focus = 0;
  await loadDetail(S.sel, true);
  refresh();
}

async function decide(rid, action) {
  const j = await api('/api/decide', { key: S.sel, rid: Number(rid), action });
  if (!j.ok) { toast(j.msg, 'bad'); return; }
  await loadDetail(S.sel, true);
  const el = document.getElementById('C' + S.focus);
  if (el && S.tab === 'proof') el.scrollIntoView({ block: 'nearest' });
  refresh();
}

async function sendChat() {
  const t = $('#ask'), q = t.value.trim();
  if (!q) return;
  const fresh = !!($('#fresh') && $('#fresh').checked);
  if (fresh && !confirm(T('从分析刚做完的那一刻重新开始问？上面这些问答会收起来，接下来的问题不再接着它们。',
                          'Start over from the moment the analysis finished? The questions above are put away and the next ones no longer follow them.'))) return;
  t.disabled = true; $('#send').disabled = true;
  $('#send').innerHTML = `<span class="spin"></span> ${T('想着呢', 'Thinking…')}`;
  const wait = document.createElement('div');
  wait.className = 'q'; wait.textContent = q;
  t.parentElement.before(wait);
  const j = await api('/api/chat', { key: S.sel, q, fresh });
  if (!j.ok) { toast(j.msg, 'bad'); t.disabled = false; $('#send').disabled = false; $('#send').textContent = T('问', 'Ask'); wait.remove(); return; }
  if (j.warn) toast(j.warn, 'bad', 10000);
  await loadDetail(S.sel, true);
  const box = $('#detail'); box.scrollTop = box.scrollHeight;
}

// ---------------------------------------------------------------- 合成一条（rex join）

// 列表里 ⌘ 点选的几条，或者一次拖进来的几个文件：按时间排好、可以上下挪，接成一条再一起处理。
// 怎么接、已经转写过的稿子怎么接上，见 rex_join.py；这里只管排顺序、起名字、传文件
function joinPicked() {
  const items = [...S.picked].map(k => S.list.find(r => r.key === k)).filter(Boolean).map(r => ({
    key: r.key, title: r.title, when: r.when, duration: r.duration,
    named: !!((r.origin && r.origin !== 'drop') || r.kw),      // 有名字（导入时的原名、关键词），不只是「麦克风」这种来源
  }));
  if (items.length >= 2) openJoin(items, false);
}

function joinFiles(files) {
  const day = t => { const d = new Date(t), p = n => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`; };
  openJoin(files.map(f => ({ file: f, title: f.name, when: day(f.lastModified || Date.now()), t: f.lastModified || 0, size: f.size, named: true })), true);
}

function openJoin(items, upload) {
  // 按开录时间排；同一分钟的按名字（「新录音 9」排在「新录音 10」前面）
  items.sort((a, b) => (a.t || 0) - (b.t || 0) || a.when.localeCompare(b.when) || (a.key || a.title).localeCompare(b.key || b.title, undefined, { numeric: true }));
  S.join = { items, upload, name: '', edited: false, busy: false, xhr: null };
  S.join.name = joinDefaultName();
  renderJoin();
  $('#joindlg').showModal();
  if (upload) probeDurations(S.join);
}

function joinDefaultName() {
  const x = S.join.items[0];
  return x && x.named ? x.title.replace(/\.[^.]+$/, '') : '';
}

function joinMeta(x) {
  return [x.when, dur(Math.round(x.duration || 0)), x.size ? mb(x.size) : ''].filter(Boolean).join(' · ');
}

function renderJoin() {
  const J = S.join, n = J.items.length, lock = J.busy ? 'disabled' : '';
  $('#joinform').innerHTML = `
    <h3>${J.upload ? T(`拖进来 ${n} 个文件`, `${n} files dropped`) : T(`把 ${n} 条合成一条`, `Join ${n} recordings into one`)}</h3>
    <p class="muted">${T('按下面的顺序首尾接成一条，再一起转写、校对、分析：一份稿子、一份分析。', 'They are joined end to end in this order, then transcribed, proofread and analyzed together: one transcript, one analysis.')}</p>
    <ol class="jlist">${J.items.map((x, i) => `<li>
      <div class="pt"><div>${esc(x.title)}</div><div class="muted" id="jm${i}">${esc(joinMeta(x))}</div></div>
      <span class="pct" id="jp${i}"></span>
      <button type="button" class="ghost" data-mv="${i}" data-d="-1" ${i && !J.busy ? '' : 'disabled'} title="${T('往前挪', 'Move up')}">↑</button>
      <button type="button" class="ghost" data-mv="${i}" data-d="1" ${i < n - 1 && !J.busy ? '' : 'disabled'} title="${T('往后挪', 'Move down')}">↓</button></li>`).join('')}</ol>
    <label class="jname"><span>${T('名字', 'Name')}</span><input id="jname" maxlength="60" value="${esc(J.name)}" ${lock}
      placeholder="${T('可以不填：转写完按关键词起', 'Optional: named after its keywords once transcribed')}"></label>
    <p class="muted small">${J.upload ? T('这几个文件合成以后收进 ~/Recordings/已合并/。', 'After joining, these files are kept in ~/Recordings/已合并/.')
      : T('原来那几条收进 ~/Recordings/已合并/，不删。已经转写、校对过的接着用，不重新转写。', 'The originals are moved to ~/Recordings/已合并/ (nothing is deleted). Transcripts and proofreading already done are reused, not redone.')}</p>
    <div class="jacts">
      ${J.upload ? `<button type="button" data-act="join-apart" ${lock} title="${T('一个一个放进收件箱，各自处理', 'Put them in the inbox one by one, each processed on its own')}">${T('分开处理', 'Process separately')}</button>` : ''}
      <span class="sp"></span>
      <button type="button" class="ghost" data-act="join-cancel">${T('取消', 'Cancel')}</button>
      <button type="submit" class="primary" id="jgo" ${lock}>${J.busy ? `<span class="spin"></span> ${J.upload ? T('上传中…', 'Uploading…') : T('排队中…', 'Queuing…')}` : T('合成一条', 'Join into one')}</button>
    </div>`;
}

function moveJoin(i, d) {
  const J = S.join, it = J.items, j = i + d;
  if (!J || J.busy || j < 0 || j >= it.length) return;
  [it[i], it[j]] = [it[j], it[i]];
  if (!J.edited) J.name = joinDefaultName();          // 名字没改过就跟着第一段走
  renderJoin();
  const b = $(`#joinform [data-mv="${j}"][data-d="${d}"]`);
  (b && !b.disabled ? b : $('#jgo')).focus();
}

// 拖进来的文件在浏览器里先读出时长，列表里好核对是不是那几段
function probeDurations(J) {
  for (const x of J.items) {
    const url = URL.createObjectURL(x.file), a = new Audio();
    a.preload = 'metadata';
    a.onloadedmetadata = () => {
      URL.revokeObjectURL(url);
      if (S.join !== J || !isFinite(a.duration)) return;
      x.duration = a.duration;
      const el = $('#jm' + J.items.indexOf(x));
      if (el) el.textContent = joinMeta(x);
    };
    a.onerror = () => URL.revokeObjectURL(url);
    a.src = url;
  }
}

function closeJoin() {
  const J = S.join;
  S.join = null;
  if (J && J.xhr) J.xhr.abort();                      // 传到一半取消：runJoin 那边收到 aborted，把这一组收掉
  if ($('#joindlg').open) $('#joindlg').close();
}

// 传一个文件到暂存区的这一组（不进收件箱），等这一组都传完再合成
function putFile(J, file, group, onpct) {
  return new Promise(resolve => {
    const x = new XMLHttpRequest();
    J.xhr = x;
    x.open('POST', `/api/upload?group=${group}&name=${encodeURIComponent(file.name)}`);
    x.setRequestHeader('X-Rex-App', '1');
    x.setRequestHeader('X-Rex-Mtime', String((file.lastModified || 0) / 1000));   // 合成时按它定开录时刻
    x.upload.onprogress = e => { if (e.lengthComputable) onpct(Math.round(e.loaded / e.total * 100)); };
    const done = r => { J.xhr = null; resolve(r); };
    x.onload = () => { let j = {}; try { j = JSON.parse(x.responseText); } catch (e) { /* 下面统一报 */ } done(j.ok ? j : { ok: false, msg: j.msg }); };
    x.onerror = () => done({ ok: false, msg: T('没传上：连不上服务', "Upload failed: can't reach the server") });
    x.onabort = () => done({ ok: false, aborted: true });
    x.send(file);
  });
}

async function runJoin() {
  const J = S.join;
  if (!J || J.busy) return;
  J.name = $('#jname').value.trim();
  J.busy = true;
  renderJoin();
  let j, ids;
  if (J.upload) {
    const group = [...crypto.getRandomValues(new Uint8Array(8))].map(b => b.toString(16).padStart(2, '0')).join('');
    ids = [];
    for (let i = 0; i < J.items.length; i++) {
      const r = await putFile(J, J.items[i].file, group, pct => { const el = $('#jp' + i); if (el) el.textContent = pct + '%'; });
      if (!r.ok) {
        api('/api/join/cancel', { group });           // 已经传上来的那几个移到废纸篓
        if (!r.aborted) toast(r.msg || T('没传上', 'Upload failed'), 'bad', 8000);
        J.busy = false;
        if (S.join === J) renderJoin();
        return;
      }
      ids.push(r.name);                                // 重名的会被改成「名字-2」：以服务端回的为准
      const el = $('#jp' + i); if (el) el.textContent = '✓';
    }
    j = await api('/api/join', { group, files: ids, name: J.name });
    if (!j.ok) api('/api/join/cancel', { group });
  } else {
    ids = J.items.map(x => x.key);
    j = await api('/api/join', { keys: ids, name: J.name });
  }
  J.busy = false;
  if (!j.ok) { toast(j.msg, 'bad', 8000); if (S.join === J) renderJoin(); return; }
  toast(j.msg, 'ok', 8000);
  S.joinWatch = { ids, job: j.job, sel: S.sel };
  S.picked.clear(); renderPickbar(); renderList();
  closeJoin();
  refresh();
}

// 合成好了就打开它（这期间你没去看别的那条的话）；没合成成就说一声
function followJoin(jobs) {
  const w = S.joinWatch;
  const hit = S.list.find(r => r.parts && w.ids.every(x => r.joined_from.includes(x)));
  const job = jobs.find(x => x.id === w.job);
  if (hit) {
    S.joinWatch = null;
    if (!S.sel || S.sel === w.sel || w.ids.includes(S.sel) || !S.list.some(r => r.key === S.sel)) select(hit.key);
    else toast(T(`合成好了：${hit.title}`, `Joined: ${hit.title}`), 'ok', 8000);
  } else if (!job || job.state === '出错' || job.state === '完成') {
    S.joinWatch = null;
    if (job && job.state === '出错') toast(T('合成没成功，原因在左下「正在做的事」里', "Joining failed; the reason is under “Jobs” at the bottom left"), 'bad', 10000);
  }
}

// ---------------------------------------------------------------- 上传、录音、手机、登录

function upload(file) {
  const ext = (file.name.split('.').pop() || '').toLowerCase();
  if (!AUDIO_EXT.includes(ext)) { toast(T(`${file.name} 不是音视频文件，没放进去`, `${file.name} is not an audio or video file; not added`), 'bad'); return; }
  const note = document.createElement('div');
  note.className = 'toast'; note.textContent = T(`上传 ${file.name} …`, `Uploading ${file.name} …`);
  $('#toasts').appendChild(note);
  const x = new XMLHttpRequest();
  x.open('POST', '/api/upload?name=' + encodeURIComponent(file.name));
  x.setRequestHeader('X-Rex-App', '1');
  x.setRequestHeader('X-Rex-Mtime', String((file.lastModified || 0) / 1000));   // 收件箱按原文件的时间起名
  x.upload.onprogress = e => { if (e.lengthComputable) note.textContent = T(`上传 ${file.name} … ${Math.round(e.loaded / e.total * 100)}%`, `Uploading ${file.name} … ${Math.round(e.loaded / e.total * 100)}%`); };
  x.onload = () => {
    let j = {}; try { j = JSON.parse(x.responseText); } catch (e) { /* 下面统一报 */ }
    note.remove();
    if (j.ok) { toast(j.msg + T('\n转写 → 分人 → 校对 → 分析，做完左边会更新', "\nTranscribe → speakers → proofread → analyze. The list on the left updates when it's done"), 'ok', 8000); refresh(); }
    else toast(j.msg || T('没传上', 'Upload failed'), 'bad');
  };
  x.onerror = () => { note.remove(); toast(T('没传上：连不上服务', "Upload failed: can't reach the server"), 'bad'); };
  x.send(file);
}

async function startRec(mode) {
  if (S.starting) return;                        // 开录要几秒，这期间别让第二下进来
  S.starting = true;
  $('#recbar').classList.add('busy');
  toast({
    both: T('正在开始：录你的麦克风 + 电脑声音…', 'Starting: your microphone + computer audio…'),
    sys: T('正在开始：只录电脑声音（不录你的麦克风）…', 'Starting: computer audio only (not your microphone)…'),
    mic: T('正在开始：只录你的麦克风…', 'Starting: your microphone only…'),
  }[mode], '', 3000);
  try {
    const j = await api('/api/record', { mode });
    toast(j.msg || (j.ok ? T('开始录了', 'Recording started') : T('没开起来', "Couldn't start recording")), j.ok ? 'ok' : 'bad', j.ok ? 6000 : 12000);
  } finally {
    S.starting = false;
    $('#recbar').classList.remove('busy');
    refresh();
  }
}

async function stopRec() {
  $('#stop').disabled = true;
  const j = await api('/api/stop', {});
  $('#stop').disabled = false;
  toast(j.msg || T('停了', 'Stopped'), j.ok ? 'ok' : 'bad', 15000);
  await refresh();
  if (S.list.length) select(S.list[0].key);
}

async function loadPhone() {
  const el = $('#phone');
  el.innerHTML = '<span class="spin"></span>';
  const j = await api('/api/phone');
  if (!j.ok) { el.textContent = j.msg; return; }
  el.innerHTML = j.items.map(x => `<div class="phone-row"><div class="pt"><div>${esc(x.title || T('iPhone 录音', 'iPhone recording'))}</div>
    <div>${esc(x.when)} · ${esc(dur(x.duration))}</div></div>
    ${x.imported ? `<span class="chip ok">${T('已导入', 'Imported')}</span>` : `<button data-phone="${esc(x.path)}" data-stamp="${esc(x.stamp)}">${T('导入', 'Import')}</button>`}</div>`).join('') || T('没有', 'None');
}

async function loadLogin() {
  const j = await api('/api/login');
  const el = $('#login');
  if (j.ok && j.login.loggedIn) { el.textContent = T(`Claude 已登录${j.login.plan ? '（' + j.login.plan + '）' : ''}`, `Claude logged in${j.login.plan ? ' (' + j.login.plan + ')' : ''}`); el.className = 'login'; el.title = j.login.email; }
  else { el.textContent = T('Claude 没登录：终端里 rex login', 'Claude not logged in: run rex login in a terminal'); el.className = 'login no'; }
}

// ---------------------------------------------------------------- 事件

document.addEventListener('click', e => {
  const t = e.target.closest('[data-t]');
  if (t && t.classList.contains('ts') && t.dataset.key) { select(t.dataset.key, t.dataset.t); return; }
  if (t && (t.classList.contains('ts') || t.classList.contains('tlink'))) { seek(t.dataset.t); if (S.tab === 'text') flashLine(Number(t.dataset.t)); return; }
  const item = e.target.closest('.item');
  if (item) {
    // 双击 = 移到废纸篓。不用浏览器的 dblclick：第一下点击会重画列表，第二下落在新元素上，浏览器认不出是双击；
    // 这里按「同一条、450 毫秒内点两下」自己判
    const k = item.dataset.key, now = Date.now();
    // ⌘ 点：挑几条合成一条。不算进双击（连着 ⌘ 点两下不能是「删除」），也不换右边
    if ((e.metaKey || e.ctrlKey) && !S.results) { S.lastClick = null; togglePick(k); return; }
    if (S.lastClick && S.lastClick.key === k && now - S.lastClick.t < 450) { S.lastClick = null; trashRec(k); return; }
    S.lastClick = { key: k, t: now };
    select(k); return;
  }
  const tab = e.target.closest('[data-tab]');
  if (tab) { S.tab = tab.dataset.tab; document.querySelectorAll('.tab').forEach(b => b.classList.toggle('on', b === tab)); renderPane(); syncHash(); return; }
  const dec = e.target.closest('[data-do]');
  if (dec) { decide(dec.dataset.rid, dec.dataset.do); return; }
  const card = e.target.closest('.card');
  if (card) { S.focus = Number(card.dataset.i); document.querySelectorAll('.card').forEach(c => c.classList.toggle('focus', c === card)); }
  const mv = e.target.closest('[data-mv]');
  if (mv) { moveJoin(Number(mv.dataset.mv), Number(mv.dataset.d)); return; }
  const act = e.target.closest('[data-act]');
  if (act && act.dataset.act === 'join') { joinPicked(); return; }
  if (act && act.dataset.act === 'unpick') { S.picked.clear(); renderPickbar(); renderList(); return; }
  if (act && act.dataset.act === 'join-cancel') { closeJoin(); return; }
  if (act && act.dataset.act === 'join-apart') { const files = S.join.items.map(x => x.file); closeJoin(); files.forEach(upload); return; }
  if (act && act.dataset.act === 'go') { api('/api/go', { key: S.sel }).then(j => { toast(j.msg, j.ok ? 'ok' : 'bad'); refresh(); }); return; }
  if (act && act.dataset.act === 'reveal') { api('/api/reveal', { key: S.sel }); return; }
  if (act && (act.dataset.act === 'export-docx' || act.dataset.act === 'export-srt')) { exportRec(act.dataset.act.slice(7)); return; }
  if (act && act.dataset.act === 'trash') { trashRec(S.sel); return; }
  if (act && act.dataset.act === 'acceptall') { acceptAll(); return; }
  const tr = e.target.closest('[data-track]');
  if (tr) { const a = player(); a.dataset.i = tr.dataset.track; const t0 = a.currentTime; a.src = `/media?k=${encodeURIComponent(S.sel)}&i=${tr.dataset.track}`; a.addEventListener('loadedmetadata', () => { a.currentTime = t0; }, { once: true }); return; }
  const rb = e.target.closest('.recbtn');
  if (rb) { startRec(rb.dataset.mode); return; }
  if (e.target.id === 'stop') { stopRec(); return; }
  if (e.target.id === 'send') { sendChat(); return; }
  const ph = e.target.closest('[data-phone]');
  if (ph) { ph.disabled = true; api('/api/phone/import', { path: ph.dataset.phone, stamp: ph.dataset.stamp }).then(j => { toast(j.msg, j.ok ? 'ok' : 'bad'); refresh(); }); }
});

document.addEventListener('keydown', e => {
  const typing = /^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName);
  if (e.target.id === 'ask' && e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); sendChat(); return; }
  if ($('#joindlg').open) return;                    // 对话框挡在前面：Y / N 不能落到后面的校对上
  if (e.key === 'Escape' && S.picked.size && !typing) { S.picked.clear(); renderPickbar(); renderList(); return; }
  if (typing || e.metaKey || e.ctrlKey || e.altKey || S.tab !== 'proof') return;
  const list = pending();
  if (!list.length) return;
  const k = e.key.toLowerCase();
  if (k === 'j' || k === 'k') {
    S.focus = Math.max(0, Math.min(list.length - 1, S.focus + (k === 'j' ? 1 : -1)));
    document.querySelectorAll('.card').forEach(c => c.classList.toggle('focus', Number(c.dataset.i) === S.focus));
    const el = document.getElementById('C' + S.focus); if (el) el.scrollIntoView({ block: 'nearest' });
    e.preventDefault();
  } else if (k === 'y' || k === 'n') {
    decide(list[S.focus].rid, k === 'y' ? 'accept' : 'reject'); e.preventDefault();
  } else if (k === ' ') {
    seek(list[S.focus].t); e.preventDefault();
  }
});

$('#detail').addEventListener('scroll', () => { S.lastScroll = Date.now(); }, { passive: true });

let searchTimer = 0;
$('#search').addEventListener('input', e => {
  clearTimeout(searchTimer);
  const q = e.target.value.trim();
  if (!q) { S.results = null; renderList(); return; }
  searchTimer = setTimeout(async () => {
    const j = await api('/api/search?q=' + encodeURIComponent(q));
    if (j.ok && $('#search').value.trim() === q) { S.results = j.results; renderList(); }
  }, 300);
});

$('#phonebox').addEventListener('toggle', e => { if (e.target.open && !S.phoneLoaded) { S.phoneLoaded = true; loadPhone(); } });

// 拖文件：整个窗口都接。拖进来的要是文字（访达会存成 .textClipping），直接说清楚
let dragDepth = 0;
window.addEventListener('dragenter', e => {
  e.preventDefault(); dragDepth++;
  const n = [...((e.dataTransfer && e.dataTransfer.items) || [])].filter(x => x.kind === 'file').length;
  $('#overlay div').textContent = n >= 2 ? T('松手：可以合成一条，也可以分开处理', 'Drop: join them into one, or process them separately') : T('松手，放进收件箱', 'Drop to put it in the inbox');
  $('#overlay').classList.add('on');
});
window.addEventListener('dragleave', e => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) $('#overlay').classList.remove('on'); });
window.addEventListener('dragover', e => e.preventDefault());
window.addEventListener('drop', e => {
  e.preventDefault(); dragDepth = 0; $('#overlay').classList.remove('on');
  const files = [...(e.dataTransfer.files || [])];
  if (S.join) { toast(T('先把「合成一条」那个框关掉，再拖', 'Close the “Join” dialog first, then drop again'), 'bad'); return; }
  if (!files.length) { toast(T('拖进来的不是文件（像是一段文字）。在访达里拖那个音频文件的图标', "What you dropped isn't a file (it looks like text). Drag the audio file's icon from Finder"), 'bad', 8000); return; }
  const audio = files.filter(f => AUDIO_EXT.includes((f.name.split('.').pop() || '').toLowerCase()));
  files.filter(f => !audio.includes(f)).forEach(upload);    // 不是音视频的：upload 会说一声
  if (audio.length >= 2) joinFiles(audio);                  // 几个一起拖进来：问一句合成一条还是分开
  else audio.forEach(upload);
});

$('#joinform').addEventListener('submit', e => { e.preventDefault(); runJoin(); });
$('#joinform').addEventListener('input', e => { if (e.target.id === 'jname' && S.join) { S.join.name = e.target.value; S.join.edited = true; } });
$('#joindlg').addEventListener('close', () => { if (S.join) closeJoin(); });    // Esc 关掉的

setInterval(() => { if (S.recording && S.recording.on) refresh(); }, 1000);   // 录音时电平条一秒刷一次
setInterval(() => { if (!S.recording || !S.recording.on) refresh(); }, 2500);
setInterval(tickClock, 1000);
S.want = wantedFromHash();
refresh();
loadLogin();
