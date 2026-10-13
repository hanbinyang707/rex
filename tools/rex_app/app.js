// 录音台的页面逻辑。只负责画界面、把按钮翻译成请求；判断和改文件都在 rex_app.py / proofread.py 里。
'use strict';

const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const AUDIO_EXT = ['m4a', 'wav', 'qta', 'mp3', 'aac', 'flac', 'ogg', 'opus', 'caf', 'aiff', 'aif', 'm4b', 'webm', 'mp4', 'mov', 'm4v', 'mkv'];
const PALETTE = ['#3b5bdb', '#d9480f', '#2b8a3e', '#ae3ec9', '#0c8599', '#e67700', '#c2255c'];

const S = {
  list: [], sel: null, rex: null, tab: 'text', focus: 0, results: null, recording: { on: false },
  sig: '', lastScroll: 0, colors: {}, phoneLoaded: false,
};

// ---------------------------------------------------------------- 工具

async function api(path, body) {
  const opt = body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Rex-App': '1' }, body: JSON.stringify(body),
  };
  let r, j;
  try { r = await fetch(path, opt); } catch (e) { return { ok: false, msg: '连不上录音台服务（rex app 关了？）' }; }
  try { j = await r.json(); } catch (e) { j = { ok: false, msg: '服务没回应' }; }
  if (r.status === 403 && j.auth) {
    // 口令对不上就重开一次页面拿新口令；但别无限刷（浏览器禁了 cookie、同时开着两个端口的录音台都会这样）
    let n = 0;
    try { n = +(sessionStorage.getItem('rex_reloads') || 0); sessionStorage.setItem('rex_reloads', n + 1); } catch (e) { /* 没有就算 */ }
    if (n < 3) { location.reload(); return { ok: false, msg: '重新连接…' }; }
    return { ok: false, msg: '口令对不上：在终端里跑 rex app 重新打开这一页' };
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

function dur(sec) {
  if (!sec) return '';
  if (sec < 60) return `${sec} 秒`;
  const m = Math.round(sec / 60);
  return m < 60 ? `${m} 分钟` : `${Math.floor(m / 60)} 小时 ${m % 60} 分`;
}

function color(who) {
  if (!who) return 'inherit';
  if (!S.colors[who]) {
    if (who === '我') S.colors[who] = PALETTE[0];
    else if (who === '对方') S.colors[who] = PALETTE[1];
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
  if (d === iso(today)) return '今天';
  if (d === iso(y)) return '昨天';
  return d || '没有日期';
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
  if (r.busy) c.push('<span class="chip busy"><span class="spin"></span> 处理中</span>');
  if (!r.transcribed) c.push('<span class="chip">没转写</span>');
  else if (r.dialogue) c.push(`<span class="chip ok">${r.speakers.length > 1 ? r.speakers.length + ' 人' : '对话稿'}</span>`);
  if (r.proof) {
    if (r.proof.failed) c.push(`<span class="chip bad">${r.proof.failed} 行没校</span>`);
    if (r.proof.unsure) c.push(`<span class="chip warn">待确认 ${r.proof.unsure}</span>`);
    else if (!r.proof.failed) c.push('<span class="chip ok">校对 ✓</span>');
  }
  if (r.analyzed) c.push('<span class="chip ok">分析 ✓</span>');
  return c.join('');
}

function renderList() {
  const el = $('#list');
  if (S.results) {
    if (!S.results.length) { el.innerHTML = '<div class="group">没搜到</div>'; return; }
    el.innerHTML = '<div class="group">搜索结果</div>' + S.results.map(r => `
      <div class="item ${r.key === S.sel ? 'sel' : ''}" data-key="${esc(r.key)}">
        <div class="t">${esc(r.title)}</div>
        <div class="m">${esc(r.when)}</div>
        ${r.hits.map(h => `<div class="hit"><span class="ts" data-key="${esc(r.key)}" data-t="${h.t == null ? '' : h.t}">${h.t == null ? '' : fmt(h.t)}</span>${esc(h.text)}</div>`).join('')}
      </div>`).join('');
    return;
  }
  if (!S.list.length) { el.innerHTML = '<div class="group">还没有录音</div>'; return; }
  let html = '', last = '';
  for (const r of S.list) {
    const g = dayLabel(r.when);
    if (g !== last) { html += `<div class="group">${esc(g)}</div>`; last = g; }
    const meta = [r.when.slice(11), r.source + (r.origin && r.source === '导入' ? '' : ''), dur(r.duration)].filter(Boolean).join(' · ');
    html += `<div class="item ${r.key === S.sel ? 'sel' : ''}" data-key="${esc(r.key)}" title="双击移到废纸篓">
      <div class="t">${esc(r.title)}</div>
      <div class="m">${esc(meta)} ${chips(r)}</div></div>`;
  }
  el.innerHTML = html;
}

function renderJobs(jobs, inbox) {
  const el = $('#jobs');
  const parts = [];
  if (inbox && inbox.busy) {
    parts.push(`<div class="job"><div class="h"><span class="chip busy"><span class="spin"></span> 收件箱</span> 正在处理</div>
      ${inbox.tail.length ? `<pre>${esc(inbox.tail.slice(-5).join('\n'))}</pre>` : ''}</div>`);
  }
  if (inbox && inbox.waiting && inbox.waiting.length && !inbox.busy) {
    parts.push(`<div class="job"><div class="h"><span class="chip warn">收件箱</span> ${inbox.waiting.length} 个文件在等</div></div>`);
  }
  for (const j of jobs.slice().reverse()) {
    if (j.state === '完成' && Date.now() / 1000 - j.ended > 600) continue;
    const cls = { '排队': '', '进行中': 'busy', '完成': 'ok', '出错': 'bad' }[j.state] || '';
    parts.push(`<div class="job"><div class="h"><span class="chip ${cls}">${j.state === '进行中' ? '<span class="spin"></span> ' : ''}${esc(j.state)}</span> ${esc(j.label)}</div>
      ${j.state !== '完成' && j.tail.length ? `<pre>${esc(j.tail.slice(-4).join('\n'))}</pre>` : ''}</div>`);
  }
  el.innerHTML = parts.join('') || '<span class="muted">没有</span>';
}

function renderRecording(r) {
  S.recording = r;
  $('#recbar').classList.toggle('on', !!r.on);
  $('#recbar').classList.toggle('busy', !!r.stopping);
  $('#recmode').textContent = r.on ? ' · ' + ({ sys: '只录电脑声音', both: '我 + 对方', mic: '只录我' }[r.mode] || r.mode)
    : (r.stopping ? ' · 上一条正在收尾…' : '');
  // 每一路一根电平条：录进文件的是什么就显示什么（audiocap 每半秒写一次）。你的麦克风出数字零、
  // 或者哪一路采集停了，当场标红——别等录完才发现（2026-10-13 那次 47 分钟没录上，录的时候看不出来）
  const parts = [];
  if (r.lost) {
    // 连不上服务就说连不上：别让页面停在最后一次「正常」上，电平条看着是绿的、实际没人在看
    parts.push('<span class="meter bad">连不上录音台服务，录音状态未知</span>');
  }
  const want = r.lost ? [] : ({ both: ['mic', 'sys'], sys: ['sys'], mic: ['mic'] }[r.mode] || ['mic', 'sys']);
  for (const [tag, who] of [['mic', '我'], ['sys', '对方']]) {
    if (!r.on || !want.includes(tag)) continue;
    const lv = r.levels ? r.levels[tag] : null;
    // 该有的那一路连电平文件都没有：标红，不是不画
    if (!lv) { parts.push(`<span class="meter bad">${who}<span class="bar"><i style="width:0%"></i></span>没数据</span>`); continue; }
    // 用本机时钟判新鲜度：服务端的 now 是上一次回应时的，回应停了它就不走了，永远不会「过期」
    const now = Date.now() / 1000;
    const stale = now - (lv.last_frame_t || lv.t) > 10;   // 文件还在刷、帧却不来了，也算停了
    const zero = lv.zero_since > 0 ? now - lv.zero_since : 0;
    let cls = '', txt = '';
    if (stale) { cls = 'bad'; txt = '采集停了'; }
    else if (tag === 'mic' && zero >= 3) { cls = 'bad'; txt = '没信号'; }
    else if (zero >= 2) { cls = 'quiet'; txt = '没声音'; }
    const w = stale || lv.db <= -60 ? 0 : Math.round((lv.db + 60) / 60 * 100);
    parts.push(`<span class="meter ${cls}" title="${who}这一路：峰值 ${lv.db} dB">${who}<span class="bar"><i style="width:${w}%"></i></span>${txt}</span>`);
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
  if (r.busy) action = '<button disabled><span class="spin"></span> 处理中</button>';
  else if (!r.entries.length) action = '<button class="primary" data-act="go">开始处理</button>';
  else if (failed) action = `<button class="primary" data-act="go">补校没校的 ${failed} 行</button>`;
  else if (!p || !r.analysis) action = `<button class="primary" data-act="go">${!p ? '补做校对和分析' : '补做分析'}</button>`;
  const speakersN = new Set(r.entries.map(e => e.who).filter(Boolean)).size;
  const meta = [r.when, r.source + (r.origin && r.origin !== r.title ? '：' + r.origin : ''),
    speakersN > 1 ? speakersN + ' 人' : '', r.kw && r.kw !== r.title ? '关键词：' + r.kw : ''].filter(Boolean).join(' · ');
  const tabs = `
        <button class="tab ${S.tab === 'text' ? 'on' : ''}" data-tab="text">稿子</button>
        <button class="tab ${S.tab === 'proof' ? 'on' : ''}" data-tab="proof">校对${nPend ? `<span class="n">${nPend}</span>` : ''}</button>
        <button class="tab ${S.tab === 'analysis' ? 'on' : ''}" data-tab="analysis">分析</button>
        <button class="tab ${S.tab === 'chat' ? 'on' : ''}" data-tab="chat">接着问${r.chat.length ? ` (${r.chat.length})` : ''}</button>`;
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
      <div class="dtitle"><h2>${esc(r.title)}</h2><span id="dact">${action}</span><button class="ghost" data-act="reveal" title="在访达中显示">访达</button><button class="ghost" data-act="trash" title="移到废纸篓（双击左边列表里的这一条也行）">删除</button></div>
      <div class="dmeta">${esc(meta)}</div>
      ${r.audio.length ? `<audio id="player" controls preload="metadata" data-key="${esc(r.key)}" data-i="0" src="/media?k=${encodeURIComponent(r.key)}&i=0"></audio>
        ${r.audio.length > 1 ? `<div class="tracks">分轨录音：${r.audio.map((a, i) => `<button class="ghost" data-track="${i}">${/-sys/.test(a) ? '电脑声音那轨' : '麦克风那轨'}</button>`).join('')}</div>` : ''}` : '<div class="muted">没有音频文件</div>'}
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
  if (!r.entries.length) return '<div class="notice info">还没有转写。点右上角「开始处理」，或者在终端里 <code>rex go</code>。</div>';
  const fixes = {}, pend = {};
  if (r.proof) {
    for (const x of r.proof.applied) (fixes[x.id] = fixes[x.id] || []).push(x);
    for (const x of r.proof.unsure) (pend[x.id] = pend[x.id] || []).push(x);
  }
  return r.entries.map(e => {
    const marks = (fixes[e.id] || []).map(x => ({ s: x.new, cls: 'fix', title: `原来是「${x.old}」${x.by === '你' ? '（你采纳的）' : ''}` }))
      .concat((pend[e.id] || []).map(x => ({ s: x.old, cls: 'pend', title: `可能是「${x.new}」：${x.why}` })));
    return `<div class="line" id="L${e.id}" data-a="${e.a}"><span class="ts" data-t="${e.a}">${fmt(e.a)}</span>
      <div>${e.who ? `<span class="who" style="color:${color(e.who)}">${esc(e.who)}</span>` : ''}${marked(e.text, marks)}</div></div>`;
  }).join('');
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
  if (!p) return `<div class="notice info">还没有校对。${r.entries.length ? '点右上角的按钮补做。' : ''}</div>`;
  const failed = p.failed.reduce((n, x) => n + x[1] - x[0] + 1, 0);
  let h = `<div class="sum"><span><span class="big">${p.applied.length}</span>处改了</span>
    <span class="chip warn">待确认 ${p.unsure.length}</span>
    ${p.rejected.length ? `<span class="chip">你没采纳 ${p.rejected.length}</span>` : ''}
    ${p.missed.length ? `<span class="chip">没对上原文 ${p.missed.length}</span>` : ''}</div>`;
  if (failed) h += `<div class="notice">还有 ${failed} 行没校成（第 ${p.failed.map(x => x[0] + '~' + x[1]).join('、')} 行）。<button data-act="go">现在补</button></div>`;
  if (p.runs && p.runs.length) h += `<div class="muted" style="font-size:12px">${p.runs.map(x => esc(x.when + (x.note ? '，' + x.note : ''))).join('<br>')}</div>`;
  if (p.unsure.length) {
    S.focus = Math.min(S.focus, p.unsure.length - 1);
    h += `<div class="h3">待你确认 <small>${p.unsure.length} 处 · Claude 拿不准，稿子里还是原文</small>
      <span class="keys"><kbd>Y</kbd> 采纳 <kbd>N</kbd> 不采纳 <kbd>J</kbd>/<kbd>K</kbd> 上下 <kbd>空格</kbd> 听这一句</span></div>`;
    h += p.unsure.map((x, i) => `
      <div class="card ${i === S.focus ? 'focus' : ''}" id="C${i}" data-i="${i}">
        <div class="ch"><span class="ts" data-t="${x.t}">${fmt(x.t)}</span> ${x.who ? `<span class="who" style="color:${color(x.who)}">${esc(x.who)}</span>` : ''}
          <del>${esc(x.old)}</del> → <ins>${esc(x.new)}</ins></div>
        <div class="acts"><button data-rid="${x.rid}" data-do="accept">采纳</button><button class="ghost" data-rid="${x.rid}" data-do="reject">不采纳</button></div>
        <div class="why">${esc(x.why)}</div>
        <div class="ctx">${marked(around(lineText(r, x.id), x.old), [{ s: x.old, cls: 'pend', title: '' }])}</div>
      </div>`).join('');
  }
  if (p.applied.length) {
    h += `<div class="h3">改了的 <small>${p.applied.length} 处 · 点「撤销」就改回原文</small></div>`;
    h += p.applied.map(x => `<div class="row"><span class="ts" data-t="${x.t}">${fmt(x.t)}</span>
      <div class="ch"><del>${esc(x.old)}</del> → <ins>${esc(x.new)}</ins><span class="why">${esc(x.why)}${x.by === '你' ? ' · 你采纳的' : ''}</span></div>
      <button class="ghost" data-rid="${x.rid}" data-do="undo">撤销</button></div>`).join('');
  }
  if (p.rejected.length) {
    h += `<div class="h3">你没采纳的 <small>${p.rejected.length} 处</small></div>`;
    h += p.rejected.map(x => `<div class="row"><span class="ts" data-t="${x.t}">${fmt(x.t)}</span>
      <div class="ch"><del>${esc(x.old)}</del> → <ins>${esc(x.new)}</ins><span class="why">${esc(x.why)}</span></div>
      <button class="ghost" data-rid="${x.rid}" data-do="accept">采纳</button></div>`).join('');
  }
  if (p.missed.length) {
    h += `<div class="h3">没对上原文的 <small>Claude 引的原文在那一行里找不到，没改</small></div>`;
    h += p.missed.map(x => `<div class="row"><span class="ts" data-t="${x.t}">${fmt(x.t)}</span>
      <div class="ch">${esc(x.old)} → ${esc(x.new)}<span class="why">${esc(x.why)}</span></div><span></span></div>`).join('');
  }
  return h;
}

function paneAnalysis(r) {
  if (!r.analysis) return '<div class="notice info">还没有分析。点右上角的按钮补做。</div>';
  const cut = r.analysis.indexOf('\n---\n');
  const head = cut >= 0 ? r.analysis.slice(0, cut) : '';
  const body = cut >= 0 ? r.analysis.slice(cut + 5) : r.analysis;
  const used = (head.match(/^- 用量：(.*)$/m) || [])[1];
  return (used ? `<div class="muted" style="font-size:12px;margin-bottom:8px">用量：${esc(used)}</div>` : '') +
    `<div class="md">${md(body)}</div>`;
}

function paneChat(r) {
  if (!r.has_session) return '<div class="notice info">这条还没有分析，先处理它，分析会开一个能接着问的会话。</div>';
  return `<div class="chat">
    ${r.chat.length ? '' : '<div class="muted">分析那个会话里有整份稿子、校对报告和第一轮分析。问什么都行：「第 40 分钟那段他到底什么意思」「把我说的计划列出来」。</div>'}
    ${r.chat.map(t => `<div class="q">${esc(t.q)}</div><div class="a md">${md(t.a)}</div>`).join('')}
    <div class="ask"><textarea id="ask" placeholder="问点什么…（⌘↩ 发送）"></textarea><button class="primary" id="send">问</button></div>
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
  renderRecording(j.recording);
  renderJobs(j.jobs, j.inbox);
  if (!S.results) renderList();
  // 转写完会按关键词改名（X → X_关键词）。选中的那条从列表里消失了，就跟到新名字上
  if (S.sel && !S.list.some(r => r.key === S.sel)) {
    const moved = S.list.find(r => r.key.startsWith(S.sel + '_'));
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
    p ? p.applied.length : -1, p ? p.unsure.length : -1];
  const now = [cur.busy, cur.transcribed, cur.analyzed, cur.chats,
    cur.proof ? cur.proof.applied : -1, cur.proof ? cur.proof.unsure : -1];
  return JSON.stringify(shown) !== JSON.stringify(now);
}

async function loadDetail(key, keepTab) {
  const j = await api('/api/rex?k=' + encodeURIComponent(key));
  if (!j.ok) { toast(j.msg || '打不开这条', 'bad'); return; }
  if (S.sel !== key) return;
  if (!keepTab) { S.tab = 'text'; S.focus = 0; }
  S.rex = j.rex;
  renderDetail();
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
  if (!confirm(`把「${r.title || key}」移到废纸篓？\n\n音频和它的稿子、校对、分析会一起移走。删错了可以在访达的废纸篓里「放回原处」。`)) return;
  const j = await api('/api/trash', { key });
  toast(j.msg, j.ok ? 'ok' : 'bad', j.ok ? 7000 : 5000);
  if (!j.ok) return;
  if (S.sel === key) {
    S.sel = null; S.rex = null;
    $('#detail').dataset.key = '';
    $('#detail').innerHTML = '<div class="empty">选一条录音</div>';
  }
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
  t.disabled = true; $('#send').disabled = true;
  $('#send').innerHTML = '<span class="spin"></span> 想着呢';
  const wait = document.createElement('div');
  wait.className = 'q'; wait.textContent = q;
  t.parentElement.before(wait);
  const j = await api('/api/chat', { key: S.sel, q });
  if (!j.ok) { toast(j.msg, 'bad'); t.disabled = false; $('#send').disabled = false; $('#send').textContent = '问'; wait.remove(); return; }
  await loadDetail(S.sel, true);
  const box = $('#detail'); box.scrollTop = box.scrollHeight;
}

// ---------------------------------------------------------------- 上传、录音、手机、登录

function upload(file) {
  const ext = (file.name.split('.').pop() || '').toLowerCase();
  if (!AUDIO_EXT.includes(ext)) { toast(`${file.name} 不是音视频文件，没放进去`, 'bad'); return; }
  const note = document.createElement('div');
  note.className = 'toast'; note.textContent = `上传 ${file.name} …`;
  $('#toasts').appendChild(note);
  const x = new XMLHttpRequest();
  x.open('POST', '/api/upload?name=' + encodeURIComponent(file.name));
  x.setRequestHeader('X-Rex-App', '1');
  x.setRequestHeader('X-Rex-Mtime', String((file.lastModified || 0) / 1000));   // 收件箱按原文件的时间起名
  x.upload.onprogress = e => { if (e.lengthComputable) note.textContent = `上传 ${file.name} … ${Math.round(e.loaded / e.total * 100)}%`; };
  x.onload = () => {
    let j = {}; try { j = JSON.parse(x.responseText); } catch (e) { /* 下面统一报 */ }
    note.remove();
    if (j.ok) { toast(j.msg + '\n转写 → 分人 → 校对 → 分析，做完左边会更新', 'ok', 8000); refresh(); }
    else toast(j.msg || '没传上', 'bad');
  };
  x.onerror = () => { note.remove(); toast('没传上：连不上服务', 'bad'); };
  x.send(file);
}

async function startRec(mode) {
  if (S.starting) return;                        // 开录要几秒，这期间别让第二下进来
  S.starting = true;
  $('#recbar').classList.add('busy');
  toast({ both: '正在开始：录你的麦克风 + 电脑声音…', sys: '正在开始：只录电脑声音（不录你的麦克风）…', mic: '正在开始：只录你的麦克风…' }[mode], '', 3000);
  try {
    const j = await api('/api/record', { mode });
    toast(j.msg || (j.ok ? '开始录了' : '没开起来'), j.ok ? 'ok' : 'bad', j.ok ? 6000 : 12000);
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
  toast(j.msg || '停了', j.ok ? 'ok' : 'bad', 15000);
  await refresh();
  if (S.list.length) select(S.list[0].key);
}

async function loadPhone() {
  const el = $('#phone');
  el.innerHTML = '<span class="spin"></span>';
  const j = await api('/api/phone');
  if (!j.ok) { el.textContent = j.msg; return; }
  el.innerHTML = j.items.map(x => `<div class="phone-row"><div class="pt"><div>${esc(x.title || 'iPhone 录音')}</div>
    <div>${esc(x.when)} · ${esc(dur(x.duration))}</div></div>
    ${x.imported ? '<span class="chip ok">已导入</span>' : `<button data-phone="${esc(x.path)}" data-stamp="${esc(x.stamp)}">导入</button>`}</div>`).join('') || '没有';
}

async function loadLogin() {
  const j = await api('/api/login');
  const el = $('#login');
  if (j.ok && j.login.loggedIn) { el.textContent = `Claude 已登录${j.login.plan ? '（' + j.login.plan + '）' : ''}`; el.className = 'login'; el.title = j.login.email; }
  else { el.textContent = 'Claude 没登录：终端里 rex login'; el.className = 'login no'; }
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
    if (S.lastClick && S.lastClick.key === k && now - S.lastClick.t < 450) { S.lastClick = null; trashRec(k); return; }
    S.lastClick = { key: k, t: now };
    select(k); return;
  }
  const tab = e.target.closest('[data-tab]');
  if (tab) { S.tab = tab.dataset.tab; document.querySelectorAll('.tab').forEach(b => b.classList.toggle('on', b === tab)); renderPane(); return; }
  const dec = e.target.closest('[data-do]');
  if (dec) { decide(dec.dataset.rid, dec.dataset.do); return; }
  const card = e.target.closest('.card');
  if (card) { S.focus = Number(card.dataset.i); document.querySelectorAll('.card').forEach(c => c.classList.toggle('focus', c === card)); }
  const act = e.target.closest('[data-act]');
  if (act && act.dataset.act === 'go') { api('/api/go', { key: S.sel }).then(j => { toast(j.msg, j.ok ? 'ok' : 'bad'); refresh(); }); return; }
  if (act && act.dataset.act === 'reveal') { api('/api/reveal', { key: S.sel }); return; }
  if (act && act.dataset.act === 'trash') { trashRec(S.sel); return; }
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
window.addEventListener('dragenter', e => { e.preventDefault(); dragDepth++; $('#overlay').classList.add('on'); });
window.addEventListener('dragleave', e => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) $('#overlay').classList.remove('on'); });
window.addEventListener('dragover', e => e.preventDefault());
window.addEventListener('drop', e => {
  e.preventDefault(); dragDepth = 0; $('#overlay').classList.remove('on');
  const files = [...(e.dataTransfer.files || [])];
  if (!files.length) { toast('拖进来的不是文件（像是一段文字）。在访达里拖那个音频文件的图标', 'bad', 8000); return; }
  files.forEach(upload);
});

setInterval(() => { if (S.recording && S.recording.on) refresh(); }, 1000);   // 录音时电平条一秒刷一次
setInterval(() => { if (!S.recording || !S.recording.on) refresh(); }, 2500);
setInterval(tickClock, 1000);
refresh();
loadLogin();
