'use strict';

/* ---------- utilità ---------- */
const $ = (s, r = document) => r.querySelector(s);
const LS = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* ignora */ } },
};
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  if (attrs) for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat()) if (c != null && c !== false) el.append(c.nodeType ? c : document.createTextNode(String(c)));
  return el;
}
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

let currency = 'EUR';
function money(v) {
  if (v == null) return 'n.d.';
  try { return new Intl.NumberFormat('it-IT', { style: 'currency', currency, maximumFractionDigits: 0 }).format(v); }
  catch (e) { return Math.round(v) + ' ' + currency; }
}
function fmtDur(m) {
  if (m == null) return 'n.d.';
  const hh = Math.floor(m / 60), mm = m % 60;
  if (!hh) return mm + ' min';
  return hh + ' h' + (mm ? ' ' + String(mm).padStart(2, '0') : '');
}
const timeOf = s => (s || '').slice(11, 16);
const dateOf = s => (s || '').slice(0, 10);
const dayNum = d => { const [y, m, dd] = d.split('-').map(Number); return Date.UTC(y, m - 1, dd) / 86400000; };
function addDays(d, n) { const t = new Date((dayNum(d) + n) * 86400000); return t.toISOString().slice(0, 10); }
function fmtDate(d) {
  if (!d) return '';
  const [y, m, dd] = d.split('-').map(Number);
  return new Intl.DateTimeFormat('it-IT', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' }).format(new Date(Date.UTC(y, m - 1, dd)));
}
const plusDay = it => { const n = dayNum(dateOf(it.arrival)) - dayNum(dateOf(it.departure)); return n > 0 ? n : 0; };

async function api(path, opts) {
  const r = await fetch(path, Object.assign({ headers: { 'Accept': 'application/json' }, credentials: 'same-origin' }, opts));
  if (r.status === 401 || (r.redirected && /\/login/.test(r.url))) { location.href = '/login'; throw new Error('non autenticato'); }
  let data = null;
  try { data = await r.json(); } catch (e) { /* non json */ }
  if (!r.ok) {
    let msg = 'Errore ' + r.status;
    const d = data && data.detail;
    if (typeof d === 'string') msg = d;
    else if (Array.isArray(d)) msg = d.map(e => (e.loc ? e.loc.filter(x => x !== 'body').join('.') + ': ' : '') + (e.msg || '')).join('; ');
    throw new Error(msg);
  }
  return data;
}

/* ---------- cache aeroporti ---------- */
const apCache = {};
const apLabel = a => `${a.iata} · ${a.city} — ${a.name}, ${a.country}`;
async function ensureAirport(code) {
  if (apCache[code]) return apCache[code];
  try { const a = await api('/api/airports/' + encodeURIComponent(code)); apCache[code] = a; return a; }
  catch (e) { return null; }
}

/* ---------- gruppi preferiti ---------- */
let groups = LS.get('psb_groups', []);
if (!Array.isArray(groups)) groups = [];
const saveGroups = () => LS.set('psb_groups', groups);
const chipFields = {};

/* ---------- campo a chip con autocompletamento ---------- */
const MAX_CHIPS = 6;
function makeChipField(key, rootId, label, placeholder) {
  const root = $('#' + rootId);
  const codes = [];
  const box = h('div', { class: 'chipbox' });
  const input = h('input', { type: 'text', placeholder, autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false', 'aria-label': label, enterkeyhint: 'done' });
  const list = h('ul', { class: 'ac', role: 'listbox', hidden: true });
  const groupsEl = h('div', { class: 'groups' });
  const labEl = h('span', { class: 'lab-t' }, label);
  root.append(labEl, box, groupsEl);
  box.append(input, list);
  let results = [], active = -1, seq = 0;
  const f = { placeholder };

  const fire = () => document.dispatchEvent(new CustomEvent('formchange'));
  function renderChips() {
    box.querySelectorAll('.chip').forEach(n => n.remove());
    codes.forEach(c => {
      const a = apCache[c];
      box.insertBefore(h('span', { class: 'chip', title: a ? apLabel(a) : c },
        h('b', { text: c }), a ? h('small', { text: a.city }) : null,
        h('button', { type: 'button', 'aria-label': 'Rimuovi ' + c, onclick: () => { remove(c); input.focus(); } }, '×')), input);
    });
    input.placeholder = codes.length ? '' : f.placeholder;
    renderGroups();
  }
  function add(code) {
    code = String(code).toUpperCase();
    if (codes.includes(code) || codes.length >= MAX_CHIPS) return;
    codes.push(code);
    renderChips(); fire();
    if (!apCache[code]) ensureAirport(code).then(a => { if (a) renderChips(); });
  }
  function remove(code) { const i = codes.indexOf(code); if (i >= 0) { codes.splice(i, 1); renderChips(); fire(); } }
  function set(arr) {
    codes.length = 0;
    (arr || []).slice(0, MAX_CHIPS).forEach(c => codes.push(String(c).toUpperCase()));
    renderChips(); fire();
    codes.forEach(c => { if (!apCache[c]) ensureAirport(c).then(a => { if (a) renderChips(); }); });
  }
  function closeList() { list.hidden = true; active = -1; }
  function renderList() {
    list.replaceChildren();
    if (!results.length) { list.append(h('li', { class: 'empty' }, 'Nessun aeroporto trovato')); list.hidden = false; return; }
    results.forEach((a, i) => {
      apCache[a.iata] = a;
      const li = h('li', { role: 'option', class: i === active ? 'on' : '' }, apLabel(a));
      li.addEventListener('mousedown', e => { e.preventDefault(); pick(a); });
      list.append(li);
    });
    list.hidden = false;
  }
  function pick(a) { apCache[a.iata] = a; add(a.iata); input.value = ''; results = []; closeList(); }
  const fetchAc = debounce(async () => {
    const q = input.value.trim();
    if (!q) { closeList(); return; }
    const my = ++seq;
    try {
      const r = await api('/api/airports?limit=12&q=' + encodeURIComponent(q));
      if (my !== seq) return;
      results = r; active = r.length ? 0 : -1; renderList();
    } catch (e) { /* ignora */ }
  }, 200);
  input.addEventListener('input', fetchAc);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      e.preventDefault();
      if (!list.hidden && results[active]) pick(results[active]);
      else if (/^[A-Za-z]{3}$/.test(input.value.trim())) { add(input.value.trim()); input.value = ''; closeList(); }
    } else if (e.key === 'Backspace' && !input.value && codes.length) {
      remove(codes[codes.length - 1]);
    } else if (e.key === 'ArrowDown' && results.length) {
      e.preventDefault(); active = (active + 1) % results.length; renderList();
    } else if (e.key === 'ArrowUp' && results.length) {
      e.preventDefault(); active = (active - 1 + results.length) % results.length; renderList();
    } else if (e.key === 'Escape') closeList();
  });
  input.addEventListener('blur', () => setTimeout(closeList, 120));
  box.addEventListener('click', e => { if (e.target === box) input.focus(); });

  function renderGroups() {
    groupsEl.replaceChildren();
    groups.forEach((g, gi) => {
      groupsEl.append(h('button', { type: 'button', class: 'gbtn', title: g.codes.join(' + '),
        onclick: () => { g.codes.forEach(add); } },
        '+ ' + g.name, h('span', { class: 'x', role: 'button', 'aria-label': 'Elimina gruppo ' + g.name, title: 'Elimina gruppo',
          onclick: e => { e.stopPropagation(); if (confirm('Eliminare il gruppo «' + g.name + '»?')) { groups.splice(gi, 1); saveGroups(); Object.values(chipFields).forEach(f => f.renderGroups()); } } }, '×')));
    });
    groupsEl.append(h('button', { type: 'button', class: 'gbtn save', onclick: () => {
      if (!codes.length) { alert('Aggiungi almeno un aeroporto da salvare.'); return; }
      const name = (prompt('Nome del gruppo (es. Casa):', '') || '').trim();
      if (!name) return;
      const ex = groups.find(g => g.name.toLowerCase() === name.toLowerCase());
      if (ex) ex.codes = codes.slice(); else groups.push({ name, codes: codes.slice() });
      saveGroups(); Object.values(chipFields).forEach(f => f.renderGroups());
    } }, '★ Salva come gruppo'));
  }
  f.codes = codes; f.set = set; f.add = add; f.renderGroups = renderGroups;
  f.setLabel = t => { labEl.textContent = t; input.setAttribute('aria-label', t); };
  f.setPlaceholder = t => { f.placeholder = t; input.placeholder = codes.length ? '' : t; };
  chipFields[key] = f;
  renderChips();
  return f;
}

