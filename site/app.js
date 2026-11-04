"use strict";
const C = { id: 0, at: 1, speed: 2, rated: 3, color: 4, rating: 5, diff: 6, opp: 7, oppRating: 8, result: 9, family: 10, acc: 11, blunders: 12, mistakes: 13, reviewed: 14, site: 15, bot: 16, sacrifices: 17, plies: 18, great: 19 };
const SITE_NAMES = { lichess: "Lichess", chesscom: "Chess.com" };
const SPEEDS = ["bullet", "blitz", "rapid", "classical"];
const SERIES = { bullet: "--s1", blitz: "--s2", rapid: "--s3", classical: "--s4" };
const TAG_NAMES = {
  hung_piece: "Left a piece hanging",
  missed_material: "Missed winning a piece",
  allowed_mate: "Allowed a forced mate",
  missed_mate: "Missed a forced mate",
  low_clock: "Slipped under time pressure",
};
const TAG_SHORT = {
  hung_piece: "left a piece hanging", missed_material: "missed winning a piece",
  allowed_mate: "allowed a forced mate", missed_mate: "missed a forced mate", low_clock: "low on time",
};
const app = document.getElementById("app");
const tip = document.getElementById("tip");
const months = {};
let data = null;
let keyHandler = null;

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const dateText = (ms) => new Date(ms).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
const cap = (s) => s[0].toUpperCase() + s.slice(1);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const resultWord = { win: "Won", loss: "Lost", draw: "Drew" };
const pawns = (cp) => Math.abs(cp) >= 1000 ? (cp > 0 ? "winning by force" : "losing by force") : (cp > 0 ? "+" : "") + (cp / 100).toFixed(1);
const plural = (n, one, many) => `${n} ${n === 1 ? one : many || one + "s"}`;
const moveLabel = (ply) => `${Math.ceil(ply / 2)}${ply % 2 ? "." : "..."}`;

async function monthOf(row) {
  const d = new Date(row[C.at]);
  const key = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
  if (!months[key]) {
    const response = await fetch(`data/months/${key}.json`);
    if (!response.ok) throw new Error(`Could not load ${key}`);
    months[key] = await response.json();
  }
  return months[key][row[C.id]];
}

function replay(detail) {
  const game = detail.fen ? new Chess(detail.fen) : new Chess();
  const frames = [game.fen()];
  const marks = [null];
  for (const san of (detail.moves || "").split(" ").filter(Boolean)) {
    const move = game.move(san, { sloppy: true });
    if (!move) return null;
    frames.push(game.fen());
    marks.push([move.from, move.to]);
  }
  return { frames, marks };
}

const MARK_CATEGORY = { "??": "blunder", "?": "mistake", "?!": "inaccuracy", "!": "great", "!!": "brilliant" };
const MARK_NAME = { blunder: "Blunder", mistake: "Mistake", inaccuracy: "Inaccuracy", great: "Great move", brilliant: "Sacrifice" };
function annotations(detail) {
  const marks = {};
  for (const m of detail.moments || []) marks[m.ply] = { blunder: "??", mistake: "?", inaccuracy: "?!" }[m.cat];
  for (const m of detail.opponent_moments || []) marks[m.ply] = { blunder: "??", mistake: "?" }[m.cat];
  for (const p of detail.great || []) marks[p] = "!";
  for (const p of detail.sacrifices || []) marks[p] = "!!";
  return marks;
}

const GLYPH = { k: "♚", q: "♛", r: "♜", b: "♝", n: "♞", p: "♟" };
function boardHTML(fen, flip, mark, label, note) {
  const rows = fen.split(" ")[0].split("/");
  const cells = [];
  rows.forEach((row, rank) => {
    let file = 0;
    for (const ch of row) {
      if (/\d/.test(ch)) { for (let i = 0; i < +ch; i++) cells.push(cell(file++, rank, "")); }
      else cells.push(cell(file++, rank, ch));
    }
  });
  function cell(file, rank, piece) {
    const name = "abcdefgh"[file] + (8 - rank);
    const shade = (file + rank) % 2 ? "d" : "l";
    const hi = mark && mark.includes(name) ? " hi" : "";
    let inner = piece ? `<span class="pc ${piece === piece.toUpperCase() ? "w" : "b"}">${GLYPH[piece.toLowerCase()]}︎</span>` : "";
    if (note && mark && mark[1] === name) {
      const category = MARK_CATEGORY[note];
      inner += `<span class="badge cat-${category}" title="${MARK_NAME[category]}" aria-label="${MARK_NAME[category]}">${note}</span>`;
    }
    return `<div class="sq ${shade}${hi}">${inner}</div>`;
  }
  if (flip) cells.reverse();
  return `<div class="board" role="img" aria-label="${esc(label)}">${cells.join("")}</div>`;
}

