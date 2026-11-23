// GrootOps Legal: chat-style Case Search. Plain JS, no build step. All user and research text goes in via textContent.
(() => {
  const $ = (id) => document.getElementById(id);
  const view = $('view'), shell = $('shell');
  const EXAMPLES = [
    'Grounds to set aside an incompetent writ of summons',
    'Service on a defendant in a manner different from the court order',
    'Does the Federal High Court have jurisdiction over banker-customer disputes?',
  ];
  const STATUS_TEXT = {
    no_results: "Lex couldn't find an authority on point in NWLR Online.",
    login_failed: "Lex couldn't sign in to NWLR Online, so no search ran. The firm's NWLR login needs attention.",
    site_error: "NWLR Online or the research assistant had a problem, so this search didn't finish.",
  };
  const state = { me: null, threads: [], threadId: null, thread: null, court: '', poll: null, view: 'home', typed: new Set(), savedCitations: new Set() };

  // --- helpers -------------------------------------------------------------------------------
  function el(tag, attrs = {}, ...kids) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === 'class') node.className = v;
      else if (k === 'text') node.textContent = v;
      else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    return node;
  }
  const icon = (name) => el('i', { class: `ti ti-${name}`, 'aria-hidden': 'true' });
  const orb = (size, busy) => el('div', { class: `orb ${size || ''} ${busy ? 'busy' : ''}`, 'aria-hidden': 'true' },
    el('span', { class: 'core' }, el('span', { class: 'swirl' }), el('span', { class: 'blob b1' }), el('span', { class: 'blob b2' }), el('span', { class: 'gloss' })));

  async function api(path, options = {}) {
    const res = await fetch(path, {
      ...options,
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'grootops-legal', ...(options.headers || {}) },
      body: options.body ? JSON.stringify(options.body) : undefined,
    });
    if (res.status === 401) { location.href = '/login'; throw new Error('signed out'); }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.error || 'Something went wrong. Try again.');
    return data;
  }

  function dayLabel(ts) {
    const d = new Date(ts * 1000), now = new Date();
    const days = Math.floor((new Date(now.toDateString()) - new Date(d.toDateString())) / 864e5);
    if (days === 0) return 'Today';
    if (days === 1) return 'Yesterday';
    if (days < 7) return 'This week';
    return 'Earlier';
  }

  // --- sidebar -------------------------------------------------------------------------------
  function renderThreads() {
    const box = $('threads');
    box.replaceChildren();
    if (!state.threads.length) { box.append(el('p', { class: 'empty-threads', text: 'Your searches will appear here.' })); return; }
    let last = '';
    for (const t of state.threads) {
      const label = dayLabel(t.updated_at);
      if (label !== last) { box.append(el('div', { class: 'group-label', text: label })); last = label; }
      const running = state.thread && state.thread.id === t.id && state.thread.searches.some((s) => s.status === 'queued' || s.status === 'running');
      box.append(el('div', { class: `thread-item ${t.id === state.threadId ? 'on' : ''}`, role: 'button', tabindex: '0',
        onclick: () => openThread(t.id), onkeydown: (e) => { if (e.key === 'Enter') openThread(t.id); } },
        running ? el('span', { class: 'dot', 'aria-label': 'Researching' }) : null,
        el('span', { text: t.title }),
        el('button', { class: 'del', title: 'Delete', 'aria-label': `Delete ${t.title}`, onclick: (e) => { e.stopPropagation(); deleteThread(t); } }, icon('trash'))));
    }
  }
  async function loadThreads() { state.threads = (await api('/api/threads')).threads; renderThreads(); }

  async function deleteThread(t) {
    if (!window.confirm(`Delete "${t.title}" from your history?`)) return;
    await api(`/api/threads/${t.id}`, { method: 'DELETE' });
    if (state.threadId === t.id) goHome();
    loadThreads();
  }

  async function loadStatus() {
    try {
      const s = await api('/api/status');
      const text = { connected: 'NWLR Online connected', not_ready: 'NWLR login needed', offline: 'Research assistant offline', preview: 'Preview mode' }[s.nwlr] || s.nwlr;
      const node = $('status');
      node.className = `status ${s.nwlr}`;
      node.replaceChildren(icon(s.nwlr === 'connected' ? 'circle-check' : 'alert-circle'), ' ', text);
      node.title = s.detail || '';
    } catch { /* the next refresh tries again */ }
  }

  // --- dropdown ------------------------------------------------------------------------------
  // The one dropdown used everywhere: a pill that opens a styled menu, with keyboard support, and
  // opens upward when there's no room below (the composer sits at the bottom of the chat).
  let openMenu = null;
  function closeOpenMenu() { if (openMenu) openMenu(); }
  document.addEventListener('mousedown', (e) => { if (openMenu && !e.target.closest('.dd')) closeOpenMenu(); });
  window.addEventListener('resize', closeOpenMenu);

  function dropdown({ label, options, value, icon: iconName, onChange }) {
    let current = options.some((o) => o.value === value) ? value : options[0].value;
    const id = `dd-${Math.random().toString(36).slice(2, 8)}`;
    const text = el('span', { class: 'dd-text' });
    const button = el('button', { type: 'button', class: 'dd-button', 'aria-haspopup': 'listbox', 'aria-expanded': 'false', 'aria-label': label, 'aria-controls': id },
      iconName ? icon(iconName) : null, text, el('i', { class: 'ti ti-chevron-down dd-chev', 'aria-hidden': 'true' }));
    const menu = el('ul', { class: 'dd-menu', role: 'listbox', id, tabindex: '-1', hidden: true, 'aria-label': label });
    const root = el('div', { class: 'dd' }, button, menu);
    let active = 0;

    const items = options.map((o, i) => {
      const li = el('li', { class: 'dd-item', role: 'option', id: `${id}-${i}`, 'aria-selected': 'false' },
        el('span', { text: o.label }), el('i', { class: 'ti ti-check dd-tick', 'aria-hidden': 'true' }));
      li.addEventListener('mousemove', () => highlight(i));
      li.addEventListener('click', () => choose(i));
      menu.append(li);
      return li;
    });
    const paint = () => {
      const index = options.findIndex((o) => o.value === current);
      text.textContent = options[index].label;
      root.classList.toggle('set', index > 0);
      items.forEach((li, i) => li.setAttribute('aria-selected', String(i === index)));
    };
    const highlight = (i) => {
      active = (i + items.length) % items.length;
      items.forEach((li, n) => li.classList.toggle('active', n === active));
      menu.setAttribute('aria-activedescendant', items[active].id);
      items[active].scrollIntoView({ block: 'nearest' });
    };
    const close = (focusButton = false) => {
      menu.hidden = true; root.classList.remove('open', 'up');
      button.setAttribute('aria-expanded', 'false');
      if (openMenu === close) openMenu = null;
      if (focusButton) button.focus();
    };
    const open = () => {
      closeOpenMenu();
      menu.hidden = false; root.classList.add('open');
      const box = button.getBoundingClientRect();
      root.classList.toggle('up', window.innerHeight - box.bottom < menu.offsetHeight + 16 && box.top > menu.offsetHeight + 16);
      button.setAttribute('aria-expanded', 'true');
      highlight(Math.max(0, options.findIndex((o) => o.value === current)));
      menu.focus();
      openMenu = close;
    };
    const choose = (i) => {
      const changed = options[i].value !== current;
      current = options[i].value; paint(); close(true);
      if (changed) onChange(current);
    };
    button.addEventListener('click', () => (menu.hidden ? open() : close()));
    button.addEventListener('keydown', (e) => { if (['ArrowDown', 'ArrowUp'].includes(e.key)) { e.preventDefault(); open(); } });
    menu.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); highlight(active + 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); highlight(active - 1); }
      else if (e.key === 'Home') { e.preventDefault(); highlight(0); }
      else if (e.key === 'End') { e.preventDefault(); highlight(items.length - 1); }
      else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); choose(active); }
      else if (e.key === 'Escape') { e.preventDefault(); close(true); }
      else if (e.key === 'Tab') close();
    });
    paint();
    return root;
  }

  // --- composer ------------------------------------------------------------------------------
  function composer({ placeholder, autofocus, busy, onSubmit }) {
    const area = el('textarea', { rows: '1', placeholder, 'aria-label': 'Research question', maxlength: '1500' });
    const send = el('button', { class: `send ${busy ? 'working' : ''}`, type: 'button' });
    const error = el('p', { class: 'composer-error', role: 'alert' });
    const court = dropdown({ label: 'Limit to a court', options: state.me.courts, value: state.court, icon: 'building-bank',
      onChange: (value) => { state.court = value; } });
    const setSend = () => {
      send.replaceChildren(...(busy ? [el('span', { class: 'spinner' }), 'Researching'] : ['Search', icon('arrow-up')]));
      send.classList.toggle('ready', !busy && area.value.trim().length > 0);
    };
    const grow = () => { area.style.height = 'auto'; area.style.height = `${Math.min(area.scrollHeight, 200)}px`; };
    const submit = () => {
      if (busy) return;
      const text = area.value.trim();
      if (!text) { error.textContent = 'Type a research question first.'; area.focus(); return; }
      onSubmit(text, error);
    };
    area.addEventListener('input', () => { error.textContent = ''; grow(); setSend(); });
    area.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); } });
    send.addEventListener('click', submit);
    setSend();
    if (autofocus) setTimeout(() => area.focus(), 50);
    const box = el('div', { class: 'composer' }, area, el('div', { class: 'composer-row' }, court, send));
    return { box, error, area };
  }

  // --- views ---------------------------------------------------------------------------------
  function setRail(which) {
    $('rail-research').classList.toggle('on', which !== 'saved');
    $('rail-saved').classList.toggle('on', which === 'saved');
  }

  function goHome() {
    stopPolling();
    state.view = 'home'; state.threadId = null; state.thread = null;
    setRail('home'); renderThreads(); closeDrawer();
    history.replaceState(null, '', '/');
    const first = (state.me.name || '').split(' ')[0];
    const hero = el('section', { class: 'hero' });
    const { box, error, area } = composer({ placeholder: 'Ask a legal question in plain English…', autofocus: true,
      onSubmit: (text, err) => startSearch(text, null, err, hero) });
    hero.append(
      orb(),
      el('h1', { text: first ? `What should we research, ${first}?` : 'What should we research?' }),
      box, error,
      el('div', { class: 'chips' }, ...EXAMPLES.map((q) => el('button', { class: 'chip', text: q, onclick: () => { area.value = q; startSearch(q, null, error, hero); } }))),
      el('div', { class: 'up-next' }, 'Up next',
        el('button', { onclick: openLatestForMemo }, orb('xs'),
          el('span', {}, 'Turn your last search into a research memo', el('small', { text: 'Download a Word memo with citations and quotes' })))),
    );
    view.replaceChildren(hero);
  }

  async function openLatestForMemo() {
    if (!state.threads.length) { goHome(); return; }
    location.href = `/api/threads/${state.threads[0].id}/memo.docx`;
  }

  async function startSearch(question, threadId, errorNode, hero) {
    try {
      const search = await api('/api/searches', { method: 'POST', body: { question, court: state.court, thread_id: threadId } });
      if (hero) { hero.classList.add('leaving'); await new Promise((r) => setTimeout(r, 300)); }
      await openThread(search.thread_id, { entering: Boolean(hero) });
      loadThreads();
    } catch (e) { if (errorNode) errorNode.textContent = e.message; }
  }

  async function openThread(id, { entering = false } = {}) {
    stopPolling();
    state.view = 'thread'; state.threadId = id; setRail('thread'); closeDrawer();
    history.replaceState(null, '', `/?t=${encodeURIComponent(id)}`);
    try { state.thread = await api(`/api/threads/${id}`); } catch (e) { goHome(); return; }
    // Finished searches loaded from history appear whole; only ones we watch finish get typed out.
    state.thread.searches.forEach((s) => { if (s.status === 'done' || s.status === 'failed') state.typed.add(s.id); });
    renderThread(entering);
    renderThreads();
    if (active()) startPolling();
  }

  const active = () => state.thread && state.thread.searches.find((s) => s.status === 'queued' || s.status === 'running');

  function renderThread(entering) {
    const col = el('div', { class: 'col' });
    for (const s of state.thread.searches) col.append(...renderSearch(s));
    const feed = el('div', { class: 'feed' }, col);
    const busy = Boolean(active());
    const { box, error } = composer({ placeholder: busy ? 'Lex is researching…' : 'Ask a follow-up…', autofocus: !busy, busy,
      onSubmit: (text, err) => startSearch(text, state.threadId, err, null) });
    const dock = el('div', { class: `dock ${entering ? 'entering' : ''}` }, box, error,
      el('p', { class: 'disclaimer', text: 'A research aid. Check each authority before you rely on it.' }));
    view.replaceChildren(feed, dock);
    feed.scrollTop = feed.scrollHeight;
  }

  function renderSearch(s) {
    const courtLabel = (state.me.courts.find((c) => c.value === s.court) || {}).label;
    const bubble = el('div', { class: 'q-bubble fade-in' }, s.question, s.court ? el('span', { class: 'q-court', text: courtLabel }) : null);
    const body = el('div', { class: 'reply-body' });
    const running = s.status === 'queued' || s.status === 'running';
    const reply = el('div', { class: 'reply fade-in', 'data-search': s.id }, orb('sm', running), body);
    if (s.status === 'queued') {
      body.append(el('div', { class: 'pulse', text: s.queued_ahead ? `Waiting for ${s.queued_ahead} search${s.queued_ahead > 1 ? 'es' : ''} ahead of yours…` : 'Starting…' }));
    } else if (s.status === 'running') {
      body.append(el('div', { class: 'pulse' }, 'Researching'));
      body.append(el('div', { class: 'steps' }, ...state.me.steps.map((label, i) =>
        el('div', { class: `step ${i < s.step ? 'done' : i === s.step ? 'now' : ''}` },
          i < s.step ? icon('circle-check') : i === s.step ? el('span', { class: 'spinner' }) : icon('circle'), label))));
      if (s.narration) body.append(el('div', { class: 'narration', text: s.narration }));
    } else if (s.status === 'failed') {
      body.append(el('div', { class: 'problem' }, "This search didn't finish. ",
        el('button', { class: 'link-btn', text: 'Try again', onclick: () => startSearch(s.question, state.threadId, null, null) })));
    } else {
      renderResult(body, s);
    }
    return [bubble, reply];
  }

  function renderResult(body, s) {
    const r = s.result || { status: 'site_error' };
    const typeOut = !state.typed.has(s.id);
    state.typed.add(s.id);
    if (r.status !== 'ok') {
      body.append(el('div', { class: 'problem', text: STATUS_TEXT[r.status] || STATUS_TEXT.site_error }));
      if (r.note) body.append(el('div', { class: 'narration', text: r.note }));
      return;
    }
    const answer = el('div', { class: 'answer' });
    body.append(answer);
    const rest = [];
    for (const a of r.authorities) rest.push(caseCard(a, s.id));
    if (r.statutes && r.statutes.length) {
      rest.push(el('div', { class: 'statutes' }, el('strong', { text: 'Statutes: ' }), r.statutes.map((x) => `${x.name}, ${x.provision}`).join('; ')));
    }
    if (r.note) rest.push(el('div', { class: 'note', text: r.note }));
    rest.push(replyActions(s, r));
    if (!typeOut) { answer.textContent = r.answer; body.append(...rest); return; }
    let i = 0;
    const text = r.answer || '';
    const tick = () => {
      i = Math.min(text.length, i + 4);
      answer.textContent = text.slice(0, i);
      if (i < text.length) { setTimeout(tick, 14); return; }
      rest.forEach((node, n) => setTimeout(() => { node.classList.add('fade-in'); body.append(node); }, 120 * (n + 1)));
    };
    tick();
  }

  function caseCard(a, searchId) {
    const saveBtn = el('button', { class: 'mini', type: 'button' });
    let saved = state.savedCitations.has(a.citation);
    const paint = () => saveBtn.replaceChildren(icon(saved ? 'bookmark-filled' : 'bookmark'), saved ? 'Saved' : 'Save');
    saveBtn.classList.toggle('on', saved);
    saveBtn.addEventListener('click', async () => {
      saved = !saved; paint(); saveBtn.classList.toggle('on', saved);
      try {
        await api('/api/saved', { method: 'POST', body: { search_id: searchId, citation: a.citation, saved } });
        if (saved) state.savedCitations.add(a.citation); else state.savedCitations.delete(a.citation);
      }
      catch { saved = !saved; paint(); saveBtn.classList.toggle('on', saved); }
    });
    paint();
    const copyBtn = el('button', { class: 'mini', type: 'button' }, icon('copy'), 'Copy citation');
    copyBtn.addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(`${a.case_name} ${a.citation}`); copyBtn.replaceChildren(icon('check'), 'Copied'); }
      catch { copyBtn.replaceChildren(icon('alert-circle'), "Couldn't copy"); }
      setTimeout(() => copyBtn.replaceChildren(icon('copy'), 'Copy citation'), 1600);
    });
    return el('article', { class: 'case' },
      el('div', { class: 'case-head' }, el('div', {},
        el('div', { class: 'case-name', text: a.case_name }),
        el('div', { class: 'case-meta', text: [a.citation, a.court].filter(Boolean).join(' · ') }))),
      a.holding ? el('div', { class: 'case-holding', text: a.holding }) : null,
      el('blockquote', { class: 'quote', text: `“${a.quote}”${a.page ? ` (${a.page})` : ''}` }),
      el('div', { class: 'case-actions' }, copyBtn,
        el('a', { class: 'mini', href: a.source_url, target: '_blank', rel: 'noopener noreferrer' }, icon('external-link'), 'Open on NWLR'),
        searchId ? saveBtn : null));
  }

  function replyActions(s, r) {
    const thumbs = ['up', 'down'].map((v) => {
      const b = el('button', { class: `icon-btn ${s.feedback === v ? 'on' : ''}`, title: v === 'up' ? 'Helpful' : 'Not helpful', 'aria-label': v === 'up' ? 'Helpful' : 'Not helpful' }, icon(`thumb-${v}`));
      b.addEventListener('click', async () => {
        const value = s.feedback === v ? '' : v;
        await api(`/api/searches/${s.id}/feedback`, { method: 'POST', body: { feedback: value } }).catch(() => {});
        s.feedback = value; thumbs.forEach((t, i) => t.classList.toggle('on', value === ['up', 'down'][i]));
      });
      return b;
    });
    const row = el('div', { class: 'reply-actions' }, ...thumbs,
      el('a', { class: 'mini', href: `/api/threads/${s.thread_id}/memo.docx` }, icon('download'), 'Export memo'));
    if (r.rejected && r.rejected.length) {
      const list = el('ul', { class: 'hidden-list', hidden: true }, ...r.rejected.map((x) => el('li', { text: `${x.label}: ${x.reason}` })));
      const toggle = el('button', { class: 'link-btn', text: `${r.rejected.length} result${r.rejected.length > 1 ? 's' : ''} hidden by the citation checks` });
      toggle.addEventListener('click', () => { list.hidden = !list.hidden; });
      return el('div', {}, row, el('div', { style: 'margin-top:4px' }, icon('shield-check'), ' ', toggle), list);
    }
    return row;
  }

  async function showSaved() {
    stopPolling();
    state.view = 'saved'; state.threadId = null; state.thread = null; setRail('saved'); renderThreads(); closeDrawer();
    const { saved } = await api('/api/saved');
    const col = el('div', { class: 'col' },
      el('div', {}, el('h2', { text: 'Saved authorities' }), el('p', { class: 'lead', text: 'Cases you saved from your searches.' })));
    if (!saved.length) col.append(el('p', { class: 'problem', text: 'Save a case from any search and it appears here.' }));
    for (const a of saved) {
      const card = caseCard(a, null);
      const remove = el('button', { class: 'mini', type: 'button' }, icon('trash'), 'Remove');
      remove.addEventListener('click', async () => {
        await api('/api/saved', { method: 'POST', body: { search_id: a.search_id, citation: a.citation, saved: false } });
        state.savedCitations.delete(a.citation);
        card.remove();
      });
      card.querySelector('.case-actions').append(remove);
      col.append(card);
    }
    view.replaceChildren(el('div', { class: 'saved-view' }, col));
  }

  // --- polling -------------------------------------------------------------------------------
  function startPolling() {
    stopPolling();
    state.poll = setInterval(async () => {
      const current = active();
      if (!current || state.view !== 'thread') { stopPolling(); return; }
      try {
        const fresh = await api(`/api/searches/${current.id}`);
        const idx = state.thread.searches.findIndex((s) => s.id === fresh.id);
        const changed = JSON.stringify([fresh.status, fresh.step, fresh.narration, fresh.queued_ahead]) !==
          JSON.stringify([current.status, current.step, current.narration, current.queued_ahead]);
        state.thread.searches[idx] = fresh;
        if (changed) {
          const finished = fresh.status === 'done' || fresh.status === 'failed';
          if (finished) { renderThread(false); stopPolling(); loadThreads(); }
          else {
            const node = view.querySelector(`[data-search="${fresh.id}"]`);
            if (node) node.replaceWith(renderSearch(fresh)[1]);
          }
        }
      } catch { /* keep polling */ }
    }, 2000);
  }
  function stopPolling() { if (state.poll) clearInterval(state.poll); state.poll = null; }

  // --- drawer, actions, start ----------------------------------------------------------------
  function closeDrawer() { shell.classList.remove('drawer'); }
  document.addEventListener('click', async (e) => {
    const target = e.target.closest('[data-action]');
    if (!target) return;
    const action = target.dataset.action;
    if (action === 'new') goHome();
    else if (action === 'saved') showSaved();
    else if (action === 'open-drawer') shell.classList.add('drawer');
    else if (action === 'close-drawer') closeDrawer();
    else if (action === 'logout') { await api('/api/logout', { method: 'POST' }).catch(() => {}); location.href = '/login'; }
  });

  (async () => {
    state.me = await api('/api/me');
    $('avatar').textContent = (state.me.name || '?').split(/\s+/).map((p) => p[0]).join('').slice(0, 2).toUpperCase();
    $('avatar').title = state.me.name;
    $('who').textContent = [state.me.name, state.me.firm].filter(Boolean).join(' · ');
    if (state.me.preview) { $('banner').hidden = false; $('banner').textContent = 'Preview mode: results are samples to show the design, not real research.'; }
    await loadThreads();
    api('/api/saved').then((d) => { state.savedCitations = new Set(d.saved.map((a) => a.citation)); }).catch(() => {});
    loadStatus(); setInterval(loadStatus, 60000);
    const fromUrl = new URLSearchParams(location.search).get('t');
    if (fromUrl) openThread(fromUrl); else goHome();
  })();
})();
