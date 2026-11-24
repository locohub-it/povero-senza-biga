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
  root.append(h('span', { class: 'lab-t' }, label), box, groupsEl);
  box.append(input, list);
  let results = [], active = -1, seq = 0;

  const fire = () => document.dispatchEvent(new CustomEvent('formchange'));
  function renderChips() {
    box.querySelectorAll('.chip').forEach(n => n.remove());
    codes.forEach(c => {
      const a = apCache[c];
      box.insertBefore(h('span', { class: 'chip', title: a ? apLabel(a) : c },
        h('b', { text: c }), a ? h('small', { text: a.city }) : null,
        h('button', { type: 'button', 'aria-label': 'Rimuovi ' + c, onclick: () => { remove(c); input.focus(); } }, '×')), input);
    });
    input.placeholder = codes.length ? '' : placeholder;
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
  const f = { codes, set, add, renderGroups };
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
  return h('div', { class: 'fpanel' + (dir === 'o' ? ' active' : ''), 'data-panel': dir },
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

/* ---------- stato del form ---------- */
const el = {};
function collectForm() {
  const filters = {};
  document.querySelectorAll('[data-f]').forEach(e => { filters[e.dataset.f] = e.type === 'checkbox' ? e.checked : e.value; });
  return {
    from: chipFields.from.codes.slice(), to: chipFields.to.codes.slice(),
    rfrom: chipFields.rfrom.codes.slice(), rto: chipFields.rto.codes.slice(),
    depart: el.depart.value, ret: el.ret.value, oneway: el.oneway.checked,
    flex: el.flex.value, adults: el.adults.value, minhours: el.minhours.value,
    filters,
  };
}
function restoreForm(s) {
  if (!s || typeof s !== 'object') return;
  chipFields.from.set(s.from); chipFields.to.set(s.to); chipFields.rfrom.set(s.rfrom); chipFields.rto.set(s.rto);
  if ((s.rfrom && s.rfrom.length) || (s.rto && s.rto.length)) $('#ret-airports').open = true;
  const today = new Date().toISOString().slice(0, 10);
  el.depart.value = s.depart && s.depart >= today ? s.depart : '';
  el.ret.value = s.ret && s.ret >= today && s.ret >= el.depart.value ? s.ret : '';
  el.oneway.checked = !!s.oneway;
  if (s.flex != null) el.flex.value = s.flex;
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
  syncOneway();
}
function syncOneway() {
  el.ret.disabled = el.oneway.checked;
  if (el.oneway.checked) el.ret.value = '';
}
const hasReturn = s => !s.oneway && !!s.ret;
function estimate(s) {
  const o = s.from.length, d = s.to.length;
  const ro = (s.rfrom.length || d), rd = (s.rto.length || o);
  const n = ((o * d) + (hasReturn(s) ? ro * rd : 0)) * (2 * Number(s.flex || 0) + 1);
  return n;
}
function updateEstimate() {
  const s = collectForm(), n = estimate(s), e = $('#estimate');
  if (!s.from.length || !s.to.length) { e.textContent = 'Scegli almeno un aeroporto di partenza e uno di arrivo.'; e.className = 'estimate'; return; }
  e.textContent = `~${n} ${n === 1 ? 'ricerca' : 'ricerche'} su Google Flights` + (n > 48 ? ' — troppe, la richiesta potrebbe essere rifiutata o lentissima: riduci aeroporti o flessibilità.' : '');
  e.className = 'estimate' + (n > 48 ? ' warn' : '');
}

function buildFilters(s, dir) {
  const g = n => s.filters[`${dir}.${n}`];
  const numOrNull = (v, mult = 1) => { if (v === '' || v == null) return null; const x = parseFloat(v); return isFinite(x) && x >= 0 ? Math.round(x * mult) : null; };
  const th = parseFloat(g('threshold'));
  const stops = g('max_stops');
  return {
    depart_from: g('depart_from') || null, depart_to: g('depart_to') || null,
    arrive_from: g('arrive_from') || null, arrive_to: g('arrive_to') || null,
    max_stops: stops === '' || stops == null ? null : Number(stops),
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
  if (!s.from.length) return fail('Scegli almeno un aeroporto di partenza.');
  if (!s.to.length) return fail('Scegli almeno un aeroporto di arrivo.');
  if (!s.depart) return fail('Indica la data di andata.');
  if (hasReturn(s) && s.ret < s.depart) return fail('La data di ritorno è prima di quella di andata.');
  LS.set('psb_form', s);
  const body = {
    origins: s.from, destinations: s.to, depart_date: s.depart,
    return_date: hasReturn(s) ? s.ret : null,
    flex_days: Number(s.flex) || 0,
    adults: Math.min(9, Math.max(1, parseInt(s.adults, 10) || 1)),
    min_hours_at_destination: Math.min(72, Math.max(0, parseInt(s.minhours, 10) || 0)),
    outbound_filters: buildFilters(s, 'o'), inbound_filters: buildFilters(s, 'i'),
  };
  if (s.rfrom.length) body.return_origins = s.rfrom;
  if (s.rto.length) body.return_destinations = s.rto;

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
  let cur = 'price';
  const draw = () => {
    list.replaceChildren();
    if (!items.length) { list.append(h('div', { class: 'empty-state' }, 'Nessun volo trovato con questi filtri.')); return; }
    const fn = SORTS.find(s => s[0] === cur)[2];
    items.slice().sort(fn).forEach(it => list.append(itineraryRow(it, thr, data, guests)));
  };
  SORTS.forEach(([k, label]) => {
    const b = h('button', { type: 'button', class: k === cur ? 'on' : '' }, label);
    b.addEventListener('click', () => { cur = k; bar.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b)); draw(); });
    bar.append(b);
  });
  sec.append(h('div', { class: 'sec-head' }, h('h2', null, `${title} (${items.length})`), bar), list);
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

function renderCombos(data, thrO, thrI) {
  const byO = new Map(data.outbound.map(i => [i.key, i])), byI = new Map(data.inbound.map(i => [i.key, i]));
  const combos = (data.combos || []).filter(c => byO.has(c.outbound) && byI.has(c.inbound));
  const sec = h('section', null, h('div', { class: 'sec-head' }, h('h2', null, 'Migliori combinazioni A/R')));
  if (!combos.length) { sec.append(h('div', { class: 'empty-state' }, 'Nessuna combinazione andata + ritorno compatibile.')); return sec; }
  const grid = h('div', { class: 'combos' });
  const more = h('button', { type: 'button', class: 'btn', style: 'margin-top:8px' });
  let shown = 6;
  const draw = () => {
    grid.replaceChildren();
    combos.slice(0, shown).forEach(c => {
      const o = byO.get(c.outbound), i = byI.get(c.inbound);
      grid.append(h('div', { class: 'combo' },
        h('div', { class: 'combo-top' },
          h('span', { class: 'total', text: money(c.total) }),
          h('span', null, h('span', { class: 'badge', text: `${c.nights} ${c.nights === 1 ? 'notte' : 'notti'}` }), ' ',
            c.same_airports ? null : h('span', { class: 'badge diff', text: 'aeroporti diversi' }))),
        comboLeg('Andata', o, thrO, data), comboLeg('Ritorno', i, thrI, data),
        h('div', { class: 'clinks' },
          o.booking_url ? h('a', { class: 'btn', href: o.booking_url, target: '_blank', rel: 'noopener noreferrer' }, 'Prenota andata') : null,
          i.booking_url ? h('a', { class: 'btn', href: i.booking_url, target: '_blank', rel: 'noopener noreferrer' }, 'Prenota ritorno') : null)));
    });
    more.hidden = combos.length <= shown;
    more.textContent = `Mostra tutte le ${combos.length} combinazioni`;
  };
  more.addEventListener('click', () => { shown = combos.length; draw(); });
  draw();
  sec.append(grid, more);
  return sec;
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

/* ---------- render complessivo ---------- */
function renderResults(data, req) {
  currency = (data.stats && data.stats.currency) || 'EUR';
  stayRefreshers = [];
  const root = $('#results');
  root.replaceChildren();
  const st = data.stats || {};
  const thrO = req.outbound_filters.long_layover_threshold, thrI = req.inbound_filters.long_layover_threshold;
  const round = !!req.return_date;

  root.append(h('div', { class: 'stats' },
    h('span', { text: `Andata: ${st.outbound_found ?? 0} voli trovati, ${st.outbound_after_filters ?? 0} dopo i filtri` }),
    round ? h('span', { text: `Ritorno: ${st.inbound_found ?? 0} voli trovati, ${st.inbound_after_filters ?? 0} dopo i filtri` }) : null,
    h('span', { text: `${st.queries ?? 0} ricerche` })));

  if (data.errors && data.errors.length) {
    const ul = h('ul');
    data.errors.forEach(e => ul.append(h('li', { text: `${e.origin} → ${e.destination} (${fmtDate(e.date)}): ${e.error}` })));
    root.append(h('div', { class: 'msg warn' }, `Alcune ricerche sono fallite (${data.errors.length}); i risultati potrebbero essere incompleti:`, ul));
  }
  if (round) root.append(renderCombos(data, thrO, thrI));
  root.append(itineraryList('Andata', data.outbound, thrO, data, req.adults));
  if (round) root.append(itineraryList('Ritorno', data.inbound, thrI, data, req.adults));

  // alloggi per ogni destinazione
  const stays = h('section', { class: 'stays' }, h('div', { class: 'sec-head' }, h('h2', null, 'Dove dormire')));
  const seen = new Set();
  req.destinations.forEach(code => {
    if (seen.has(code)) return; seen.add(code);
    const a = airportInfo(data, code);
    const cout = req.return_date || addDays(req.depart_date, 1);
    stays.append(stayPanel({ city: a.city, country: a.country, checkin: req.depart_date, checkout: cout, guests: req.adults, title: `Dove dormire a ${a.city} (${code})` }));
  });
  stays.append(h('p', { class: 'hint', text: 'Per gli scali lunghi usa il pulsante «Dove dormire» accanto al badge «città gratis».' }));
  root.append(stays);
  root.hidden = false;
  root.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/* ---------- init ---------- */
function init() {
  chipFields.from = makeChipField('from', 'fld-from', 'Da', 'Città o codice (es. NAP)…');
  chipFields.to = makeChipField('to', 'fld-to', 'A', 'Città o codice (es. BCN)…');
  chipFields.rfrom = makeChipField('rfrom', 'fld-rfrom', 'Ritorno da', 'vuoto = come «A»');
  chipFields.rto = makeChipField('rto', 'fld-rto', 'Ritorno verso', 'vuoto = come «Da»');
  ['depart', 'ret', 'oneway', 'flex', 'adults', 'minhours'].forEach(id => { el[id] = $('#' + id); });

  $('#fpanels').append(filterPanel('o', 'Andata'), filterPanel('i', 'Ritorno'));
  document.querySelectorAll('.tab').forEach(t => t.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(x => x.classList.toggle('active', x === t));
    document.querySelectorAll('.fpanel').forEach(p => p.classList.toggle('active', p.dataset.panel === t.dataset.tab));
  }));

  $('#swap').addEventListener('click', () => {
    const a = chipFields.from.codes.slice(), b = chipFields.to.codes.slice();
    chipFields.from.set(b); chipFields.to.set(a);
  });
  el.oneway.addEventListener('change', syncOneway);
  el.depart.addEventListener('change', () => {
    el.ret.min = el.depart.value;
    if (el.ret.value && el.ret.value < el.depart.value) el.ret.value = el.depart.value;
  });
  el.depart.min = new Date().toISOString().slice(0, 10);

  restoreForm(LS.get('psb_form', null));
  el.ret.min = el.depart.value || el.depart.min;

  const persist = debounce(() => { LS.set('psb_form', collectForm()); }, 400);
  const onChange = () => { updateEstimate(); persist(); };
  $('#search-form').addEventListener('input', onChange);
  $('#search-form').addEventListener('change', onChange);
  document.addEventListener('formchange', onChange);
  $('#search-form').addEventListener('submit', onSubmit);
  updateEstimate();
}
document.addEventListener('DOMContentLoaded', init);