const SAN_TOKEN = "(?:O-O(?:-O)?|[KQRBN][a-h1-8]?x?[a-h][1-8]|[a-h]x[a-h][1-8](?:=[QRBN])?|[a-h][1-8](?:=[QRBN])?)[+#]?[!?]*";
const bareMove = (san) => san.replace(/[+#!?]/g, "");

function moveRef(text, ply, gameId) {
  if (gameId) return `<a class="moveref" href="#/game/${gameId}/${ply}">${esc(text)}</a>`;
  return `<button class="moveref" data-ply="${ply}" aria-label="Go to ${esc(text)}">${esc(text)}</button>`;
}

// A move that was played links to itself. An engine alternative links to the position it was available in.
function plyForMove(number, dots, san, sans) {
  const ply = (number - 1) * 2 + (dots === "." ? 1 : 2);
  if (ply < 1 || ply > sans.length) return null;
  return sans[ply - 1] && bareMove(sans[ply - 1]) === bareMove(san) ? ply : ply - 1;
}

function linkMoves(text, detail, gameId) {
  const sans = (detail.moves || "").split(" ").filter(Boolean);
  if (detail.fen || !sans.length) return esc(text);
  const pattern = new RegExp(`(?<![\\w.])(\\d+)(\\.{1,3})\\s?(${SAN_TOKEN})|\\b([Mm]ove )(\\d+)\\b`, "g");
  let html = "", last = 0;
  for (const match of text.matchAll(pattern)) {
    let ply = null, shown = match[0], prefix = "";
    if (match[3]) ply = plyForMove(+match[1], match[2], match[3], sans);
    else {
      prefix = match[4];
      shown = match[0].slice(prefix.length);
      const candidate = (+match[5] - 1) * 2 + 1;
      ply = candidate <= sans.length ? candidate : null;
      if (ply !== null) shown = match[0];
      prefix = "";
    }
    html += esc(text.slice(last, match.index)) + prefix + (ply === null ? esc(shown) : moveRef(shown, ply, gameId));
    last = match.index + match[0].length;
  }
  return html + esc(text.slice(last));
}

function linkLine(line, detail, gameId) {
  const sans = (detail.moves || "").split(" ").filter(Boolean);
  if (detail.fen || !sans.length) return esc(line);
  let next = null;
  return line.split(/\s+/).map((token) => {
    const numbered = token.match(new RegExp(`^(\\d+)(\\.{1,3})(${SAN_TOKEN})$`));
    if (numbered) {
      const ply = plyForMove(+numbered[1], numbered[2], numbered[3], sans);
      next = ply === null ? null : ply + 1;
      return ply === null ? esc(token) : moveRef(token, ply, gameId);
    }
    if (next && sans[next - 1] && bareMove(sans[next - 1]) === bareMove(token)) {
      const ply = next;
      next += 1;
      return moveRef(token, ply, gameId);
    }
    next = null;
    return esc(token);
  }).join(" ");
}

function reviewHTML(detail, showMoments, gameId) {
  const r = detail.review;
  if (!r) return "";
  if (r.sections) {
    const parts = r.sections.map((sec) => {
      const line = sec.line ? `<p class="line">${linkLine(sec.line, detail, gameId)}</p>` : "";
      return `<p>${linkMoves(sec.text, detail, gameId)}</p>${line}`;
    }).join("");
    return `<div class="review"><p class="headline">${esc(r.headline)}</p>${parts}<h3>Turning point</h3><p>${linkMoves(r.turning_point, detail, gameId)}</p><div class="focus"><h3>Work on this</h3><p>${linkMoves(r.focus, detail, gameId)}</p></div></div>`;
  }
  const notes = showMoments && r.moments && r.moments.length
    ? `<h3>Moments to look at</h3><ul class="moments">${r.moments.map((m) => {
        const found = (detail.moments || []).find((x) => x.ply === m.ply);
        return `<li><button data-ply="${m.ply}"><b>${moveLabel(m.ply)} ${esc(found ? found.san : "")}</b><span class="why">${esc(m.note)}</span></button></li>`;
      }).join("")}</ul>` : "";
  return `<div class="review"><p>${esc(r.summary)}</p><h3>Turning point</h3><p>${esc(r.turning_point)}</p>${notes}<div class="focus"><h3>Work on this</h3><p>${esc(r.focus)}</p></div></div>`;
}

function headline(row) {
  const rating = row[C.oppRating] ? ` (${row[C.oppRating]})` : "";
  return `<h1><span class="verdict ${row[C.result]}">${resultWord[row[C.result]]}</span> against ${esc(row[C.opp])}${rating}</h1>`;
}
function metaLine(row) {
  const color = row[C.color] === "w" ? "White" : "Black";
  return `${dateText(row[C.at])}, ${SITE_NAMES[row[C.site]]} ${row[C.speed]}${row[C.bot] ? " against a bot" : ""}, playing ${color}, ${esc(row[C.family])}`;
}

function setNav(name) {
  document.querySelectorAll("[data-nav]").forEach((a) => {
    if (a.dataset.nav === name) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
}

function ratingsBySpeed(site) {
  const out = {};
  for (const s of SPEEDS) out[s] = [];
  for (const row of data.games) {
    if (row[C.site] === site && !row[C.bot] && row[C.rated] && row[C.rating] && out[row[C.speed]]) out[row[C.speed]].push(row);
  }
  return out;
}

function goalSection() {
  const rows = Object.keys(SITE_NAMES).flatMap((site) => {
    const series = ratingsBySpeed(site);
    return SPEEDS.filter((s) => series[s].length).map((s) => {
    const list = series[s];
    const last = list[list.length - 1];
    const now = last[C.rating] + (last[C.diff] || 0);
    const wins = list.filter((r) => r[C.result] === "win").length;
    const gap = data.goal - now;
    const state = gap <= 0
      ? `<span class="goal-met">✓ reached, ${-gap} above</span>`
      : `${gap} to go`;
    return `<tr><td>${SITE_NAMES[site]}</td><td>${cap(s)}</td><td class="num">${now}</td><td>${state}</td><td class="num">${list.length.toLocaleString()}</td><td class="num">${Math.round(wins * 100 / list.length)}%</td></tr>`;
    });
  });
  if (!rows.length) return "";
  return `<section><h2>Road to ${data.goal}</h2><div class="table-wrap"><table class="goal-table"><thead><tr><th>Site</th><th>Time control</th><th class="num">Rating</th><th>Goal</th><th class="num">Rated games</th><th class="num">Won</th></tr></thead><tbody>${rows.join("")}</tbody></table></div></section>`;
}

function ratingChart(host, days, site) {
  const series = ratingsBySpeed(site);
  const now = data.games.length ? data.games[data.games.length - 1][C.at] : Date.now();
  const from = days ? now - days * 864e5 : Math.min(...SPEEDS.flatMap((s) => series[s].slice(0, 1).map((r) => r[C.at])));
  const lines = SPEEDS.map((s) => ({ s, pts: series[s].filter((r) => r[C.at] >= from).map((r) => [r[C.at], r[C.rating]]) })).filter((l) => l.pts.length);
  if (!lines.length) { host.innerHTML = '<p class="note">No rated games in this range.</p>'; return; }
  const W = Math.max(300, host.clientWidth), H = W > 500 ? 320 : 280;
  const m = { l: 42, r: W > 500 ? 74 : 56, t: 12, b: 26 };
  const values = lines.flatMap((l) => l.pts.map((p) => p[1])).concat(data.goal);
  const lo = Math.floor(Math.min(...values) / 100) * 100, hi = Math.ceil(Math.max(...values) / 100) * 100;
  const x = (t) => m.l + (t - from) / Math.max(1, now - from) * (W - m.l - m.r);
  const y = (v) => m.t + (hi - v) / Math.max(1, hi - lo) * (H - m.t - m.b);
  const step = Math.max(100, Math.ceil((hi - lo) / 5 / 100) * 100);
  let grid = "";
  for (let v = lo; v <= hi; v += step) grid += `<line class="grid" x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}"/><text x="${m.l - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
  const span = now - from;
  let ticks = "";
  for (let i = 0; i <= 3; i++) {
    const t = from + span * i / 3;
    ticks += `<text x="${x(t)}" y="${H - 7}" text-anchor="${i === 0 ? "start" : i === 3 ? "end" : "middle"}">${new Date(t).toLocaleDateString(undefined, { month: "short", year: "2-digit" })}</text>`;
  }
  const paths = lines.map((l) => {
    const stride = Math.max(1, Math.floor(l.pts.length / 500));
    const pts = l.pts.filter((_, i) => i % stride === 0 || i === l.pts.length - 1);
    const d = pts.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)} ${y(p[1]).toFixed(1)}`).join("");
    return `<path d="${d}" fill="none" stroke="${css(SERIES[l.s])}" stroke-width="2" stroke-linejoin="round"/>`;
  }).join("");
  const ends = lines.map((l) => ({ s: l.s, y: y(l.pts[l.pts.length - 1][1]) })).sort((a, b) => a.y - b.y);
  ends.forEach((e, i) => { if (i && e.y - ends[i - 1].y < 14) e.y = ends[i - 1].y + 14; });
  const labels = ends.map((e) => `<text x="${W - m.r + 6}" y="${e.y + 4}">${cap(e.s)}</text>`).join("");
  host.innerHTML = `<div class="legend">${lines.map((l) => `<span><i style="background:${css(SERIES[l.s])}"></i>${cap(l.s)}</span>`).join("")}</div>
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Rating over time for ${lines.map((l) => l.s).join(", ")}, with the ${data.goal} goal marked">${grid}
    <line class="goal" x1="${m.l}" x2="${W - m.r}" y1="${y(data.goal)}" y2="${y(data.goal)}"/><text x="${m.l + 4}" y="${y(data.goal) - 5}">Goal ${data.goal}</text>
    ${paths}${labels}${ticks}<line class="hair" y1="${m.t}" y2="${H - m.b}" x1="-9" x2="-9"/>
    <rect x="${m.l}" y="${m.t}" width="${W - m.l - m.r}" height="${H - m.t - m.b}" fill="transparent"/></svg>`;
  const svg = host.querySelector("svg");
  const hair = svg.querySelector(".hair");
  const move = (event) => {
    const box = svg.getBoundingClientRect();
    const px = (event.clientX - box.left) / box.width * W;
    const t = from + (px - m.l) / (W - m.l - m.r) * span;
    if (px < m.l || px > W - m.r) { hide(); return; }
    hair.setAttribute("x1", px); hair.setAttribute("x2", px);
    const rows = lines.map((l) => {
      let found = null;
      for (const p of l.pts) { if (p[0] <= t) found = p; else break; }
      return found ? `${cap(l.s)} ${found[1]}` : null;
    }).filter(Boolean);
    showTip(`<b>${dateText(t)}</b><br>${rows.join("<br>") || "No games yet"}`, event);
  };
  const hide = () => { tip.hidden = true; hair.setAttribute("x1", -9); hair.setAttribute("x2", -9); };
  svg.addEventListener("pointermove", move);
  svg.addEventListener("pointerdown", move);
  svg.addEventListener("pointerleave", hide);
}

function showTip(html, event) {
  tip.innerHTML = html;
  tip.hidden = false;
  const box = tip.getBoundingClientRect();
  tip.style.left = Math.max(8, Math.min(innerWidth - box.width - 8, event.clientX + 12)) + "px";
  tip.style.top = Math.max(8, event.clientY - box.height - 12) + "px";
}

function chartSection() {
  return `<section><h2>Rating over time</h2><div class="controls" id="range">
    <button data-days="90">3 months</button><button data-days="365">1 year</button><button data-days="0" aria-pressed="true">All time</button></div>
    <div class="controls" id="chart-site"><button data-site="lichess" aria-pressed="true">Lichess</button><button data-site="chesscom">Chess.com</button></div><div class="chart" id="chart"></div></section>`;
}

function mistakesSection() {
  if (!data.analysed) return "";
  const recent = data.tags.recent, all = data.tags.all;
  const order = Object.keys(TAG_NAMES).sort((a, b) => recent[b] - recent[a]);
  const row = (name, a, b) => `<tr><td>${name}</td><td class="num">${a.toFixed(1)}</td><td class="num">${b.toFixed(1)}</td></tr>`;
  const phase = data.phases;
  return `<section><h2>Recurring mistakes</h2><p class="hint">How often each pattern shows up in mistakes and blunders, per 100 games. Your last ${data.recent_size.toLocaleString()} analysed games sit beside your full analysed history.</p>
  <div class="table-wrap"><table><thead><tr><th>Pattern</th><th class="num">Recent</th><th class="num">All</th></tr></thead><tbody>
  ${order.map((t) => row(TAG_NAMES[t], recent[t], all[t])).join("")}
  ${["opening", "middlegame", "endgame"].map((p) => row(`${cap(p)} errors`, phase.recent[p] * 100, phase.all[p] * 100)).join("")}
  </tbody></table></div></section>`;
}

function openingsSection() {
  if (!data.openings.length) return "";
  const rows = data.openings.slice(0, 12).map((o) => {
    const total = o.win + o.draw + o.loss;
    return `<tr><td>${esc(o.name)}</td><td>${cap(o.color)}</td><td class="num">${total}</td><td class="num">${Math.round((o.win + o.draw / 2) * 100 / total)}%</td></tr>`;
  });
  return `<section><h2>Most played openings</h2><div class="table-wrap"><table><thead><tr><th>Opening</th><th>Side</th><th class="num">Games</th><th class="num">Score</th></tr></thead><tbody>${rows.join("")}</tbody></table></div></section>`;
}

async function latestReview() {
  for (let i = data.games.length - 1; i >= 0; i--) {
    if (!data.games[i][C.reviewed]) continue;
    const row = data.games[i];
    const detail = await monthOf(row);
    const line = replay(detail);
    let ply = (detail.moments || []).reduce((best, m) => (!best || m.before - m.after > best.before - best.after ? m : best), null);
    ply = ply ? ply.ply : (line ? line.frames.length - 1 : 0);
    const board = line ? boardHTML(line.frames[ply], row[C.color] === "b", line.marks[ply], `Board after ${moveLabel(ply)}`, annotations(detail)[ply]) : "";
    return `<div class="game-head"><div>${board}<p class="note">Your biggest swing, after move ${Math.ceil(ply / 2)}.</p></div>
      <div>${headline(row)}<p class="meta">${metaLine(row)}</p>${reviewHTML(detail, false, row[C.id])}<p><a href="#/game/${row[C.id]}">Replay this game</a></p></div></div>`;
  }
  return `<h1 style="font-size:clamp(2rem,5vw,3.2rem);margin-top:12px">Your reviews will appear here</h1><p class="hint">${data.total.toLocaleString()} games collected and ${data.analysed.toLocaleString()} analysed so far. Reviews are written as analysis finishes.</p>`;
}

async function home() {
  setNav("home");
  const lead = await latestReview();
  app.innerHTML = lead + goalSection() + chartSection() + mistakesSection() + openingsSection();
  const host = document.getElementById("chart");
  let days = 0, site = "lichess";
  ratingChart(host, days, site);
  const choose = (id, apply) => document.getElementById(id).addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    event.currentTarget.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b === button));
    apply(button);
    ratingChart(host, days, site);
  });
  choose("range", (b) => { days = +b.dataset.days; });
  choose("chart-site", (b) => { site = b.dataset.site; });
}