/* ---------- pannelli filtri ---------- */
function filterPanel(dir, title) {
  const p = (n) => `${dir}.${n}`;
  const num = (n, ph, extra) => h('input', Object.assign({ type: 'number', 'data-f': p(n), min: 0, step: 'any', placeholder: ph, inputmode: 'decimal' }, extra));
  const tm = n => h('input', { type: 'time', 'data-f': p(n) });
  const lab = (t, el, cls) => h('label', { class: 'lab' + (cls ? ' ' + cls : '') }, t, el);
  const setv = (n, v) => { const e = $(`[data-f="${p(n)}"]`); e.value = v; e.dispatchEvent(new Event('input', { bubbles: true })); };
  return h('div', { class: 'fpanel' + (dir === '0' ? ' active' : ''), 'data-panel': dir },
    h('h3', null, title),
    h('div', { class: 'fgrid' },
      lab('Partenza dalle', tm('depart_from')), lab('Partenza alle', tm('depart_to')),
      lab('Arrivo dalle', tm('arrive_from')), lab('Arrivo alle', tm('arrive_to'))),
    h('div', { class: 'presets' },
      h('button', { type: 'button', class: 'pbtn', onclick: () => { setv('arrive_from', ''); setv('arrive_to', '20:00'); } }, 'Arrivo entro le 20 (check-in)'),
      h('button', { type: 'button', class: 'pbtn', onclick: () => { setv('arrive_from', '07:00'); setv('arrive_to', '23:00'); } }, 'Niente arrivi notturni')),
    h('div', { class: 'fgrid' },
      lab('Max scali', h('select', { 'data-f': p('max_stops') },
        h('option', { value: '' }, 'qualsiasi'), h('option', { value: '0' }, '0 (solo diretti)'), h('option', { value: '1' }, '1'), h('option', { value: '2' }, '2'))),
      lab('Max prezzo', num('max_price', '€ totale')),
      lab('Max durata (ore)', num('max_duration', 'ore')),
      lab('Max scalo (ore)', num('max_layover', 'ore')),
      lab('Min scalo (minuti)', num('min_layover', 'es. 90 per coincidenze sicure', { step: 5 }))),
    h('label', { class: 'chk', style: 'margin-top:8px' },
      h('input', { type: 'checkbox', 'data-f': p('long_only') }), 'Solo voli con scalo lungo (città gratis)'),
    h('div', { class: 'inline' }, 'Scalo lungo da', h('input', { type: 'number', 'data-f': p('threshold'), min: 1, step: 'any', value: 6, inputmode: 'decimal' }), 'ore'));
}