const listState = { site: "", speed: "", result: "", q: "", sort: "newest", shown: 50 };
const SORTS = { newest: "Newest first", oldest: "Oldest first", best: "Highest accuracy", worst: "Lowest accuracy", opponentHigh: "Highest-rated opponent", opponentLow: "Lowest-rated opponent", sacrifices: "Most sacrifices", great: "Most great moves" };
function sortGames(list) {
  // Very short games can score 100%, so they rank after full games.
  const acc = (r, missing) => (r[C.acc] == null || r[C.plies] < 20 ? missing : r[C.acc]);
  const byDate = (a, b) => b[C.at] - a[C.at];
  const orders = {
    newest: byDate,
    oldest: (a, b) => a[C.at] - b[C.at],
    best: (a, b) => acc(b, -1) - acc(a, -1) || byDate(a, b),
    worst: (a, b) => acc(a, 101) - acc(b, 101) || byDate(a, b),
    opponentHigh: (a, b) => (b[C.oppRating] ?? -1) - (a[C.oppRating] ?? -1) || byDate(a, b),
    opponentLow: (a, b) => (a[C.oppRating] ?? 1e6) - (b[C.oppRating] ?? 1e6) || byDate(a, b),
    sacrifices: (a, b) => b[C.sacrifices] - a[C.sacrifices] || byDate(a, b),
    great: (a, b) => b[C.great] - a[C.great] || byDate(a, b),
  };
  return list.sort(orders[listState.sort]);
}
function gamesView() {
  setNav("games");
  app.innerHTML = `<h1 style="font-size:clamp(2rem,5vw,3.2rem);margin-top:12px">Games</h1>
  <p class="hint" id="count"></p>
  <div class="filters">
    <input id="q" type="search" placeholder="Search opponent or opening" aria-label="Search opponent or opening" value="${esc(listState.q)}">
    <select id="sort" aria-label="Sort games">${Object.entries(SORTS).map(([k, v]) => `<option value="${k}" ${listState.sort === k ? "selected" : ""}>${v}</option>`).join("")}</select>
    <select id="site" aria-label="Site"><option value="">All sites</option>${Object.entries(SITE_NAMES).map(([k, v]) => `<option value="${k}" ${listState.site === k ? "selected" : ""}>${v}</option>`).join("")}</select>
    <select id="speed" aria-label="Time control"><option value="">All time controls</option>${["ultraBullet", ...SPEEDS, "correspondence"].map((s) => `<option value="${s}" ${listState.speed === s ? "selected" : ""}>${cap(s)}</option>`).join("")}</select>
    <select id="result" aria-label="Result"><option value="">All results</option>${["win", "loss", "draw"].map((r) => `<option value="${r}" ${listState.result === r ? "selected" : ""}>${cap(r)}</option>`).join("")}</select>
  </div><ul class="rows" id="rows"></ul><p><button id="more" hidden>Show 50 more</button></p>`;
  const draw = () => {
    const q = listState.q.toLowerCase();
    const list = [];
    for (let i = data.games.length - 1; i >= 0; i--) {
      const r = data.games[i];
      if (listState.site && r[C.site] !== listState.site) continue;
      if (listState.speed && r[C.speed] !== listState.speed) continue;
      if (listState.result && r[C.result] !== listState.result) continue;
      if (q && !r[C.opp].toLowerCase().includes(q) && !r[C.family].toLowerCase().includes(q)) continue;
      list.push(r);
    }
    document.getElementById("count").textContent = `${list.length.toLocaleString()} of ${data.total.toLocaleString()} games. ${data.analysed.toLocaleString()} analysed, ${data.reviewed.toLocaleString()} reviewed.`;
    sortGames(list);
    document.getElementById("rows").innerHTML = list.slice(0, listState.shown).map((r) => {
      const errs = r[C.blunders] == null ? "" : `, ${r[C.blunders]} ${r[C.blunders] === 1 ? "blunder" : "blunders"}`;
      const acc = r[C.acc] == null ? "" : `${Math.round(r[C.acc])}%`;
      return `<li><a href="#/game/${r[C.id]}"><span class="res ${r[C.result]}">${resultWord[r[C.result]]}</span><span class="opp">${esc(r[C.opp])}${r[C.oppRating] ? ` (${r[C.oppRating]})` : ""}</span><span class="acc">${acc}</span><span class="dt">${new Date(r[C.at]).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "2-digit" })}</span><span class="sub">${SITE_NAMES[r[C.site]]}, ${cap(r[C.speed])}${r[C.bot] ? ", bot" : ""}, ${esc(r[C.family])}${errs}${r[C.sacrifices] ? `, ${plural(r[C.sacrifices], "sacrifice")}` : ""}${r[C.great] ? `, ${plural(r[C.great], "great move")}` : ""}${r[C.reviewed] ? ", reviewed" : ""}</span></a></li>`;
    }).join("") || '<li class="note">No games match. Clear a filter to see more.</li>';
    document.getElementById("more").hidden = list.length <= listState.shown;
  };
  const reset = (key) => (event) => { listState[key] = event.target.value; listState.shown = 50; draw(); };
  document.getElementById("q").addEventListener("input", reset("q"));
  document.getElementById("sort").addEventListener("change", reset("sort"));
  document.getElementById("site").addEventListener("change", reset("site"));
  document.getElementById("speed").addEventListener("change", reset("speed"));
  document.getElementById("result").addEventListener("change", reset("result"));
  document.getElementById("more").addEventListener("click", () => { listState.shown += 50; draw(); });
  draw();
}

const FIGURINES = { K: "♔", Q: "♕", R: "♖", B: "♗", N: "♘" };
function figurine(san) {
  return esc(san).replace(/^[KQRBN]/, (p) => `<span class="fig" aria-hidden="true">${FIGURINES[p]}\uFE0E</span><span class="sr">${p}</span>`)
    .replace(/=([QRBN])/, (_, p) => `=<span class="fig" aria-hidden="true">${FIGURINES[p]}\uFE0E</span><span class="sr">${p}</span>`);
}

function moveTable(detail, sans) {
  if (!sans.length) return "";
  const parts = (detail.fen || "").split(" ");
  const blackFirst = parts[1] === "b";
  const first = +parts[5] || 1;
  const marks = annotations(detail);
  const cell = (ply) => {
    if (ply < 1 || ply > sans.length) return "<td></td>";
    const note = marks[ply];
    const category = note ? MARK_CATEGORY[note] : "";
    const mark = note ? `<span class="mark" title="${MARK_NAME[category]}">${note}</span>` : "";
    return `<td><button data-ply="${ply}"${note ? ` class="tone-${category}"` : ""}>${figurine(sans[ply - 1])}${mark}</button></td>`;
  };
  const rows = [];
  const offset = blackFirst ? 1 : 0;
  for (let i = 0; i * 2 - offset < sans.length; i++) {
    const whitePly = i * 2 + 1 - offset;
    rows.push(`<tr><th scope="row">${first + i}</th>${cell(whitePly)}${cell(whitePly + 1)}</tr>`);
  }
  return `<div class="movetable" id="moves" tabindex="0" aria-label="Moves"><table><tbody>${rows.join("")}</tbody></table></div>`;
}