/* ---------- calendario con prezzi per giorno ---------- */
const MONTHS = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno', 'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre'];
const WD = ['lun', 'mar', 'mer', 'gio', 'ven', 'sab', 'dom'];
const priceCache = new Map(); // "ORI>DEST|YYYY-MM|adulti" -> Promise<{prices}>
const iso = (y, m, d) => `${y}-${String(m + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
const todayIso = () => new Date().toISOString().slice(0, 10);
const addMonth = (y, m, k) => { const t = y * 12 + m + k; return [Math.floor(t / 12), t % 12]; };

function monthPrices(origins, dests, y, m, adults) {
  // una richiesta copre il mese indicato e il successivo (max 61 giorni)
  const key = `${origins.join(',')}>${dests.join(',')}|${iso(y, m, 1).slice(0, 7)}|${adults}`;
  if (!priceCache.has(key)) {
    const start = iso(y, m, 1);
    const end = new Date(Date.UTC(y, m + 2, 0)).toISOString().slice(0, 10);
    const q = new URLSearchParams({ origins: origins.join(','), destinations: dests.join(','), start, end, adults: String(adults) });
    priceCache.set(key, api('/api/date-prices?' + q).catch(e => { priceCache.delete(key); throw e; }));
  }
  return priceCache.get(key);
}
const curAdults = () => Math.min(9, Math.max(1, parseInt(el.adults.value, 10) || 1));

let openPicker = null;
function closePicker() { if (openPicker) { openPicker.remove(); openPicker = null; document.removeEventListener('mousedown', outsidePicker, true); } }
function outsidePicker(e) { if (openPicker && !openPicker.contains(e.target) && !e.target.closest('.dp-btn')) closePicker(); }
document.addEventListener('keydown', e => { if (e.key === 'Escape') closePicker(); });

/* griglia di un mese: restituisce { el, cells: [[data, bottone, disattivato]] } */
function monthGrid(y, m, { min, marks, onPick }) {
  const grid = h('div', { class: 'dp-grid' }, WD.map(w => h('span', { class: 'dp-wd', text: w })));
  const lead = (new Date(Date.UTC(y, m, 1)).getUTCDay() + 6) % 7;
  const days = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
  for (let i = 0; i < lead; i++) grid.append(h('span', { class: 'dp-pad' }));
  const cells = [];
  for (let d = 1; d <= days; d++) {
    const ds = iso(y, m, d);
    const off = ds < min;
    const c = h('button', { type: 'button', class: 'dp-day' + (ds === todayIso() ? ' today' : '') + (marks ? marks(ds) : ''), disabled: off },
      h('span', { class: 'dn', text: String(d) }), h('span', { class: 'dpr' }));
    c.addEventListener('click', () => onPick(ds));
    cells.push([ds, c, off]);
    grid.append(c);
  }
  return {
    el: h('div', { class: 'dp-month' }, h('div', { class: 'dp-mname', text: `${MONTHS[m]} ${y}` }), grid),
    cells,
  };
}

/* colora le celle in base ai prezzi: verde = terzo più economico, arancio = terzo più caro */
function paintPrices(cells, prices) {
  const vals = cells.filter(([ds, , off]) => !off && prices[ds] != null).map(([ds]) => prices[ds]).sort((a, b) => a - b);
  if (!vals.length) return null;
  const q = p => vals[Math.min(vals.length - 1, Math.floor(p * (vals.length - 1)))];
  const lo = q(1 / 3), hi = q(2 / 3), minP = vals[0];
  cells.forEach(([ds, c, off]) => {
    const p = prices[ds];
    if (off || p == null) return;
    c.querySelector('.dpr').textContent = money(p);
    c.classList.add(p <= lo ? 'cheap' : p >= hi && hi > lo ? 'pricey' : 'mid');
    if (p === minP) c.classList.add('best');
    c.title = `${fmtDate(ds)}: da ${money(p)}`;
  });
  return minP;
}

const legend = () => h('div', { class: 'dp-legend' },
  h('span', null, h('i', { class: 'lg cheap' }), 'più economico'),
  h('span', null, h('i', { class: 'lg mid' }), 'nella media'),
  h('span', null, h('i', { class: 'lg pricey' }), 'più caro'));

/* calendario: mostra `count` mesi da (y, m), carica i prezzi della tratta e li colora */
function renderCalendar2(pop, { y, m, count, min, marks, onPick, route, onNav, title }) {
  const [origins, dests] = route;
  const canPrice = origins.length && dests.length;
  const months = [];
  for (let k = 0; k < count; k++) { const [yy, mm] = addMonth(y, m, k); months.push(monthGrid(yy, mm, { min, marks, onPick })); }
  const status = h('div', { class: 'dp-status hint', text: canPrice ? 'Carico i prezzi…' : 'Inserisci gli aeroporti per vedere i prezzi per giorno.' });
  const prevOk = iso(y, m, 1) > todayIso().slice(0, 8) + '01';
  pop.replaceChildren(
    title || null,
    h('div', { class: 'dp-head' },
      h('button', { type: 'button', class: 'dp-nav', 'aria-label': 'Mese precedente', disabled: !prevOk, onclick: () => onNav(-1) }, '‹'),
      h('div', { class: 'dp-route hint', text: canPrice ? `${origins.join('/')} → ${dests.join('/')} · prezzi sola andata` : '' }),
      h('button', { type: 'button', class: 'dp-nav', 'aria-label': 'Mese successivo', onclick: () => onNav(1) }, '›')),
    h('div', { class: 'dp-months' }, months.map(x => x.el)),
    legend(),
    status);
  if (!canPrice) return;
  const token = `${y}-${m}-${origins}-${dests}`;
  pop.dataset.token = token;
  // ogni richiesta copre 2 mesi: bastano richieste ai mesi pari dell'intervallo
  const reqs = [];
  for (let k = 0; k < count; k += 2) { const [yy, mm] = addMonth(y, m, k); reqs.push(monthPrices(origins, dests, yy, mm, curAdults())); }
  Promise.all(reqs).then(list => {
    if (pop.dataset.token !== token || !pop.isConnected) return;
    const prices = Object.assign({}, ...list.map(r => (r && r.prices) || {}));
    const minP = paintPrices(months.flatMap(x => x.cells), prices);
    const a = curAdults();
    status.textContent = minP == null ? 'Nessun prezzo disponibile per questi mesi.'
      : `Prezzo più basso: ${money(minP)}. Prezzi indicativi di sola andata, ${a} ${a === 1 ? 'adulto' : 'adulti'}.`;
  }).catch(e => { if (pop.dataset.token === token) status.textContent = 'Prezzi non disponibili: ' + e.message; });
}

function openPop(wrap, pop) {
  wrap.append(pop);
  openPicker = pop;
  setTimeout(() => document.addEventListener('mousedown', outsidePicker, true), 0);
}
function hijackValue(inp, render) {
  const desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
  Object.defineProperty(inp, 'value', { get() { return desc.get.call(inp); }, set(v) { desc.set.call(inp, v); render(); } });
}
const fmtFull = v => fmtDate(v) + ' ' + v.slice(0, 4);

/* campo data singolo (sola andata, tappe) */
function datePicker(inp, getRoute) {
  inp.type = 'hidden';
  const btn = h('button', { type: 'button', class: 'dp-btn' });
  const wrap = h('div', { class: 'dp' }, btn, inp);
  const render = () => {
    const v = inp.value;
    btn.replaceChildren(h('span', { class: 'dp-ico', 'aria-hidden': 'true' }, '📅'),
      h('span', { class: v ? 'dp-val' : 'dp-val empty', text: v ? fmtFull(v) : 'Scegli la data' }));
  };
  hijackValue(inp, render);
  render();
  btn.addEventListener('click', () => {
    if (openPicker && openPicker.dataset.owner === inp.dataset.pid) { closePicker(); return; }
    closePicker();
    const min = inp.min || todayIso();
    const start = inp.value || min;
    let y = Number(start.slice(0, 4)), m = Number(start.slice(5, 7)) - 1;
    const pop = h('div', { class: 'dp-pop', role: 'dialog', 'aria-label': 'Scegli la data' });
    pop.dataset.owner = inp.dataset.pid;
    const draw = () => renderCalendar2(pop, {
      y, m, count: 1, min, route: getRoute(),
      marks: ds => ds === inp.value ? ' sel' : '',
      onPick: ds => { inp.value = ds; inp.dispatchEvent(new Event('change', { bubbles: true })); closePicker(); },
      onNav: k => { [y, m] = addMonth(y, m, k); draw(); },
    });
    draw();
    openPop(wrap, pop);
  });
  return wrap;
}

/* calendario grande andata + ritorno (solo A/R semplice):
   primo clic = andata (colori dei prezzi di andata), secondo clic = ritorno (colori del ritorno) */
function rangePicker(inpOut, inpRet, getRouteOut, getRouteRet) {
  inpOut.type = 'hidden'; inpRet.type = 'hidden';
  const btn = h('button', { type: 'button', class: 'dp-btn dp-range-btn' });
  const wrap = h('div', { class: 'dp' }, btn, inpOut, inpRet);
  const render = () => {
    const a = inpOut.value, b = inpRet.value;
    btn.replaceChildren(h('span', { class: 'dp-ico', 'aria-hidden': 'true' }, '📅'),
      h('span', { class: a ? 'dp-val' : 'dp-val empty', text: a ? fmtFull(a) : 'Andata' }),
      h('span', { class: 'dp-arrow', 'aria-hidden': 'true' }, '→'),
      h('span', { class: b ? 'dp-val' : 'dp-val empty', text: b ? fmtFull(b) : 'Ritorno' }));
  };
  hijackValue(inpOut, render); hijackValue(inpRet, render);
  render();
  btn.addEventListener('click', () => {
    if (openPicker && openPicker.dataset.owner === 'range') { closePicker(); return; }
    closePicker();
    const today = todayIso();
    let phase = inpOut.value ? 'ret' : 'out';
    const start = inpOut.value || today;
    let y = Number(start.slice(0, 4)), m = Number(start.slice(5, 7)) - 1;
    const count = window.innerWidth >= 760 ? 2 : 1;
    const pop = h('div', { class: 'dp-pop dp-big', role: 'dialog', 'aria-label': 'Scegli andata e ritorno' });
    pop.dataset.owner = 'range';
    const fire = inp => inp.dispatchEvent(new Event('change', { bubbles: true }));
    const draw = () => {
      const out = inpOut.value, ret = inpRet.value;
      const steps = h('div', { class: 'dp-steps' },
        h('button', { type: 'button', class: 'dp-step' + (phase === 'out' ? ' on' : ''), onclick: () => { phase = 'out'; draw(); } },
          h('small', { text: '1 · Andata' }), h('b', { text: out ? fmtFull(out) : 'scegli il giorno' })),
        h('button', { type: 'button', class: 'dp-step' + (phase === 'ret' ? ' on' : ''), disabled: !out, onclick: () => { phase = 'ret'; draw(); } },
          h('small', { text: '2 · Ritorno' }), h('b', { text: ret ? fmtFull(ret) : 'scegli il giorno' })));
      renderCalendar2(pop, {
        y, m, count, title: steps,
        min: phase === 'ret' && out ? out : today,
        route: phase === 'out' ? getRouteOut() : getRouteRet(),
        marks: ds => (ds === out ? ' sel out' : '') + (ds === ret ? ' sel ret' : '') + (out && ret && ds > out && ds < ret ? ' inrange' : ''),
        onPick: ds => {
          if (phase === 'out') {
            inpOut.value = ds; fire(inpOut);
            if (inpRet.value && inpRet.value < ds) { inpRet.value = ''; fire(inpRet); }
            phase = 'ret';
            [y, m] = [Number(ds.slice(0, 4)), Number(ds.slice(5, 7)) - 1]; // mostra dal mese dell'andata
            draw();
          } else {
            inpRet.value = ds; fire(inpRet);
            closePicker();
          }
        },
        onNav: k => { [y, m] = addMonth(y, m, k); draw(); },
      });
    };
    draw();
    openPop(wrap, pop);
  });
  return wrap;
}

/* ---------- stato del form: catena di aeroporti ----------
   stops = caselle esplicite [Da, A, tappe...]
   ritorno: con 2 caselle è sottinteso (A → Da); con più caselle compare la
   casella «Ritorno a» precompilata con gli aeroporti di partenza.
   retOn = false → nessun volo di ritorno (solo andata / multi-città aperto). */
const el = {};
const MAX_LEGS = 5;
const stops = [];      // [{ id, field, wrap }]
let retBox = null;     // { id, field, wrap } quando la casella Ritorno è visibile
let retOn = true;
let dateInputs = [];   // una data per volo
let stopSeq = 0;
let pendingDates = null; // date riallineate dopo aver aggiunto/tolto caselle
const curDates = () => dateInputs.map(i => i.value);

function legsCodes() {
  // [[origini, destinazioni], ...] per ogni volo
  const legs = [];
  for (let i = 0; i < stops.length - 1; i++) legs.push([stops[i].field.codes, stops[i + 1].field.codes]);
  if (retOn && stops.length >= 2) {
    const home = stops.length === 2 ? stops[0].field.codes : (retBox ? retBox.field.codes : []);
    legs.push([stops[stops.length - 1].field.codes, home]);
  }
  return legs;
}
const legCount = () => legsCodes().length;
function isRoundTrip() { return retOn && stops.length === 2; }
function legName(i) {
  const legs = legsCodes();
  const [from, to] = legs[i] || [[], []];
  const route = (from.length ? from.join('/') : '…') + ' → ' + (to.length ? to.join('/') : '…');
  if (isRoundTrip()) return (i === 0 ? 'Andata' : 'Ritorno') + ' · ' + route;
  if (retOn && i === legs.length - 1) return 'Ritorno · ' + route;
  if (legs.length === 1) return 'Andata · ' + route;
  return `Volo ${i + 1} · ${route}`;
}

function makeStop(codes, label, placeholder) {
  const id = 'stop-' + (++stopSeq);
  const fieldRoot = h('div', { class: 'field', id });
  const removeBtn = h('button', { type: 'button', class: 'stop-x', title: 'Rimuovi questa casella', 'aria-label': 'Rimuovi questa casella' }, '×');
  const wrap = h('div', { class: 'stop' }, fieldRoot, removeBtn);
  $('#stops').append(wrap);
  const field = makeChipField(id, id, label, placeholder);
  field.setLabel(label);
  if (codes && codes.length) field.set(codes);
  return { id, field, wrap, removeBtn };
}
function addStop(codes) {
  const st = makeStop(codes, 'Poi verso', 'Città o codice…');
  st.removeBtn.addEventListener('click', () => removeStop(st));
  stops.push(st);
  return st;
}
function ensureRetBox(codes) {
  if (retBox) return retBox;
  retBox = makeStop(codes, 'Ritorno a', 'Città o codice…');
  retBox.wrap.classList.add('ret');
  retBox.removeBtn.addEventListener('click', askNoReturn);
  return retBox;
}
function dropRetBox() {
  if (!retBox) return;
  retBox.wrap.remove();
  delete chipFields[retBox.id];
  retBox = null;
}
function removeStop(st) {
  const i = stops.indexOf(st);
  if (i < 2) return; // Da e A restano sempre
  // togliere la casella i unisce il volo che ci arriva (i-1) e quello che ne parte (i):
  // se il secondo è il ritorno si tiene la sua data, altrimenti quella del primo
  const d = curDates(); d.splice(retOn && i === stops.length - 1 ? i - 1 : i, 1); pendingDates = d;
  stops.splice(i, 1);
  st.wrap.remove();
  delete chipFields[st.id];
  if (stops.length === 2) dropRetBox(); // torna andata e ritorno sottinteso
  layoutStops();
}
function plusClicked() {
  if (legCount() >= MAX_LEGS) return;
  const d = curDates();
  const st = addStop([]);
  if (retOn && stops.length === 3) ensureRetBox(stops[0].field.codes.slice());
  d.splice(stops.length - 2, 0, ''); pendingDates = d; // nuovo volo prima del ritorno
  layoutStops();
  st.wrap.querySelector('input').focus();
}
async function askNoReturn() {
  const ok = await confirmDialog('Sei sicuro di non voler cercare un volo di ritorno?', 'Sì, niente ritorno', 'No, tienilo');
  if (!ok) return;
  const d = curDates(); d.pop(); pendingDates = d;
  retOn = false;
  dropRetBox();
  layoutStops();
}
function restoreReturn() {
  const d = curDates(); d.push(''); pendingDates = d;
  retOn = true;
  if (stops.length >= 3) ensureRetBox(stops[0].field.codes.slice());
  layoutStops();
}

function layoutStops() {
  const box = $('#stops');
  box.querySelectorAll('.stop-sep').forEach(n => n.remove());
  stops.forEach((st, i) => {
    st.field.setLabel(i === 0 ? 'Da' : i === 1 ? 'A' : 'Poi verso');
    st.field.setPlaceholder(i === 0 ? 'Città o codice (es. BRI)…' : i === 1 ? 'Città o codice (es. MXP)…' : 'Città o codice (es. TRN)…');
    st.wrap.classList.toggle('removable', i >= 2);
    box.append(st.wrap);
    if (i < stops.length - 1) {
      box.append(i === 0 && stops.length === 2
        ? h('button', { type: 'button', class: 'icon-btn stop-sep', title: 'Inverti Da / A', 'aria-label': 'Inverti Da e A', onclick: swapFirst }, '⇄')
        : h('span', { class: 'stop-sep arrow', 'aria-hidden': 'true' }, '→'));
    }
  });
  // il + sta dopo l'ultima tappa, al posto della freccia verso il ritorno
  box.append(h('button', { type: 'button', class: 'icon-btn stop-sep plus', title: 'Aggiungi una tappa', 'aria-label': 'Aggiungi una tappa',
    disabled: legCount() >= MAX_LEGS, onclick: plusClicked }, '+'));
  if (retBox) { retBox.wrap.classList.add('removable'); box.append(retBox.wrap); }
  syncDates();
  rebuildFilters();
  document.dispatchEvent(new CustomEvent('formchange'));
}
function swapFirst() {
  if (stops.length !== 2) return;
  const a = stops[0].field.codes.slice(), b = stops[1].field.codes.slice();
  stops[0].field.set(b); stops[1].field.set(a);
}

function syncDates() {
  const box = $('#dates');
  closePicker();
  const old = pendingDates || curDates();
  pendingDates = null;
  const n = legCount();
  box.replaceChildren();
  dateInputs = [];
  const today = new Date().toISOString().slice(0, 10);
  if (isRoundTrip()) {
    // andata e ritorno semplice: un solo calendario grande per le due date
    const inpOut = h('input', { type: 'hidden', min: today }), inpRet = h('input', { type: 'hidden', min: today });
    inpOut.value = old[0] || ''; inpRet.value = old[1] || '';
    const head = h('span', { class: 'date-head' }, h('span', { class: 'date-t', text: rangeName() }),
      h('button', { type: 'button', class: 'date-x', title: 'Nessun volo di ritorno', 'aria-label': 'Nessun volo di ritorno', onclick: e => { e.preventDefault(); askNoReturn(); } }, '×'));
    dateInputs = [inpOut, inpRet];
    box.append(h('div', { class: 'lab date-lab date-range' }, head,
      rangePicker(inpOut, inpRet, () => legsCodes()[0] || [[], []], () => legsCodes()[1] || [[], []])));
    return;
  }
  for (let i = 0; i < n; i++) {
    const inp = h('input', { type: 'date', required: true, min: today });
    inp.value = old[i] || '';
    const head = h('span', { class: 'date-head' }, h('span', { class: 'date-t', text: legName(i) }));
    inp.dataset.pid = 'd' + i;
    const legIdx = i;
    const lab = h('div', { class: 'lab date-lab' }, head, datePicker(inp, () => legsCodes()[legIdx] || [[], []]));
    inp.addEventListener('change', () => {
      for (let j = i + 1; j < dateInputs.length; j++) {
        dateInputs[j].min = inp.value || today;
        if (dateInputs[j].value && inp.value && dateInputs[j].value < inp.value) dateInputs[j].value = inp.value;
      }
    });
    dateInputs.push(inp);
    box.append(lab);
  }
  if (!retOn) {
    box.append(h('div', { class: 'no-ret' },
      h('span', { class: 'hint', text: stops.length === 2 ? 'Solo andata' : 'Senza ritorno' }),
      h('button', { type: 'button', class: 'add-ret', onclick: restoreReturn }, '↩ Aggiungi ritorno')));
  }
  for (let j = 1; j < dateInputs.length; j++) dateInputs[j].min = dateInputs[j - 1].value || today;
}
function rangeName() {
  const [o, d] = legsCodes()[0] || [[], []];
  return `Andata e ritorno · ${o.length ? o.join('/') : '…'} ⇄ ${d.length ? d.join('/') : '…'}`;
}
function refreshDateLabels() {
  if (isRoundTrip()) { const t = $('#dates .date-t'); if (t) t.textContent = rangeName(); return; }
  $('#dates').querySelectorAll('.date-t').forEach((t, i) => { t.textContent = legName(i); });
}

function rebuildFilters() {
  const saved = {};
  document.querySelectorAll('[data-f]').forEach(e => { saved[e.dataset.f] = e.type === 'checkbox' ? e.checked : e.value; });
  const tabs = $('#ftabs'), panels = $('#fpanels');
  const activeTab = (tabs.querySelector('.tab.active') || {}).dataset;
  tabs.replaceChildren(); panels.replaceChildren();
  const n = Math.max(1, legCount());
  for (let i = 0; i < n; i++) {
    const title = legName(i);
    tabs.append(h('button', { type: 'button', class: 'tab', 'data-tab': String(i), role: 'tab' }, title.split(' · ')[0]));
    panels.append(filterPanel(String(i), title));
  }
  document.querySelectorAll('[data-f]').forEach(e => {
    if (!(e.dataset.f in saved)) return;
    if (e.type === 'checkbox') e.checked = !!saved[e.dataset.f]; else e.value = saved[e.dataset.f];
  });
  const want = activeTab && activeTab.tab && Number(activeTab.tab) < n ? activeTab.tab : '0';
  selectTab(want);
  tabs.classList.toggle('single', n === 1);
}
function selectTab(k) {
  document.querySelectorAll('#ftabs .tab').forEach(x => x.classList.toggle('active', x.dataset.tab === k));
  document.querySelectorAll('#fpanels .fpanel').forEach(p => p.classList.toggle('active', p.dataset.panel === k));
}

/* finestra di conferma */
function confirmDialog(message, yes, no) {
  return new Promise(resolve => {
    const dlg = h('dialog', { class: 'confirm' },
      h('p', { text: message }),
      h('div', { class: 'confirm-actions' },
        h('button', { type: 'button', class: 'btn', value: 'no' }, no || 'Annulla'),
        h('button', { type: 'button', class: 'btn fill', value: 'yes' }, yes || 'Conferma')));
    document.body.append(dlg);
    let done = false;
    const finish = v => { if (done) return; done = true; dlg.close(); dlg.remove(); resolve(v); };
    dlg.addEventListener('click', e => {
      const b = e.target.closest('button');
      if (b) finish(b.value === 'yes');
      else if (e.target === dlg) finish(false); // clic fuori
    });
    dlg.addEventListener('cancel', e => { e.preventDefault(); finish(false); });
    if (typeof dlg.showModal === 'function') { dlg.showModal(); dlg.querySelector('[value=no]').focus(); }
    else finish(window.confirm(message));
  });
}

function collectForm() {
  const filters = {};
  document.querySelectorAll('[data-f]').forEach(e => { filters[e.dataset.f] = e.type === 'checkbox' ? e.checked : e.value; });
  return {
    v: 3,
    stops: stops.map(s => s.field.codes.slice()),
    ret: { on: retOn, codes: retBox ? retBox.field.codes.slice() : null },
    legs: legsCodes().map(([a, b]) => [a.slice(), b.slice()]),
    dates: dateInputs.map(i => i.value),
    adults: el.adults.value, minhours: el.minhours.value,
    filters,
  };
}
function migrateForm(s) {
  if (!s || typeof s !== 'object' || s.v === 3) return s;
  if (s.v !== 2) {
    // formato originale (Da/A + data ritorno)
    const filters = {};
    Object.entries(s.filters || {}).forEach(([k, v]) => { filters[k.replace(/^o\./, '0.').replace(/^i\./, '1.')] = v; });
    const round = !s.oneway && !!s.ret;
    return { v: 3, stops: [s.from || [], s.to || []], ret: { on: round, codes: null }, dates: [s.depart || '', round ? s.ret : ''],
      flex: s.flex, adults: s.adults, minhours: s.minhours, filters };
  }
  // v2: catena esplicita; se l'ultima casella torna agli aeroporti di partenza è il ritorno
  const st = s.stops || [];
  const first = st[0] || [], last = st[st.length - 1] || [];
  const back = st.length >= 3 && last.length && last.every(c => first.includes(c));
  if (back) {
    const body = st.slice(0, -1);
    return Object.assign({}, s, { v: 3, stops: body, ret: { on: true, codes: body.length === 2 ? null : last } });
  }
  return Object.assign({}, s, { v: 3, ret: { on: false, codes: null } });
}
function restoreForm(s) {
  s = migrateForm(s);
  const today = new Date().toISOString().slice(0, 10);
  const list = (s && Array.isArray(s.stops) && s.stops.length >= 2) ? s.stops : [[], []];
  list.slice(0, MAX_LEGS + 1).forEach(c => addStop(c));
  retOn = !(s && s.ret && s.ret.on === false);
  if (retOn && stops.length >= 3) ensureRetBox((s && s.ret && s.ret.codes) || stops[0].field.codes.slice());
  layoutStops();
  if (s) {
    (s.dates || []).forEach((d, i) => { if (dateInputs[i] && d && d >= today) dateInputs[i].value = d; });
    for (let j = 1; j < dateInputs.length; j++) {
      dateInputs[j].min = dateInputs[j - 1].value || today;
      if (dateInputs[j].value && dateInputs[j].value < dateInputs[j].min) dateInputs[j].value = '';
    }
    if (s.adults) el.adults.value = s.adults;
    if (s.minhours != null && s.minhours !== '') el.minhours.value = s.minhours;
    if (s.filters) {
      let any = false;
      document.querySelectorAll('[data-f]').forEach(e => {
        if (!(e.dataset.f in s.filters)) return;
        const v = s.filters[e.dataset.f];
        if (e.type === 'checkbox') e.checked = !!v; else e.value = v;
        if (v && e.type !== 'checkbox' && !(e.dataset.f.endsWith('threshold') && String(v) === '6')) any = true;
        if (v === true) any = true;
      });
      if (any) $('#filters-box').open = true;
    }
  }
}

function estimate(s) {
  let n = 0;
  s.legs.forEach(([o, d]) => {
    n += o.filter(x => !d.includes(x)).length * d.length + o.filter(x => d.includes(x)).length * (d.length - 1);
  });
  return n;
}
function updateEstimate() {
  const s = collectForm(), n = estimate(s), e = $('#estimate');
  refreshDateLabels();
  const plus = document.querySelector('.stop-sep.plus');
  if (plus) plus.disabled = legCount() >= MAX_LEGS;
  if (s.legs.some(([o, d]) => !o.length || !d.length)) { e.textContent = 'Inserisci almeno un aeroporto in ogni casella.'; e.className = 'estimate'; return; }
  e.textContent = `~${n} ${n === 1 ? 'ricerca' : 'ricerche'} su Google Flights` + (n > 48 ? ' — troppe: riduci aeroporti o tappe.' : '');
  e.className = 'estimate' + (n > 48 ? ' warn' : '');
}

function buildFilters(s, dir) {
  const g = n => s.filters[`${dir}.${n}`];
  const numOrNull = (v, mult = 1) => { if (v === '' || v == null) return null; const x = parseFloat(v); return isFinite(x) && x >= 0 ? Math.round(x * mult) : null; };
  const th = parseFloat(g('threshold'));
  const stopsSel = g('max_stops');
  return {
    depart_from: g('depart_from') || null, depart_to: g('depart_to') || null,
    arrive_from: g('arrive_from') || null, arrive_to: g('arrive_to') || null,
    max_stops: stopsSel === '' || stopsSel == null ? null : Number(stopsSel),
    min_layover: numOrNull(g('min_layover')),
    max_layover: numOrNull(g('max_layover'), 60),
    long_layover_only: !!g('long_only'),
    long_layover_threshold: isFinite(th) && th >= 1 ? Math.round(th * 60) : 360,
    max_price: numOrNull(g('max_price')),
    max_duration: numOrNull(g('max_duration'), 60),
  };
}

/* ---------- ricerca ---------- */
let busy = false, timer = null;
async function onSubmit(ev) {
  ev.preventDefault();
  if (busy) return;
  const s = collectForm();
  const err = $('#form-error');
  err.hidden = true;
  const fail = m => { err.textContent = m; err.hidden = false; };
  if (!s.stops[0].length) return fail('Scegli almeno un aeroporto di partenza.');
  for (let i = 1; i < s.stops.length; i++) if (!s.stops[i].length) return fail(`Manca l'aeroporto della casella ${i + 1}: compilala o rimuovila con ×.`);
  if (s.ret.on && s.ret.codes && !s.ret.codes.length) return fail('Manca l\'aeroporto di ritorno: compilalo o togli il ritorno con ×.');
  for (let i = 0; i < s.dates.length; i++) {
    if (!s.dates[i]) return fail(`Indica la data del volo ${i + 1}.`);
    if (i && s.dates[i] < s.dates[i - 1]) return fail(`La data del volo ${i + 1} è prima di quella del volo ${i}.`);
  }
  LS.set('psb_form', s);
  const body = {
    legs: s.legs.map(([o, d], i) => ({ origins: o, destinations: d, date: s.dates[i], filters: buildFilters(s, String(i)) })),
    flex_days: 0,
    adults: Math.min(9, Math.max(1, parseInt(s.adults, 10) || 1)),
    min_hours_at_destination: Math.min(72, Math.max(0, parseInt(s.minhours, 10) || 0)),
  };

  busy = true;
  $('#go').disabled = true;
  $('#results').hidden = true;
  const prog = $('#progress'); prog.hidden = false;
  const n = estimate(s), t0 = Date.now();
  $('#prog-sub').textContent = `${n} ${n === 1 ? 'ricerca' : 'ricerche'} in corso: può richiedere fino a 40 secondi.`;
  const tick = () => { $('#prog-text').textContent = `Cerco voli… ${Math.round((Date.now() - t0) / 1000)} s`; };
  tick(); timer = setInterval(tick, 500);
  try {
    const data = await api('/api/search', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' }, body: JSON.stringify(body) });
    renderResults(data, body);
  } catch (e) {
    fail(e.message || 'Errore durante la ricerca.');
  } finally {
    clearInterval(timer); prog.hidden = true; busy = false; $('#go').disabled = false;
  }
}

/* ---------- risultati ---------- */
let stayRefreshers = [];
function airportInfo(data, code) { return (data.airports && data.airports[code]) || apCache[code] || { iata: code, city: code, country: '' }; }

function layoverBadges(it, thr, data, opts) {
  if (!it.layovers || !it.layovers.length) return null;
  const wrap = h('span', { class: 'lay' });
  it.layovers.forEach(l => {
    const free = l.minutes >= thr;
    const city = l.city || (airportInfo(data, l.airport).city);
    const txt = `Scalo ${fmtDur(l.minutes)} a ${city}`;
    if (free) {
      wrap.append(h('span', { class: 'badge free', title: 'Scalo lungo: puoi uscire e visitare la città' },
        'città gratis · ' + txt + (l.overnight ? ' · notte' : '')));
      if (opts && opts.onStay) wrap.append(h('button', { type: 'button', class: 'lay-btn', onclick: e => { e.preventDefault(); e.stopPropagation(); opts.onStay(l); } }, 'Dove dormire'));
    } else wrap.append(h('span', { class: 'badge' }, txt + (l.overnight ? ' · notte' : '')));
  });
  return wrap;
}
const stopsTxt = it => it.stops === 0 ? 'diretto' : it.stops === 1 ? '1 scalo' : it.stops + ' scali';