function evalGraph(detail, row, ply) {
  if (!detail.evals) return "";
  const n = detail.evals.length - 1, W = 600, H = 90;
  const sign = row[C.color] === "w" ? 1 : -1;
  const y = (cp) => H / 2 - Math.max(-600, Math.min(600, cp * sign)) / 600 * (H / 2 - 2);
  const x = (i) => i / Math.max(1, n) * W;
  const area = `M0 ${H / 2}` + detail.evals.map((e, i) => `L${x(i).toFixed(1)} ${y(e).toFixed(1)}`).join("") + `L${W} ${H / 2}Z`;
  return `<svg class="eval" id="eval" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Evaluation through the game from your side. Above the line favours you."><path class="area" d="${area}"/><line class="mid" x1="0" x2="${W}" y1="${H / 2}" y2="${H / 2}" vector-effect="non-scaling-stroke"/><line class="now" id="evalnow" x1="${x(ply)}" x2="${x(ply)}" y1="0" y2="${H}" vector-effect="non-scaling-stroke"/></svg>`;
}

async function gameView(id, startPly) {
  setNav("games");
  const row = data.games.find((r) => r[C.id] === id);
  if (!row) { app.innerHTML = '<h1>Game not found</h1><p><a href="#/games">Back to all games</a></p>'; return; }
  const detail = await monthOf(row);
  const line = replay(detail);
  const sans = (detail.moves || "").split(" ").filter(Boolean);
  const moments = detail.moments || [];
  let ply = line ? (startPly == null ? line.frames.length - 1 : Math.min(startPly, line.frames.length - 1)) : 0;
  const flip = row[C.color] === "b";
  const siteUrl = detail.url || `https://lichess.org/${row[C.id]}`;
  const counts = detail.counts;
  const stats = detail.skipped
    ? `<p class="note">Not analysed: ${esc(detail.skipped)}.</p>`
    : counts ? `<p class="meta">Accuracy ${row[C.acc] == null ? "n/a" : row[C.acc] + "%"}, ${plural(counts.blunder, "blunder")}, ${plural(counts.mistake, "mistake")}, ${plural(counts.inaccuracy, "inaccuracy", "inaccuracies")}.</p>`
    : '<p class="note">Analysis is still in the queue.</p>';
  const noReview = detail.review || detail.skipped ? "" : '<p class="note">This game hasn’t been reviewed yet.</p>';
  const reviewed = new Set(((detail.review && detail.review.moments) || []).map((m) => m.ply));
  const others = moments.filter((m) => !reviewed.has(m.ply) && m.cat !== "inaccuracy");
  app.innerHTML = `<div class="game-head"><div>
      <div id="board"></div>
      <div class="controls"><button id="first" aria-label="First position">⏮</button><button id="prev" aria-label="Previous move">◀</button><button id="next" aria-label="Next move">▶</button><button id="last" aria-label="Last position">⏭</button><span class="position" id="pos" aria-live="polite"></span></div>
      ${evalGraph(detail, row, ply)}
      ${moveTable(detail, sans)}
    </div><div>${headline(row)}<p class="meta">${metaLine(row)}</p>${stats}${noReview}${reviewHTML(detail, true)}
      ${detail.review ? `<p class="note">Review written by ${esc(detail.review.model)} from ${esc(detail.engine)} analysis.</p>` : ""}
      <p><a href="${esc(siteUrl)}" rel="noopener">Open on ${SITE_NAMES[row[C.site]]}</a></p></div></div>
    ${others.length ? `<section><h2>${reviewed.size ? "Other mistakes and blunders" : "Mistakes and blunders"}</h2><ul class="moments">${others.map((m) => `<li><button data-ply="${m.ply}"><b>${moveLabel(m.ply)} ${esc(m.san)} <span class="tag-${m.cat}">${m.cat}</span></b><span class="why">${pawns(m.before)} to ${pawns(m.after)}${m.best ? `, ${esc(m.best)} was better` : ""}${m.tags.length ? `, ${m.tags.map((t) => TAG_SHORT[t]).join(", ")}` : ""}</span></button></li>`).join("")}</ul></section>` : ""}
    ${(detail.great || []).length ? `<section><h2>Great moves</h2><ul class="moments">${detail.great.map((p) => `<li><button data-ply="${p}"><b>${moveLabel(p)} ${esc(sans[p - 1])}!</b><span class="why">The only move here that didn't lose.</span></button></li>`).join("")}</ul></section>` : ""}
    ${(detail.sacrifices || []).length ? `<section><h2>Sacrifices</h2><ul class="moments">${detail.sacrifices.map((p) => `<li><button data-ply="${p}"><b>${moveLabel(p)} ${esc(sans[p - 1])}!!</b><span class="why">The engine's top move, leaving a piece where it can be taken.</span></button></li>`).join("")}</ul></section>` : ""}`;
  const notes = annotations(detail);
  const boardHost = document.getElementById("board");
  const pos = document.getElementById("pos");
  const evalNow = document.getElementById("evalnow");
  const go = (next) => {
    if (!line) return;
    ply = Math.max(0, Math.min(line.frames.length - 1, next));
    boardHost.innerHTML = boardHTML(line.frames[ply], flip, line.marks[ply], ply ? `Board after ${moveLabel(ply)} ${sans[ply - 1]}` : "Starting position", notes[ply]);
    pos.textContent = ply ? `${moveLabel(ply)} ${sans[ply - 1]}` : "Start";
    document.querySelectorAll("#moves button").forEach((b) => {
      const current = +b.dataset.ply === ply;
      b.classList.toggle("on", current);
      if (current) b.setAttribute("aria-current", "true"); else b.removeAttribute("aria-current");
    });
    const list = document.getElementById("moves");
    const active = list && list.querySelector("button.on");
    if (active) {
      const box = list.getBoundingClientRect(), item = active.getBoundingClientRect();
      if (item.top < box.top + 30 || item.bottom > box.bottom) list.scrollTop += item.top - box.top - box.height / 2;
    } else if (list) list.scrollTop = 0;
    if (evalNow) { const x = ply / Math.max(1, detail.evals.length - 1) * 600; evalNow.setAttribute("x1", x); evalNow.setAttribute("x2", x); }
  };
  if (!line) boardHost.innerHTML = '<p class="note">This position can’t be replayed here. Open the original game instead.</p>';
  document.getElementById("first").onclick = () => go(0);
  document.getElementById("prev").onclick = () => go(ply - 1);
  document.getElementById("next").onclick = () => go(ply + 1);
  document.getElementById("last").onclick = () => go(Infinity);
  app.addEventListener("click", plyClick);
  const graph = document.getElementById("eval");
  if (graph) graph.addEventListener("pointerdown", (event) => {
    const box = graph.getBoundingClientRect();
    go(Math.round((event.clientX - box.left) / box.width * (detail.evals.length - 1)));
  });
  keyHandler = (event) => {
    if (event.key === "ArrowLeft") go(ply - 1);
    if (event.key === "ArrowRight") go(ply + 1);
  };
  document.addEventListener("keydown", keyHandler);
  function plyClick(event) {
    const button = event.target.closest("[data-ply]");
    if (!button) return;
    go(+button.dataset.ply);
    boardHost.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  cleanup = () => app.removeEventListener("click", plyClick);
  go(ply);
}

let cleanup = null;
async function route() {
  if (keyHandler) { document.removeEventListener("keydown", keyHandler); keyHandler = null; }
  if (cleanup) { cleanup(); cleanup = null; }
  tip.hidden = true;
  const hash = location.hash.replace(/^#\/?/, "");
  try {
    if (hash.startsWith("game/")) {
      const [id, startPly] = hash.slice(5).split("/");
      await gameView(id, startPly === undefined || !/^\d+$/.test(startPly) ? null : +startPly);
    }
    else if (hash === "games") gamesView();
    else await home();
  } catch (error) {
    app.innerHTML = `<h1>This page didn’t load</h1><p>${esc(error.message)}. Reload to try again.</p>`;
  }
  window.scrollTo(0, 0);
}

async function start() {
  try {
    const response = await fetch("data/summary.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    data = await response.json();
  } catch (error) {
    app.innerHTML = `<h1>Game data isn’t available yet</h1><p class="hint">The first update hasn’t published it. Check again after the next run. (${esc(error.message)})</p>`;
    return;
  }
  document.getElementById("foot").textContent = `${data.total.toLocaleString()} games from Lichess and Chess.com. ${data.analysed.toLocaleString()} analysed with Stockfish, ${data.reviewed.toLocaleString()} reviewed.`;
  addEventListener("hashchange", route);
  route();
}
start();