function itineraryRow(it, thr, data, guests) {
  const route = `${it.origin} ${airportInfo(data, it.origin).city} → ${it.destination} ${airportInfo(data, it.destination).city}`;
  const pd = plusDay(it);
  const det = h('details', { class: 'it' });
  const slot = h('div', { class: 'stay-slot' });
  const stayOpened = new Set();
  const onStay = l => {
    det.open = true;
    if (stayOpened.has(l.airport + l.minutes)) return;
    stayOpened.add(l.airport + l.minutes);
    const seg = it.segments.find(sg => sg.destination === l.airport);
    const cin = dateOf(seg ? seg.arrival : it.departure);
    const info = airportInfo(data, l.airport);
    slot.append(stayPanel({ city: l.city || info.city, country: info.country, checkin: cin, checkout: addDays(cin, 1), guests, inner: true }));
  };
  const sum = h('summary', null,
    h('div', { class: 'it-price', text: money(it.price) }),
    h('div', { class: 'it-line' },
      h('span', { class: 'it-times' }, `${timeOf(it.departure)} → ${timeOf(it.arrival)}`, pd ? h('sup', { text: ' +' + pd }) : null),
      h('span', { class: 'it-date', text: fmtDate(dateOf(it.departure)) })),
    h('div', { class: 'it-route', text: route }),
    h('div', { class: 'it-meta' },
      `${fmtDur(it.duration)} · ${(it.airlines || []).join(', ') || '—'} · `,
      h('span', { class: 'badge' + (it.stops === 0 ? ' direct' : '') }, stopsTxt(it)), ' ',
      layoverBadges(it, thr, data, { onStay })));
  const detail = h('div', { class: 'it-detail' });
  it.segments.forEach((sg, i) => {
    detail.append(h('div', { class: 'seg' },
      h('div', { class: 'sh' }, `${timeOf(sg.departure)} ${sg.origin} → ${timeOf(sg.arrival)} ${sg.destination}`, ` · ${fmtDate(dateOf(sg.departure))}`),
      h('div', { class: 'sm' }, [sg.flight_number, sg.airline, sg.aircraft, fmtDur(sg.duration)].filter(Boolean).join(' · '),
        ` — ${sg.origin_name || sg.origin} → ${sg.destination_name || sg.destination}`)));
    const l = it.layovers && it.layovers[i];
    if (l) detail.append(h('div', { class: 'lay-row' + (l.minutes >= thr ? ' free' : '') },
      `Scalo ${fmtDur(l.minutes)} a ${l.city || l.airport} (${l.airport})` + (l.overnight ? ' · notte' : '') + (l.minutes >= thr ? ' · città gratis' : '')));
  });
  detail.append(slot);
  if (it.booking_url) detail.append(h('div', { class: 'clinks' }, h('a', { class: 'btn fill', href: it.booking_url, target: '_blank', rel: 'noopener noreferrer' }, 'Prenota')));
  det.append(sum, detail);
  return det;
}

const SORTS = [
  ['price', 'Prezzo', (a, b) => (a.price ?? 1e12) - (b.price ?? 1e12)],
  ['duration', 'Durata', (a, b) => (a.duration ?? 1e12) - (b.duration ?? 1e12)],
  ['departure', 'Partenza', (a, b) => (a.departure || '').localeCompare(b.departure || '')],
  ['layover', 'Scalo più lungo', (a, b) => (b.max_layover || 0) - (a.max_layover || 0)],
];

function itineraryList(title, items, thr, data, guests) {
  const sec = h('section');
  const list = h('div', { class: 'list' });
  const bar = h('div', { class: 'sort' }, 'Ordina:');
  const heading = h('h2');
  const dayChip = h('button', { type: 'button', class: 'day-chip', hidden: true, title: 'Mostra tutte le date' });
  let cur = 'price', day = null;
  const draw = () => {
    list.replaceChildren();
    const shown = day ? items.filter(it => dateOf(it.departure) === day) : items;
    heading.textContent = `${title} (${shown.length})`;
    dayChip.hidden = !day;
    if (day) dayChip.textContent = `Solo ${fmtDate(day)} ×`;
    if (!shown.length) { list.append(h('div', { class: 'empty-state' }, 'Nessun volo trovato con questi filtri.')); return; }
    const fn = SORTS.find(s => s[0] === cur)[2];
    shown.slice().sort(fn).forEach(it => list.append(itineraryRow(it, thr, data, guests)));
  };
  dayChip.addEventListener('click', () => { day = null; draw(); if (sec.onDay) sec.onDay(null); });
  sec.setDay = d => { day = d; draw(); };
  SORTS.forEach(([k, label]) => {
    const b = h('button', { type: 'button', class: k === cur ? 'on' : '' }, label);
    b.addEventListener('click', () => { cur = k; bar.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b)); draw(); });
    bar.append(b);
  });
  sec.append(h('div', { class: 'sec-head' }, h('div', { class: 'sec-title-row' }, heading, dayChip), bar), list);
  draw();
  return sec;
}

function comboLeg(tag, it, thr, data) {
  if (!it) return null;
  const pd = plusDay(it);
  return h('div', { class: 'cleg' },
    h('div', { class: 'l1' }, h('span', { class: 'tag', text: tag }),
      h('span', { text: fmtDate(dateOf(it.departure)) }),
      h('span', { class: 'tm' }, `${timeOf(it.departure)} → ${timeOf(it.arrival)}`, pd ? ' +' + pd : ''),
      h('span', { text: `${it.origin} → ${it.destination}` })),
    h('div', { class: 'l2' }, `${(it.airlines || []).join(', ') || '—'} · ${stopsTxt(it)} · ${fmtDur(it.duration)} `, layoverBadges(it, thr, data)));
}

function legTitle(req, i) {
  const n = req.legs.length;
  const l = req.legs[i];
  const route = `${l.origins.join('/')} → ${l.destinations.join('/')}`;
  const round = n === 2 && req.legs[1].destinations.every(x => req.legs[0].origins.includes(x));
  if (round) return (i === 0 ? 'Andata' : 'Ritorno') + ' · ' + route;
  return `Volo ${i + 1} · ${route}`;
}

function renderCombos(data, req, thr) {
  const maps = data.legs.map(l => new Map(l.itineraries.map(i => [i.key, i])));
  const combos = (data.combos || []).filter(c => c.keys.every((k, i) => maps[i] && maps[i].has(k)));
  const n = data.legs.length;
  const round = n === 2 && req.legs[1].destinations.every(x => req.legs[0].origins.includes(x));
  const sec = h('section', null, h('div', { class: 'sec-head' }, h('h2', null, round ? 'Migliori combinazioni A/R' : 'Migliori combinazioni del viaggio')));
  if (!combos.length) {
    const empty = data.legs.filter(l => !l.itineraries.length).map(l => `volo ${l.index + 1}`);
    sec.append(h('div', { class: 'empty-state' }, empty.length
      ? `Nessuna combinazione: non ci sono voli per ${empty.join(', ')}. Se gli aeroporti sono vicini (es. Malpensa–Torino) conviene treno o bus: togli quella tappa e cerca i voli separatamente.`
      : 'Nessuna combinazione compatibile: gli orari dei voli non si incastrano (prova a ridurre le «ore minime a destinazione» o a spostare le date).'));
    return sec;
  }
  const grid = h('div', { class: 'combos' });
  const more = h('button', { type: 'button', class: 'btn', style: 'margin-top:8px' });
  let shown = 6;
  const tagOf = i => round ? (i === 0 ? 'Andata' : 'Ritorno') : `Volo ${i + 1}`;
  const draw = () => {
    grid.replaceChildren();
    combos.slice(0, shown).forEach(c => {
      const its = c.keys.map((k, i) => maps[i].get(k));
      const diff = c.same_airport_connections.some(x => !x) || (round && !c.returns_home);
      const nightsTxt = c.nights.length === 1
        ? `${c.nights[0]} ${c.nights[0] === 1 ? 'notte' : 'notti'}`
        : c.nights.map((x, i) => `${x} ${x === 1 ? 'notte' : 'notti'} a ${airportInfo(data, its[i].destination).city}`).join(' · ');
      const legsEls = [];
      its.forEach((it, i) => {
        legsEls.push(comboLeg(tagOf(i), it, thr[i], data));
      });
      grid.append(h('div', { class: 'combo' },
        h('div', { class: 'combo-top' },
          h('span', { class: 'total', text: money(c.total) }),
          h('span', null, h('span', { class: 'badge', text: nightsTxt }), ' ',
            diff ? h('span', { class: 'badge diff', text: 'aeroporti diversi' }) : null)),
        legsEls,
        h('div', { class: 'clinks' },
          its.map((it, i) => it.booking_url ? h('a', { class: 'btn', href: it.booking_url, target: '_blank', rel: 'noopener noreferrer' }, round ? `Prenota ${tagOf(i).toLowerCase()}` : `Prenota volo ${i + 1}`) : null)),
        (c.links && c.links.length) ? h('div', { class: 'clinks rt' },
          h('span', { class: 'rt-label', text: c.same_airline
            ? (n === 2 ? 'Stessa compagnia, stessi aeroporti: puoi prenotare insieme' : 'Stessa compagnia, tappe collegate: puoi prenotare insieme')
            : (n === 2 ? 'Stessi aeroporti: confronta il prezzo A/R' : 'Tappe collegate: confronta il prezzo multi-città') }),
          c.links.map(l => h('a', { class: 'btn fill', href: l.url, target: '_blank', rel: 'noopener noreferrer' }, l.label))) : null));
    });
    more.hidden = combos.length <= shown;
    more.textContent = `Mostra tutte le ${combos.length} combinazioni`;
  };
  more.addEventListener('click', () => { shown = combos.length; draw(); });
  draw();
  sec.append(grid, more);
  return sec;
}

/* ---------- prezzi per giorno ---------- */
function priceStrip(tag, days, onPick) {
  const prices = days.map(d => d.price).filter(p => p != null);
  const max = Math.max(...prices, 1), min = Math.min(...prices);
  const row = h('div', { class: 'pstrip', role: 'group', 'aria-label': `Prezzi per giorno, ${tag}` });
  let sel = null;
  const cols = days.map(d => {
    const has = d.price != null;
    const pct = has ? Math.max(8, Math.round((d.price / max) * 100)) : 0;
    const b = h('button', {
      type: 'button', class: 'pday' + (has && d.price === min ? ' best' : '') + (has ? '' : ' none'), disabled: !has,
      title: has ? `${fmtDate(d.date)}: da ${money(d.price)} (${d.route}, ${d.airline}) · ${d.count} voli` : `${fmtDate(d.date)}: nessun volo`,
    },
      h('span', { class: 'pval', text: has ? money(d.price) : '—' }),
      h('span', { class: 'pbar-wrap' }, h('span', { class: 'pbar', style: `height:${pct}%` })),
      h('span', { class: 'pdate', text: fmtDate(d.date) }));
    b.addEventListener('click', () => { sel = sel === d.date ? null : d.date; mark(); onPick(sel); });
    return [d.date, b];
  });
  const mark = () => cols.forEach(([dt, b]) => b.classList.toggle('on', dt === sel));
  row.setSel = d => { sel = d; mark(); };
  cols.forEach(([, b]) => row.append(b));
  return h('div', { class: 'pstrip-box' }, h('div', { class: 'ptag', text: tag }), row);
}

/* ---------- alloggi ---------- */
function getBudget() { const b = Number(LS.get('psb_budget', 40)); return b >= 1 ? b : 40; }
function stayPanel({ city, country, checkin, checkout, guests, inner, title }) {
  const box = h('div', { class: 'stay-links' });
  const budget = h('input', { type: 'number', min: 1, max: 1000, value: getBudget(), inputmode: 'numeric', 'aria-label': 'Budget per notte' });
  const nights = Math.max(1, dayNum(checkout) - dayNum(checkin));
  const panel = h('div', { class: 'stay-panel' + (inner ? ' inner' : '') },
    h('div', { class: 'stay-head' },
      h('strong', null, title || `Dove dormire a ${city}`),
      h('label', { class: 'bud' }, 'Budget a notte', budget, currency)),
    h('div', { class: 'hint', text: `${fmtDate(checkin)} → ${fmtDate(checkout)} · ${nights} ${nights === 1 ? 'notte' : 'notti'} · ${guests} ${guests === 1 ? 'ospite' : 'ospiti'}` }),
    box);
  let seq = 0;
  async function load() {
    const my = ++seq;
    box.replaceChildren(h('span', { class: 'hint', text: 'Carico…' }));
    const q = new URLSearchParams({ city, checkin, checkout, guests: String(guests), max_price: String(Math.min(1000, Math.max(1, parseInt(budget.value, 10) || 40))) });
    if (country) q.set('country', country);
    try {
      const links = await api('/api/stays?' + q);
      if (my !== seq) return;
      box.replaceChildren();
      links.forEach(l => box.append(h('a', { href: l.url, target: '_blank', rel: 'noopener noreferrer' },
        h('b', { text: l.provider }), h('em', { text: l.label }), h('span', { text: l.note }))));
      if (!links.length) box.append(h('span', { class: 'hint', text: 'Nessun link disponibile.' }));
    } catch (e) { if (my === seq) box.replaceChildren(h('span', { class: 'hint', text: 'Errore: ' + e.message })); }
  }
  const onBudget = debounce(() => {
    const v = parseInt(budget.value, 10);
    if (!(v >= 1)) return;
    LS.set('psb_budget', v);
    stayRefreshers.forEach(r => r(v, panel));
  }, 500);
  budget.addEventListener('input', onBudget);
  stayRefreshers.push((v, src) => { if (!panel.isConnected) return; if (src !== panel) budget.value = v; load(); });
  load();
  return panel;
}

function renderCalendar(data, req, lists) {
  const strips = data.legs.filter(l => (l.calendar || []).length >= 2);
  if (!strips.length) return null;
  const sec = h('section', { class: 'calendar' },
    h('div', { class: 'sec-head' }, h('h2', null, 'Prezzi per giorno')),
    h('p', { class: 'hint', text: 'Prezzo più basso per ogni data, tra tutti gli aeroporti scelti. Tocca un giorno per vedere solo i voli di quella data.' }));
  strips.forEach(l => {
    const list = lists[l.index];
    const strip = priceStrip(legTitle(req, l.index), l.calendar, d => list.setDay(d));
    list.onDay = d => strip.querySelector('.pstrip').setSel(d);
    sec.append(strip);
  });
  return sec;
}

/* ---------- render complessivo ---------- */
function renderResults(data, req) {
  currency = (data.stats && data.stats.currency) || 'EUR';
  stayRefreshers = [];
  const root = $('#results');
  root.replaceChildren();
  const st = data.stats || {};
  const thr = req.legs.map(l => l.filters.long_layover_threshold);
  const n = data.legs.length;

  root.append(h('div', { class: 'stats' },
    data.legs.map(l => h('span', { text: `${n > 1 ? legTitle(req, l.index).split(' · ')[0] : 'Voli'}: ${l.found} trovati, ${l.after_filters} dopo i filtri` })),
    h('span', { text: `${st.queries ?? 0} ricerche` })));

  if (data.errors && data.errors.length) {
    const ul = h('ul');
    data.errors.forEach(e => ul.append(h('li', { text: `${e.origin} → ${e.destination} (${fmtDate(e.date)}): ${e.error}` })));
    root.append(h('div', { class: 'msg warn' }, `Alcune ricerche sono fallite (${data.errors.length}); i risultati potrebbero essere incompleti:`, ul));
  }

  const lists = data.legs.map(l => itineraryList(n > 1 ? legTitle(req, l.index) : 'Voli', l.itineraries, thr[l.index], data, req.adults));
  if (n > 1) root.append(renderCombos(data, req, thr));
  const calendar = renderCalendar(data, req, lists);
  if (calendar) root.append(calendar);
  data.legs.forEach((l, i) => {
    if (!l.itineraries.length && !l.found) {
      root.append(h('div', { class: 'msg warn' }, `${legTitle(req, i)}: nessun volo trovato. Se gli aeroporti sono vicini conviene treno o bus.`));
    }
    root.append(lists[i]);
  });

  // alloggi: in ogni tappa intermedia, dall'arrivo alla partenza successiva
  const stays = h('section', { class: 'stays' }, h('div', { class: 'sec-head' }, h('h2', null, 'Dove dormire')));
  const home = new Set(req.legs[0].origins);
  req.legs.forEach((l, i) => {
    const last = i === req.legs.length - 1;
    if (last && n > 1 && l.destinations.some(c => home.has(c))) return; // si torna a casa
    const cout = last ? addDays(l.date, 1) : req.legs[i + 1].date;
    const seen = new Set();
    l.destinations.forEach(code => {
      if (seen.has(code)) return; seen.add(code);
      const a = airportInfo(data, code);
      stays.append(stayPanel({ city: a.city, country: a.country, checkin: l.date, checkout: cout, guests: req.adults, title: `Dove dormire a ${a.city} (${code})` }));
    });
  });
  stays.append(h('p', { class: 'hint', text: 'Per gli scali lunghi usa il pulsante «Dove dormire» accanto al badge «città gratis».' }));
  root.append(stays);
  root.hidden = false;
  root.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/* ---------- init ---------- */
function init() {
  ['adults', 'minhours'].forEach(id => { el[id] = $('#' + id); });
  $('#ftabs').addEventListener('click', e => { const t = e.target.closest('.tab'); if (t) selectTab(t.dataset.tab); });

  restoreForm(LS.get('psb_form', null));

  const persist = debounce(() => { LS.set('psb_form', collectForm()); }, 400);
  const onChange = () => { updateEstimate(); persist(); };
  $('#search-form').addEventListener('input', onChange);
  $('#search-form').addEventListener('change', onChange);
  document.addEventListener('formchange', onChange);
  $('#search-form').addEventListener('submit', onSubmit);
  updateEstimate();
}
document.addEventListener('DOMContentLoaded', init);
document.addEventListener('DOMContentLoaded', () => {
  api('/api/me').then(m => { if (m && m.auth_required) $('#logout').hidden = false; }).catch(() => {});
});

/* ---------- tema: sistema / chiaro / scuro ---------- */
(function themeToggle() {
  const ORDER = ['system', 'light', 'dark'];
  const LABEL = { system: ['◐', 'Sistema'], light: ['☀', 'Chiaro'], dark: ['☾', 'Scuro'] };
  const read = () => { try { const t = localStorage.getItem('psb-theme'); return ORDER.includes(t) ? t : 'system'; } catch (e) { return 'system'; } };
  const write = t => { try { if (t === 'system') localStorage.removeItem('psb-theme'); else localStorage.setItem('psb-theme', t); } catch (e) { /* ignora */ } };
  function apply(t) {
    const root = document.documentElement;
    if (t === 'system') delete root.dataset.theme; else root.dataset.theme = t;
    const btn = document.getElementById('theme-btn');
    if (!btn) return;
    btn.querySelector('.ti').textContent = LABEL[t][0];
    btn.querySelector('.tl').textContent = LABEL[t][1];
    btn.setAttribute('aria-label', 'Tema: ' + LABEL[t][1].toLowerCase() + '. Clic per cambiare');
  }
  document.addEventListener('DOMContentLoaded', () => {
    let cur = read();
    apply(cur);
    const btn = document.getElementById('theme-btn');
    if (btn) btn.addEventListener('click', () => {
      cur = ORDER[(ORDER.indexOf(cur) + 1) % ORDER.length];
      write(cur);
      apply(cur);
    });
  });
})();
