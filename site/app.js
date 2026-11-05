"use strict";
const C = { id: 0, at: 1, speed: 2, rated: 3, color: 4, rating: 5, diff: 6, opp: 7, oppRating: 8, result: 9, family: 10, acc: 11, blunders: 12, mistakes: 13, reviewed: 14, site: 15, bot: 16, sacrifices: 17, plies: 18, great: 19, comeback: 20 };
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

const NOTE = { blunder: "??", mistake: "?", inaccuracy: "?!", great: "!", brilliant: "!!", miss: "✕" };
const CATEGORY_NAME = { brilliant: "Brilliant", great: "Great", best: "Best", excellent: "Excellent", good: "Good", book: "Book", inaccuracy: "Inaccuracy", mistake: "Mistake", miss: "Miss", blunder: "Blunder" };
const winPercent = (cp) => 50 + 50 * (2 / (1 + Math.exp(-0.00368208 * cp)) - 1);

function annotations(detail, row) {
  const notes = {};
  const evals = detail.evals;
  if (!evals) return notes;
  const myParity = row[C.color] === "w" ? 1 : 0;
  const moments = {};
  for (const m of detail.moments || []) moments[m.ply] = m;
  const theirErrors = {};
  for (const m of detail.opponent_moments || []) theirErrors[m.ply] = m;
  for (let ply = 1; ply < evals.length; ply++) {
    const white = ply % 2 === 1;
    const sign = white ? 1 : -1;
    const drop = winPercent(evals[ply - 1] * sign) - winPercent(evals[ply] * sign);
    const mine = ply % 2 === myParity;
    let category;
    if (mine && moments[ply]) {
      category = moments[ply].cat;
      const chance = theirErrors[ply - 1];
      const stillOk = evals[ply] * sign >= -150;
      if (stillOk && ((chance && !chance.punished && category !== "inaccuracy") || moments[ply].tags.includes("missed_mate"))) category = "miss";
    } else if (!mine && theirErrors[ply]) category = theirErrors[ply].cat;
    else if (drop >= 5) category = "inaccuracy";
    else if (drop <= 1) category = "best";
    else if (drop <= 2.5) category = "excellent";
    else category = "good";
    if (ply <= (detail.book_plies || 0) && !["blunder", "mistake", "miss"].includes(category)) category = "book";
    notes[ply] = category;
  }
  for (const p of detail.great || []) notes[p] = "great";
  for (const p of detail.sacrifices || []) notes[p] = "brilliant";
  return notes;
}

function summaryHTML(detail, row) {
  const notes = annotations(detail, row);
  const plies = Object.keys(notes).map(Number);
  if (!plies.length) return "";
  const myParity = row[C.color] === "w" ? 1 : 0;
  const rows = Object.keys(CATEGORY_NAME).map((category) => {
    const matching = plies.filter((p) => notes[p] === category);
    if (!matching.length) return "";
    const mine = matching.filter((p) => p % 2 === myParity).length;
    const mark = NOTE[category] ? ` ${NOTE[category]}` : "";
    return `<tr><td class="tone-${category}">${CATEGORY_NAME[category]}${mark}</td><td class="num">${mine}</td><td class="num">${matching.length - mine}</td></tr>`;
  }).join("");
  return `<section class="tight"><h2>Move summary</h2><div class="table-wrap"><table class="summary"><thead><tr><th>Type</th><th class="num">You</th><th class="num">${esc(row[C.opp])}</th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
}

function styleHTML(detail) {
  const style = detail.style;
  if (!style) return "";
  const [first, ...rest] = style.top;
  const also = rest.map(([name, share]) => `${esc(name)} (${Math.round(share * 100)}%)`).join(", ");
  const why = style.why && style.why.length ? `<p>Shared traits: ${esc(style.why.join(", "))}.</p>` : "";
  return `<section class="tight"><h2>World champion most like this game</h2><p class="headline">${esc(first[0])} (${Math.round(first[1] * 100)}%)</p>${why}${also ? `<p class="meta">Next closest: ${also}</p>` : ""}<p class="note">A rough, for-fun comparison of move patterns, such as captures, king pressure and pawn play. It says nothing about strength, one game is a small sample, and fast online games tend to lean toward the sharper, older champions. Compares 16 of the 18 undisputed champions: Ding Liren and Gukesh Dommaraju aren't in the data yet.</p></section>`;
}

function styleSection() {
  const overall = data.style_overall;
  if (!overall) return "";
  const [first, ...rest] = overall.top;
  const counts = data.style_counts || [];
  const total = counts.reduce((sum, item) => sum + item[1], 0);
  const why = overall.why.length ? `<p>Shared traits: ${esc(overall.why.join(", "))}.</p>` : "";
  const table = counts.length ? `<h3 class="sub-head">Closest match game by game</h3><div class="table-wrap"><table><thead><tr><th>Champion</th><th class="num">Games</th><th class="num">Share</th></tr></thead><tbody>${counts.slice(0, 6).map(([name, n]) => `<tr><td>${esc(name)}</td><td class="num">${n.toLocaleString()}</td><td class="num">${Math.round(n * 100 / total)}%</td></tr>`).join("")}</tbody></table></div>` : "";
  return `<section><h2>World champion you play most like</h2><p class="headline">${esc(first[0])}</p>${why}<p class="meta">Next closest: ${rest.map(([name]) => esc(name)).join(", ")}</p><p class="hint">Based on the average of your ${overall.games.toLocaleString()} human games. It's a rough comparison of move patterns, not strength.</p>${table}</section>`;
}

function nextCheck() {
  const next = new Date();
  next.setUTCMinutes(17, 0, 0);
  next.setUTCHours(next.getUTCHours() + (next.getUTCHours() % 2 ? 1 : 0));
  if (next <= new Date()) next.setUTCHours(next.getUTCHours() + 2);
  return next;
}

function timeWords(ms) {
  const minutes = Math.max(1, Math.round(ms / 60000));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return minutes % 60 ? `${hours} hr ${minutes % 60} min` : `${hours} hr`;
  return `${Math.round(hours / 24)} days`;
}

function refreshLine() {
  const updated = data.updated_at ? `Last published ${timeWords(Date.now() - data.updated_at)} ago. ` : "";
  return `${updated}Next check for new games in about ${timeWords(nextCheck() - Date.now())}, though GitHub can run it late.`;
}

function showRefresh() {
  const line = document.getElementById("refresh");
  if (line && data) line.textContent = refreshLine();
}
setInterval(showRefresh, 30000);

function evalBar(cp, flip) {
  const whiteShare = winPercent(cp);
  const value = Math.abs(cp) >= 1000 ? "M" : (Math.abs(cp) / 100).toFixed(1);
  const whiteAhead = cp >= 0;
  const onBottom = whiteAhead !== flip;
  const fill = flip ? `top:0;height:${whiteShare}%` : `bottom:0;height:${whiteShare}%`;
  return `<div class="evalbar" role="img" aria-label="Evaluation ${cp >= 0 ? "White" : "Black"} ${value}"><div class="white-fill" style="${fill}"></div><span class="val ${onBottom ? "low" : "high"} ${whiteAhead ? "on-white" : "on-black"}">${value}</span></div>`;
}

function boardRow(boardMarkup, cp, flip) {
  return `<div class="board-row"><div class="bar-slot">${cp == null ? "" : evalBar(cp, flip)}</div><div class="board-slot">${boardMarkup}</div></div>`;
}

const engine = {
  worker: null, enabled: false, searching: false, pending: null, fen: null, lines: {}, listener: null,
  files: ["vendor/stockfish/stockfish-19-lite-single.js", "vendor/stockfish/stockfish-19-asm.js"],
  attempt: 0, ready: false, timer: null, failed: false,
  start() {
    if (this.worker || this.failed) return;
    this.ready = false;
    this.worker = new Worker(this.files[this.attempt]);
    this.worker.onmessage = (event) => this.onLine(String(event.data));
    this.worker.onerror = (event) => this.fail(event.message);
    this.worker.onmessageerror = () => this.fail("message error");
    this.worker.postMessage("uci");
    clearTimeout(this.timer);
    this.timer = setTimeout(() => { if (!this.ready) this.fail("no response"); }, this.attempt ? 30000 : 8000);
  },
  fail(reason) {
    clearTimeout(this.timer);
    if (this.worker) this.worker.terminate();
    this.worker = null;
    this.searching = false;
    const fen = this.pending || this.fen;
    this.pending = null;
    this.fen = null;
    this.lines = {};
    this.attempt += 1;
    if (this.attempt < this.files.length) {
      if (fen) this.analyse(fen);
      return;
    }
    this.failed = true;
    if (this.listener) this.listener(null, `The engine couldn't start in this browser (${reason || "unknown error"}).`);
  },
  analyse(fen) {
    this.start();
    if (!this.worker) return;
    if (this.fen === fen && (this.searching || Object.keys(this.lines).length)) return;
    this.lines = {};
    this.fen = fen;
    if (this.searching) { this.pending = fen; this.worker.postMessage("stop"); return; }
    this.run(fen);
  },
  run(fen) {
    this.searching = true;
    this.pending = null;
    this.worker.postMessage(`position fen ${fen}`);
    this.worker.postMessage(`go depth 20 movetime ${this.attempt ? 8000 : 4000}`);
  },
  stop() {
    this.fen = null;
    this.lines = {};
    this.pending = null;
    if (this.worker && this.searching) this.worker.postMessage("stop");
  },
  onLine(line) {
    if (line.startsWith("uciok") && !this.ready) {
      this.ready = true;
      clearTimeout(this.timer);
      this.worker.postMessage("setoption name MultiPV value 2");
      return;
    }
    if (line.startsWith("bestmove")) {
      this.searching = false;
      if (this.pending) this.run(this.pending);
      else if (this.listener) this.listener(this.lines);
      return;
    }
    if (this.pending || !line.startsWith("info") || !line.includes(" pv ")) return;
    const part = line.match(/ multipv (\d+)/);
    const depth = line.match(/ depth (\d+)/);
    const score = line.match(/ score (cp|mate) (-?\d+)/);
    const pv = line.split(" pv ")[1];
    if (!score || !pv || !this.fen) return;
    const whiteToMove = this.fen.split(" ")[1] === "w";
    const value = +score[2] * (whiteToMove ? 1 : -1);
    this.lines[part ? part[1] : "1"] = { depth: depth ? +depth[1] : 0, kind: score[1], value, pv: pv.trim().split(" ") };
    if (this.listener) this.listener(this.lines);
  },
};

const opponent = {
  worker: null, attempt: 0, timer: null, onMove: null, onFail: null, elo: 1700, last: null,
  ask(fen, elo, onMove, onFail) {
    this.onMove = onMove;
    this.onFail = onFail;
    this.last = fen;
    this.elo = elo;
    this.attempt = Math.max(this.attempt, engine.attempt);
    if (!this.worker) this.boot();
    this.send();
  },
  boot() {
    this.worker = new Worker(engine.files[this.attempt]);
    this.worker.onmessage = (event) => {
      const line = String(event.data);
      if (!line.startsWith("bestmove")) return;
      clearTimeout(this.timer);
      const uci = line.split(" ")[1];
      if (this.onMove) this.onMove(uci);
    };
    this.worker.onerror = () => this.fail();
    this.worker.postMessage("uci");
  },
  send() {
    const limited = this.elo < 3000;
    this.worker.postMessage(`setoption name UCI_LimitStrength value ${limited}`);
    if (limited) this.worker.postMessage(`setoption name UCI_Elo value ${this.elo}`);
    this.worker.postMessage(`position fen ${this.last}`);
    this.worker.postMessage("go movetime 700");
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.fail(), this.attempt ? 30000 : 12000);
  },
  fail() {
    clearTimeout(this.timer);
    if (this.worker) this.worker.terminate();
    this.worker = null;
    this.attempt += 1;
    if (this.attempt < engine.files.length) { this.boot(); this.send(); return; }
    this.attempt = engine.files.length - 1;
    if (this.onFail) this.onFail();
  },
  stop() {
    clearTimeout(this.timer);
    this.onMove = null;
    this.onFail = null;
    if (this.worker) this.worker.postMessage("stop");
  },
};

function engineScore(line) {
  if (line.kind === "mate") return `${line.value > 0 ? "" : "-"}M${Math.abs(line.value)}`;
  return `${line.value > 0 ? "+" : ""}${(line.value / 100).toFixed(1)}`;
}

function lineToSan(fen, pv, limit = 8) {
  const game = new Chess(fen);
  const parts = fen.split(" ");
  let number = +parts[5], white = parts[1] === "w";
  const out = [];
  for (const uci of pv.slice(0, limit)) {
    const move = game.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] });
    if (!move) break;
    out.push(white ? `${number}. ${move.san}` : (out.length ? move.san : `${number}... ${move.san}`));
    if (!white) number += 1;
    white = !white;
  }
  return out.join(" ");
}

function arrowsSVG(lines, flip) {
  const center = (sq) => {
    const file = sq.charCodeAt(0) - 97, rank = +sq[1] - 1;
    return flip ? [(7 - file) * 100 + 50, rank * 100 + 50] : [file * 100 + 50, (7 - rank) * 100 + 50];
  };
  const parts = ["2", "1"].filter((k) => lines[k] && lines[k].pv[0]).map((k) => {
    const uci = lines[k].pv[0];
    const [x1, y1] = center(uci.slice(0, 2)), [x2, y2] = center(uci.slice(2, 4));
    const angle = Math.atan2(y2 - y1, x2 - x1), head = 34;
    const ex = x2 - Math.cos(angle) * head, ey = y2 - Math.sin(angle) * head;
    const a = angle + Math.PI / 2, w = 26;
    return `<g class="arrow arrow-${k}"><line x1="${x1}" y1="${y1}" x2="${ex}" y2="${ey}"/><polygon points="${x2},${y2} ${ex + Math.cos(a) * w},${ey + Math.sin(a) * w} ${ex - Math.cos(a) * w},${ey - Math.sin(a) * w}"/></g>`;
  }).join("");
  return `<svg class="arrows" viewBox="0 0 800 800" aria-hidden="true">${parts}</svg>`;
}

function betterMove(detail, notes, frames, ply) {
  if (!["blunder", "mistake", "miss"].includes(notes[ply])) return null;
  const moment = (detail.moments || []).find((m) => m.ply === ply);
  if (!moment || !moment.best) return null;
  const move = new Chess(frames[ply - 1]).move(moment.best, { sloppy: true });
  return move ? { san: move.san, uci: move.from + move.to } : null;
}

function betterArrow(better, flip) {
  if (!better) return "";
  return arrowsSVG({ 1: { pv: [better.uci] } }, flip).replace("arrow arrow-1", "arrow arrow-better");
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
    let inner = piece ? `<img class="pc" src="vendor/pieces/${piece === piece.toUpperCase() ? "w" : "b"}${piece.toUpperCase()}.svg" alt="" draggable="false">` : "";
    if (note && NOTE[note] && mark && mark[1] === name) {
      inner += `<span class="badge cat-${note}" title="${CATEGORY_NAME[note]}" aria-label="${CATEGORY_NAME[note]}">${NOTE[note]}</span>`;
    }
    return `<div class="sq ${shade}${hi}" data-sq="${name}">${inner}</div>`;
  }
  if (flip) cells.reverse();
  return `<div class="board" role="group" aria-label="${esc(label)}">${cells.join("")}</div>`;
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

function shownMove(prefix, san, ply, notes, sans) {
  const played = ply >= 1 && sans[ply - 1] && bareMove(sans[ply - 1]) === bareMove(san);
  const category = played ? notes[ply] : null;
  return `${prefix}${san.replace(/[!?]+$/, "")}${category && NOTE[category] ? NOTE[category] : ""}`;
}

function linkMoves(text, detail, gameId, notes) {
  const sans = (detail.moves || "").split(" ").filter(Boolean);
  if (detail.fen || !sans.length) return esc(text);
  const pattern = new RegExp(`(?<![\\w.])(\\d+)(\\.{1,3})\\s?(${SAN_TOKEN})|\\b([Mm]ove )(\\d+)\\b`, "g");
  let html = "", last = 0;
  for (const match of text.matchAll(pattern)) {
    let ply = null, shown = match[0], prefix = "";
    if (match[3]) {
      ply = plyForMove(+match[1], match[2], match[3], sans);
      const actual = (+match[1] - 1) * 2 + (match[2] === "." ? 1 : 2);
      shown = shownMove(`${match[1]}${match[2]}`, match[3], actual, notes, sans);
    }
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

function linkLine(line, detail, gameId, notes) {
  const sans = (detail.moves || "").split(" ").filter(Boolean);
  if (detail.fen || !sans.length) return esc(line);
  let next = null;
  return line.split(/\s+/).map((token) => {
    const numbered = token.match(new RegExp(`^(\\d+)(\\.{1,3})(${SAN_TOKEN})$`));
    if (numbered) {
      const ply = plyForMove(+numbered[1], numbered[2], numbered[3], sans);
      next = ply === null ? null : ply + 1;
      const actual = (+numbered[1] - 1) * 2 + (numbered[2] === "." ? 1 : 2);
      const label = shownMove(`${numbered[1]}${numbered[2]}`, numbered[3], actual, notes, sans);
      return ply === null ? esc(label) : moveRef(label, ply, gameId);
    }
    if (next && sans[next - 1] && bareMove(sans[next - 1]) === bareMove(token)) {
      const ply = next;
      next += 1;
      return moveRef(shownMove("", token, ply, notes, sans), ply, gameId);
    }
    next = null;
    return esc(token);
  }).join(" ");
}

function reviewHTML(detail, showMoments, gameId, row) {
  const r = detail.review;
  if (!r) return "";
  const notes = annotations(detail, row);
  if (r.sections) {
    const parts = r.sections.map((sec) => {
      const line = sec.line ? `<p class="line">${linkLine(sec.line, detail, gameId, notes)}</p>` : "";
      return `<p>${linkMoves(sec.text, detail, gameId, notes)}</p>${line}`;
    }).join("");
    return `<div class="review"><p class="headline">${esc(r.headline)}</p>${parts}<h3>Turning point</h3><p>${linkMoves(r.turning_point, detail, gameId, notes)}</p><div class="focus"><h3>Work on this</h3><p>${linkMoves(r.focus, detail, gameId, notes)}</p></div></div>`;
  }
  const moments = showMoments && r.moments && r.moments.length
    ? `<h3>Moments to look at</h3><ul class="moments">${r.moments.map((m) => {
        const found = (detail.moments || []).find((x) => x.ply === m.ply);
        return `<li><button data-ply="${m.ply}"><b>${moveLabel(m.ply)} ${esc(found ? found.san : "")}</b><span class="why">${esc(m.note)}</span></button></li>`;
      }).join("")}</ul>` : "";
  return `<div class="review"><p>${esc(r.summary)}</p><h3>Turning point</h3><p>${esc(r.turning_point)}</p>${moments}<div class="focus"><h3>Work on this</h3><p>${esc(r.focus)}</p></div></div>`;
}

function playerBar(row, mine) {
  const score = row[C.result] === "draw" ? "½" : (row[C.result] === "win") === mine ? "1" : "0";
  const name = mine ? (row[C.site] === "chesscom" ? data.chesscom_username : data.username) : row[C.opp];
  const rating = mine ? row[C.rating] : row[C.oppRating];
  const diff = mine && row[C.diff] ? `<span class="${row[C.diff] > 0 ? "gain" : "lost"}">${row[C.diff] > 0 ? "+" : ""}${row[C.diff]}</span>` : "";
  return `<div class="player"><span class="score${score === "1" ? " won" : ""}">${score}</span><span class="name">${esc(name)}</span><span class="rating">${rating ?? ""}</span>${diff}</div>`;
}

const ICONS = {
  first: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h3v16H5zM20 4v16L9 12z"/></svg>',
  prev: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 4v16L6 12z"/></svg>',
  next: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 4v16l12-8z"/></svg>',
  last: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M16 4h3v16h-3zM4 4v16l11-8z"/></svg>',
};

function headline(row) {
  const rating = row[C.oppRating] ? ` (${row[C.oppRating]})` : "";
  return `<h1><span class="verdict ${row[C.result]}">${resultWord[row[C.result]]}</span> against <a class="plain" href="#/opponent/${encodeURIComponent(row[C.opp])}">${esc(row[C.opp])}</a>${rating}</h1>`;
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
      const low = data.goal - 500;
      const width = Math.max(3, Math.min(100, (now - low) * 100 / (data.goal - low)));
      const state = gap <= 0 ? `<span class="goal-met">✓ ${-gap} above goal</span>` : `${gap} to go`;
      return `<li><div class="goal-top"><span>${speedIcon(s)}${SITE_NAMES[site]} ${s}</span><b>${now}</b></div><div class="goal-bar${gap <= 0 ? " met" : ""}" role="img" aria-label="${now} of ${data.goal}"><i style="width:${width}%"></i></div><div class="goal-note"><span>${state}</span><span>${list.length.toLocaleString()} rated, ${Math.round(wins * 100 / list.length)}% won</span></div></li>`;
    });
  });
  if (!rows.length) return "";
  return `<section><h2>Road to ${data.goal}</h2><ul class="goal-list">${rows.join("")}</ul></section>`;
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
    const board = line ? boardHTML(line.frames[ply], row[C.color] === "b", line.marks[ply], `Board after ${moveLabel(ply)}`, annotations(detail, row)[ply]) : "";
    return `<div class="game-head"><div>${playerBar(row, false)}${boardRow(board + (line ? betterArrow(betterMove(detail, annotations(detail, row), line.frames, ply), row[C.color] === "b") : ""), detail.evals ? detail.evals[ply] : null, row[C.color] === "b")}${playerBar(row, true)}<p class="note">Your biggest swing, after move ${Math.ceil(ply / 2)}.</p></div>
      <div>${headline(row)}<p class="meta">${metaLine(row)}</p>${reviewHTML(detail, false, row[C.id], row)}<p><a href="#/game/${row[C.id]}">Replay this game</a></p></div></div>`;
  }
  return `<h1 style="font-size:clamp(1.5rem,3vw,2rem);margin-top:12px">Your reviews will appear here</h1><p class="hint">${data.total.toLocaleString()} games collected and ${data.analysed.toLocaleString()} analysed so far. Reviews are written as analysis finishes.</p>`;
}

const PATTERN_TEXT = { hung_piece: "leaving pieces hanging", missed_material: "missing chances to win a piece", allowed_mate: "allowing forced mates", missed_mate: "missing forced mates", low_clock: "slipping when low on time" };
function weeklySection() {
  const now = Date.now();
  const week = data.games.filter((r) => r[C.at] >= now - 7 * 864e5 && !r[C.bot]);
  const before = data.games.filter((r) => r[C.at] >= now - 14 * 864e5 && r[C.at] < now - 7 * 864e5 && !r[C.bot]);
  if (!week.length) {
    return `<section class="tight"><h2>This week</h2><p>No games in the last 7 days yet. <a href="#/practice">Practice your past mistakes</a> in the meantime.</p></section>`;
  }
  const count = (result) => week.filter((r) => r[C.result] === result).length;
  const average = (rows) => {
    const scored = rows.filter((r) => r[C.acc] != null && r[C.plies] >= 20);
    return scored.length ? scored.reduce((sum, r) => sum + r[C.acc], 0) / scored.length : null;
  };
  const accuracy = average(week), earlier = average(before);
  const change = accuracy != null && earlier != null ? `, ${accuracy >= earlier ? "up" : "down"} ${Math.abs(accuracy - earlier).toFixed(1)} from the week before` : "";
  const ratings = {};
  for (const r of week) if (r[C.rated] && r[C.diff] != null) {
    const key = `${SITE_NAMES[r[C.site]]} ${r[C.speed]}`;
    ratings[key] = (ratings[key] || 0) + r[C.diff];
  }
  const ratingText = Object.entries(ratings).filter(([, v]) => v).map(([k, v]) => `${k} ${v > 0 ? "+" : ""}${v}`).join(", ");
  const tags = {};
  for (const r of week) for (const t of (data.recent_tags || {})[r[C.id]] || []) tags[t] = (tags[t] || 0) + 1;
  const common = Object.entries(tags).sort((a, b) => b[1] - a[1])[0];
  const wins = week.filter((r) => r[C.result] === "win" && r[C.acc] != null && r[C.plies] >= 20);
  const best = wins.sort((a, b) => b[C.acc] - a[C.acc])[0];
  const tile = (value, label, tone) => `<div class="stat"><b${tone ? ` class="${tone}"` : ""}>${value}</b><span>${label}</span></div>`;
  const delta = accuracy != null && earlier != null ? `${accuracy >= earlier ? "▲" : "▼"} ${Math.abs(accuracy - earlier).toFixed(1)} vs last week` : "Accuracy";
  const net = Object.values(ratings).reduce((sum, v) => sum + v, 0);
  const tiles = tile(week.length, plural(week.length, "game").split(" ")[1])
    + tile(`${count("win")}-${count("draw")}-${count("loss")}`, "Won, drawn, lost")
    + (accuracy != null ? tile(`${accuracy.toFixed(0)}%`, delta) : "")
    + (ratingText ? tile(`${net > 0 ? "+" : ""}${net}`, "Rating", net >= 0 ? "res win" : "res loss") : "");
  const notes = [
    ratingText ? `<li>${esc(ratingText)}</li>` : "",
    common ? `<li>Most common pattern: ${PATTERN_TEXT[common[0]]} (${common[1]} ${common[1] === 1 ? "time" : "times"}). <a href="#/practice/${common[0]}">Practice this</a></li>` : "",
    best ? `<li>Best win: <a href="#/game/${best[C.id]}">${esc(best[C.opp])}</a>, ${Math.round(best[C.acc])}% accuracy</li>` : "",
  ].join("");
  return `<section class="tight"><h2>This week</h2><div class="stats">${tiles}</div><ul class="week-list">${notes}</ul><p><a class="button-link" href="#/practice/week">Practice this week's blunders</a></p></section>`;
}

const OVERVIEW_TABS = { summary: "Summary", progress: "Progress", openings: "Openings", style: "Style" };
let overviewTab = "summary";
try { overviewTab = OVERVIEW_TABS[localStorage.getItem("pinkroses-tab")] ? localStorage.getItem("pinkroses-tab") : "summary"; } catch { /* use the default tab */ }

async function home() {
  setNav("home");
  const lead = await latestReview();
  const panels = {
    summary: () => weeklySection() + `<section>${lead}</section>` + goalSection(),
    progress: () => progressSection() + chartSection() + clockSection() + mistakesSection(),
    openings: () => openingsSection() + '<p><a class="button-link" href="#/openings">Open the opening explorer</a></p>',
    style: () => styleSection() + opponentsSection(),
  };
  app.innerHTML = `<div class="tabs" role="tablist" aria-label="Overview sections">${Object.entries(OVERVIEW_TABS).map(([k, v]) => `<button role="tab" data-tab="${k}">${v}</button>`).join("")}</div><div id="tab-panel" role="tabpanel"></div>`;
  const panel = document.getElementById("tab-panel");
  const show = (tab) => {
    overviewTab = tab;
    try { localStorage.setItem("pinkroses-tab", tab); } catch { /* the tab just won't be remembered */ }
    app.querySelectorAll("[data-tab]").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === tab));
    panel.innerHTML = panels[tab]();
    const host = document.getElementById("chart");
    if (!host) return;
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
  };
  app.querySelector(".tabs").addEventListener("click", (event) => {
    const button = event.target.closest("[data-tab]");
    if (button) show(button.dataset.tab);
  });
  show(overviewTab);
}

const listState = { site: "", speed: "", result: "", q: "", sort: "newest", from: "", to: "", min: "", max: "", comeback: false, upset: false, reviewed: false, brilliant: false, shown: 50 };
const SORTS = { newest: "Newest first", oldest: "Oldest first", best: "Highest accuracy", worst: "Lowest accuracy", opponentHigh: "Highest-rated opponent", opponentLow: "Lowest-rated opponent", sacrifices: "Most brilliant moves", great: "Most great moves" };
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
  app.innerHTML = `<h1 style="font-size:clamp(1.5rem,3vw,2rem);margin-top:12px">Games</h1>
  <p class="hint" id="count"></p><p class="hint" id="refresh"></p>
  <div class="filters">
    <input id="q" type="search" placeholder="Search opponent or opening" aria-label="Search opponent or opening" value="${esc(listState.q)}">
    <select id="sort" aria-label="Sort games">${Object.entries(SORTS).map(([k, v]) => `<option value="${k}" ${listState.sort === k ? "selected" : ""}>${v}</option>`).join("")}</select>
    <select id="site" aria-label="Site"><option value="">All sites</option>${Object.entries(SITE_NAMES).map(([k, v]) => `<option value="${k}" ${listState.site === k ? "selected" : ""}>${v}</option>`).join("")}</select>
    <select id="speed" aria-label="Time control"><option value="">All time controls</option>${["ultraBullet", ...SPEEDS, "correspondence"].map((s) => `<option value="${s}" ${listState.speed === s ? "selected" : ""}>${cap(s)}</option>`).join("")}</select>
    <select id="result" aria-label="Result"><option value="">All results</option>${["win", "loss", "draw"].map((r) => `<option value="${r}" ${listState.result === r ? "selected" : ""}>${cap(r)}</option>`).join("")}</select>
  </div><details class="more-filters"><summary>More filters</summary><div class="filters">
    <label>From <input id="f-from" type="date" value="${esc(listState.from)}"></label><label>To <input id="f-to" type="date" value="${esc(listState.to)}"></label>
    <label>Opponent rating <input id="f-min" type="number" inputmode="numeric" placeholder="Min" aria-label="Minimum opponent rating" value="${esc(listState.min)}"></label><label>to <input id="f-max" type="number" inputmode="numeric" placeholder="Max" aria-label="Maximum opponent rating" value="${esc(listState.max)}"></label></div>
    <div class="filters checks"><label><input id="f-comeback" type="checkbox" ${listState.comeback ? "checked" : ""}> Wins from lost positions</label><label><input id="f-upset" type="checkbox" ${listState.upset ? "checked" : ""}> Upset wins (100+ higher rated)</label><label><input id="f-brilliant" type="checkbox" ${listState.brilliant ? "checked" : ""}> Has a brilliant move</label><label><input id="f-reviewed" type="checkbox" ${listState.reviewed ? "checked" : ""}> Reviewed</label></div></details>
    <ul class="rows" id="rows"></ul><p><button id="more" hidden>Show 50 more</button></p>`;
  const draw = () => {
    const q = listState.q.toLowerCase();
    const list = [];
    for (let i = data.games.length - 1; i >= 0; i--) {
      const r = data.games[i];
      if (listState.site && r[C.site] !== listState.site) continue;
      if (listState.speed && r[C.speed] !== listState.speed) continue;
      if (listState.result && r[C.result] !== listState.result) continue;
      if (listState.from && r[C.at] < Date.parse(listState.from)) continue;
      if (listState.to && r[C.at] >= Date.parse(listState.to) + 864e5) continue;
      if (listState.min && !(r[C.oppRating] >= +listState.min)) continue;
      if (listState.max && !(r[C.oppRating] <= +listState.max)) continue;
      if (listState.comeback && !r[C.comeback]) continue;
      if (listState.upset && !(r[C.result] === "win" && r[C.oppRating] && r[C.rating] && r[C.oppRating] - r[C.rating] >= 100)) continue;
      if (listState.brilliant && !r[C.sacrifices]) continue;
      if (listState.reviewed && !r[C.reviewed]) continue;
      if (q && !r[C.opp].toLowerCase().includes(q) && !r[C.family].toLowerCase().includes(q)) continue;
      list.push(r);
    }
    document.getElementById("count").textContent = `${list.length.toLocaleString()} of ${data.total.toLocaleString()} games. ${data.analysed.toLocaleString()} analysed, ${data.reviewed.toLocaleString()} reviewed.`;
    sortGames(list);
    document.getElementById("rows").innerHTML = list.slice(0, listState.shown).map(gameRow).join("") || '<li class="note">No games match. Clear a filter to see more.</li>';
    document.getElementById("more").hidden = list.length <= listState.shown;
  };
  showRefresh();
  const reset = (key) => (event) => { listState[key] = event.target.value; listState.shown = 50; draw(); };
  document.getElementById("q").addEventListener("input", reset("q"));
  for (const [id, key] of [["f-from", "from"], ["f-to", "to"], ["f-min", "min"], ["f-max", "max"]]) document.getElementById(id).addEventListener("change", reset(key));
  for (const [id, key] of [["f-comeback", "comeback"], ["f-upset", "upset"], ["f-brilliant", "brilliant"], ["f-reviewed", "reviewed"]]) {
    document.getElementById(id).addEventListener("change", (event) => { listState[key] = event.target.checked; listState.shown = 50; draw(); });
  }
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

function moveTable(detail, sans, row) {
  if (!sans.length) return "";
  const parts = (detail.fen || "").split(" ");
  const blackFirst = parts[1] === "b";
  const first = +parts[5] || 1;
  const marks = annotations(detail, row);
  const cell = (ply) => {
    if (ply < 1 || ply > sans.length) return "<td></td>";
    const category = marks[ply];
    const mark = category && NOTE[category] ? `<span class="mark">${NOTE[category]}</span>` : "";
    const label = category ? ` title="${CATEGORY_NAME[category]}" class="tone-${category}"` : "";
    return `<td><button data-ply="${ply}"${label}>${figurine(sans[ply - 1])}${mark}</button></td>`;
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
  const n = detail.evals.length - 1, W = 600, H = 100;
  const white = row[C.color] === "w";
  const sign = white ? 1 : -1;
  const y = (cp) => (100 - winPercent(cp * sign)) / 100 * H;
  const x = (i) => i / Math.max(1, n) * W;
  const area = `M0 ${H}` + detail.evals.map((e, i) => `L${x(i).toFixed(1)} ${y(e).toFixed(1)}`).join("") + `L${W} ${H}Z`;
  const notes = annotations(detail, row);
  const dots = Object.entries(notes).filter(([, c]) => ["blunder", "mistake", "miss", "great", "brilliant"].includes(c)).map(([p, c]) => {
    const i = +p;
    return `<span class="eval-dot cat-${c}" style="left:${(x(i) / W * 100).toFixed(2)}%;top:${(y(detail.evals[i]) / H * 100).toFixed(2)}%"></span>`;
  }).join("");
  return `<div class="eval-wrap${white ? " you-white" : " you-black"}"><svg class="eval" id="eval" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Evaluation through the game. Your side is the lower fill; a higher line favours you."><path class="area" d="${area}"/><line class="mid" x1="0" x2="${W}" y1="${H / 2}" y2="${H / 2}" vector-effect="non-scaling-stroke"/><line class="now" id="evalnow" x1="${x(ply)}" x2="${x(ply)}" y1="0" y2="${H}" vector-effect="non-scaling-stroke"/></svg>${dots}</div>`;
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
      ${evalGraph(detail, row, ply)}
      ${playerBar(row, false)}<div class="board-sticky"><div class="board-row"><div class="bar-slot" id="evalbar"></div><div class="board-slot" id="board"></div></div></div>${playerBar(row, true)}
      <div class="controls"><button id="first" aria-label="First position">${ICONS.first}</button><button id="prev" aria-label="Previous move">${ICONS.prev}</button><button id="next" aria-label="Next move">${ICONS.next}</button><button id="last" aria-label="Last position">${ICONS.last}</button><span class="position" id="pos" aria-live="polite"></span></div>
      <div id="promote" class="promote" hidden></div>
      <div id="variation" class="variation" hidden></div>
      <div class="play-panel"><button id="play-start">Play from here</button><label>Computer strength <select id="play-elo"><option value="1400">1400</option><option value="1700" selected>1700</option><option value="2000">2000</option><option value="2500">2500</option><option value="3000">Full strength</option></select></label></div>
      <p class="play-status" id="play-status" aria-live="polite" hidden></p>
      <div class="engine-panel"><button id="engine-toggle" aria-pressed="false">Live engine</button><p class="note" id="engine-note">Drag or tap a piece on the board to try your own moves.</p><div id="engine-lines"></div></div>
      ${moveTable(detail, sans, row)}
    </div><div>${headline(row)}<p class="meta">${metaLine(row)}</p>${stats}${noReview}${reviewHTML(detail, true, undefined, row)}${summaryHTML(detail, row)}${clockChart(detail, row)}${styleHTML(detail)}
      ${detail.review ? `<p class="note">Review written by ${esc(detail.review.model)} from ${esc(detail.engine)} analysis.</p>` : ""}
      <p><a href="${esc(siteUrl)}" rel="noopener">Open on ${SITE_NAMES[row[C.site]]}</a></p></div></div>
    ${others.length ? `<section><h2>${reviewed.size ? "Other mistakes and blunders" : "Mistakes and blunders"}</h2><ul class="moments">${others.map((m) => `<li><button data-ply="${m.ply}"><b>${moveLabel(m.ply)} ${esc(m.san)} <span class="tag-${m.cat}">${m.cat}</span></b><span class="why">${pawns(m.before)} to ${pawns(m.after)}${m.best ? `, ${esc(m.best)} was better` : ""}${m.tags.length ? `, ${m.tags.map((t) => TAG_SHORT[t]).join(", ")}` : ""}</span></button></li>`).join("")}</ul></section>` : ""}
    ${(detail.great || []).length ? `<section><h2>Great moves</h2><ul class="moments">${detail.great.map((p) => `<li><button data-ply="${p}"><b>${moveLabel(p)} ${esc(sans[p - 1])}!</b><span class="why">The only move here that didn't lose.</span></button></li>`).join("")}</ul></section>` : ""}
    ${(detail.sacrifices || []).length ? `<section><h2>Brilliant moves</h2><ul class="moments">${detail.sacrifices.map((p) => `<li><button data-ply="${p}"><b>${moveLabel(p)} ${esc(sans[p - 1])}!!</b><span class="why">The engine's top move, leaving a piece where it can be taken.</span></button></li>`).join("")}</ul></section>` : ""}`;
  const notes = annotations(detail, row);
  const boardHost = document.getElementById("board");
  const pos = document.getElementById("pos");
  const evalNow = document.getElementById("evalnow");
  let variation = null;
  let playing = null;
  let selected = null;
  let targets = [];
  const currentFen = () => (variation ? variation.frames[variation.index] : line ? line.frames[ply] : null);
  const currentCp = () => {
    if (variation && engine.enabled && engine.fen === currentFen() && engine.lines["1"]) {
      const top = engine.lines["1"];
      return top.kind === "mate" ? (top.value > 0 ? 1000 : -1000) : Math.max(-1000, Math.min(1000, top.value));
    }
    return !variation && detail.evals ? detail.evals[ply] : variation ? variation.cp : null;
  };
  const paintBoard = () => {
    const fen = currentFen();
    if (!fen) return;
    const mark = variation ? variation.marks[variation.index] : line.marks[ply];
    const note = variation ? null : notes[ply];
    const label = variation ? "Board in your line" : ply ? `Board after ${moveLabel(ply)} ${sans[ply - 1]}` : "Starting position";
    const better = variation ? null : betterMove(detail, notes, line.frames, ply);
    boardHost.innerHTML = boardHTML(fen, flip, mark, label, note)
      + betterArrow(better, flip)
      + (engine.enabled && engine.fen === fen ? arrowsSVG(engine.lines, flip) : "");
    if (selected) {
      const from = boardHost.querySelector(`[data-sq="${selected}"]`);
      if (from) from.classList.add("selected");
      for (const t of targets) {
        const cell = boardHost.querySelector(`[data-sq="${t.to}"]`);
        if (cell) cell.classList.add(t.captured ? "can-take" : "can-move");
      }
    }
    const barHost = document.getElementById("evalbar");
    const cp = currentCp();
    if (barHost) barHost.innerHTML = cp == null ? "" : evalBar(cp, flip);
  };
  const paintEngine = () => {
    const box = document.getElementById("engine-lines");
    const button = document.getElementById("engine-toggle");
    if (!box || !button) return;
    button.setAttribute("aria-pressed", engine.enabled);
    const fen = currentFen();
    if (!engine.enabled || !fen) { box.innerHTML = ""; return; }
    const lines = ["1", "2"].filter((k) => engine.fen === fen && engine.lines[k]).map((k) => engine.lines[k]);
    box.innerHTML = lines.length
      ? lines.map((l) => `<p class="engine-line"><b>${engineScore(l)}</b> ${esc(lineToSan(fen, l.pv))}</p>`).join("") + `<p class="note">Depth ${lines[0].depth}, Stockfish 19 ${engine.attempt ? "(compatibility version, slower)" : "Lite"} in your browser.</p>`
      : new Chess(fen).game_over() ? '<p class="note">The game is over in this position.</p>' : '<p class="note">Thinking…</p>';
  };
  const paintVariation = () => {
    const box = document.getElementById("variation");
    if (!box) return;
    box.hidden = !variation;
    if (!variation) { box.innerHTML = ""; return; }
    const parts = variation.frames[0].split(" ");
    let number = +parts[5], white = parts[1] === "w";
    const moves = variation.sans.map((san, i) => {
      const prefix = white ? `${number}. ` : (i === 0 ? `${number}... ` : "");
      if (!white) number += 1;
      white = !white;
      return `${prefix}<button data-var="${i + 1}"${variation.index === i + 1 ? ' class="on"' : ""}>${esc(san)}</button>`;
    }).join(" ");
    box.innerHTML = `<p class="variation-line"><b>Your line:</b> ${moves}</p><button id="leave-variation">Back to the game</button>`;
  };
  const analyseNow = () => {
    const fen = currentFen();
    if (engine.enabled && fen && !new Chess(fen).game_over()) engine.analyse(fen);
    else if (engine.enabled) engine.stop();
  };
  const refresh = () => {
    paintBoard();
    pos.textContent = variation
      ? (variation.index ? `Your line: ${variation.sans[variation.index - 1]}` : "Your line: start")
      : ply ? `${moveLabel(ply)} ${sans[ply - 1]}` : "Start";
    const better = !variation && line ? betterMove(detail, notes, line.frames, ply) : null;
    if (better) pos.textContent += `, better: ${better.san}`;
    document.querySelectorAll("#moves button").forEach((b) => {
      const current = !variation && +b.dataset.ply === ply;
      b.classList.toggle("on", current);
      if (current) b.setAttribute("aria-current", "true"); else b.removeAttribute("aria-current");
    });
    const list = document.getElementById("moves");
    const active = list && list.querySelector("button.on");
    if (active) {
      const box = list.getBoundingClientRect(), item = active.getBoundingClientRect();
      if (item.top < box.top + 30 || item.bottom > box.bottom) list.scrollTop += item.top - box.top - box.height / 2;
    } else if (list && !variation) list.scrollTop = 0;
    if (evalNow) { const x = ply / Math.max(1, (detail.evals || [0, 0]).length - 1) * 600; evalNow.setAttribute("x1", x); evalNow.setAttribute("x2", x); }
    paintVariation();
    analyseNow();
    paintEngine();
  };
  const canMoveNow = () => {
    if (!playing) return true;
    if (playing.thinking) return false;
    const fen = currentFen();
    return !!fen && fen.split(" ")[1] === playing.color;
  };
  const paintPlay = () => {
    const box = document.getElementById("play-status");
    const start = document.getElementById("play-start");
    if (!box || !start) return;
    start.textContent = playing ? "Stop playing" : "Play from here";
    box.hidden = !playing;
    if (!playing) { box.textContent = ""; return; }
    const game = new Chess(currentFen());
    const who = playing.color === "w" ? "White" : "Black";
    if (game.in_checkmate()) box.textContent = game.turn() === playing.color ? "Checkmate. The computer won." : "Checkmate. You won!";
    else if (game.game_over()) box.textContent = "The game is drawn.";
    else if (playing.problem) box.textContent = "The computer couldn't start in this browser.";
    else if (playing.thinking) box.textContent = "The computer is thinking…";
    else box.textContent = game.turn() === playing.color ? `You're playing ${who}. Your move.` : "Step forward to the latest position to continue.";
  };
  const stopPlaying = () => {
    if (!playing) return;
    playing = null;
    opponent.stop();
    paintPlay();
  };
  const startVariation = () => {
    if (!variation) variation = { frames: [line.frames[ply]], marks: [line.marks[ply]], sans: [], index: 0, cp: detail.evals ? detail.evals[ply] : null };
  };
  const addToVariation = (game, move) => {
    variation.frames.length = variation.index + 1;
    variation.marks.length = variation.index + 1;
    variation.sans.length = variation.index;
    variation.frames.push(game.fen());
    variation.marks.push([move.from, move.to]);
    variation.sans.push(move.san);
    variation.index += 1;
  };
  const computerTurn = () => {
    if (!playing) return;
    const fen = currentFen();
    if (new Chess(fen).game_over() || fen.split(" ")[1] === playing.color) { paintPlay(); return; }
    playing.thinking = true;
    paintPlay();
    const session = playing;
    opponent.ask(fen, session.elo, (uci) => {
      if (playing !== session) return;
      session.thinking = false;
      const game = new Chess(currentFen());
      const move = game.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] });
      if (move) addToVariation(game, move);
      refresh();
      paintPlay();
    }, () => {
      if (playing !== session) return;
      session.thinking = false;
      session.problem = true;
      paintPlay();
    });
  };
  const clearSelection = () => { selected = null; targets = []; document.getElementById("promote").hidden = true; };
  const go = (next) => {
    if (!line) return;
    stopPlaying();
    variation = null;
    clearSelection();
    ply = Math.max(0, Math.min(line.frames.length - 1, next));
    refresh();
  };
  const step = (delta) => {
    if (!variation) { go(ply + delta); return; }
    clearSelection();
    const index = variation.index + delta;
    if (index < 0) { go(ply); return; }
    variation.index = Math.min(index, variation.sans.length);
    refresh();
  };
  const playMove = (from, to, promotion) => {
    const game = new Chess(currentFen());
    const move = game.move({ from, to, promotion });
    clearSelection();
    if (!move) { refresh(); return; }
    if (!variation && !playing && ply < sans.length && bareMove(sans[ply]) === bareMove(move.san)) { go(ply + 1); return; }
    startVariation();
    addToVariation(game, move);
    if (!engine.enabled && !playing) engine.enabled = true;
    refresh();
    computerTurn();
  };
  const onSquare = (square) => {
    const fen = currentFen();
    if (!fen || !canMoveNow()) return;
    const game = new Chess(fen);
    const target = targets.find((t) => t.to === square);
    if (selected && target) {
      if (target.promotion) {
        const box = document.getElementById("promote");
        const from = selected;
        box.hidden = false;
        box.innerHTML = '<span>Promote to</span>' + [["q", "Queen"], ["r", "Rook"], ["b", "Bishop"], ["n", "Knight"]].map(([k, n]) => `<button data-promo="${k}">${n}</button>`).join("");
        box.onclick = (event) => {
          const button = event.target.closest("[data-promo]");
          if (button) playMove(from, square, button.dataset.promo);
        };
        return;
      }
      playMove(selected, square);
      return;
    }
    const piece = game.get(square);
    if (piece && piece.color === game.turn() && square !== selected) {
      selected = square;
      targets = game.moves({ square, verbose: true });
      paintBoard();
    } else {
      clearSelection();
      paintBoard();
    }
  };
  let drag = null;
  let press = null;
  const endDrag = () => {
    if (drag && drag.ghost) drag.ghost.remove();
    drag = null;
  };
  const moveGhost = (event) => {
    drag.ghost.style.left = `${event.clientX - drag.size / 2}px`;
    drag.ghost.style.top = `${event.clientY - drag.size / 2}px`;
  };
  boardHost.addEventListener("pointerdown", (event) => {
    if (event.button) return;
    const cell = event.target.closest("[data-sq]");
    press = cell ? { square: cell.dataset.sq, x: event.clientX, y: event.clientY } : null;
    const fen = currentFen();
    if (!cell || !fen || !canMoveNow()) return;
    const square = cell.dataset.sq;
    const game = new Chess(fen);
    const piece = game.get(square);
    if (!piece || piece.color !== game.turn()) return;
    const image = cell.querySelector(".pc");
    drag = { from: square, x: event.clientX, y: event.clientY, moved: false, wasSelected: selected === square, size: cell.offsetWidth, src: image ? image.src : "" };
    selected = square;
    targets = game.moves({ square, verbose: true });
    paintBoard();
    boardHost.setPointerCapture(event.pointerId);
  });
  boardHost.addEventListener("pointermove", (event) => {
    if (!drag) return;
    if (!drag.moved && Math.hypot(event.clientX - drag.x, event.clientY - drag.y) < 6) return;
    if (!drag.moved) {
      drag.moved = true;
      drag.ghost = document.createElement("img");
      drag.ghost.src = drag.src;
      drag.ghost.alt = "";
      drag.ghost.className = "drag-piece";
      drag.ghost.style.width = drag.ghost.style.height = `${drag.size}px`;
      document.body.appendChild(drag.ghost);
      const source = boardHost.querySelector(`[data-sq="${drag.from}"] .pc`);
      if (source) source.style.opacity = "0.25";
    }
    moveGhost(event);
  });
  // Taps are handled here rather than on click, because selecting a piece redraws the square being pressed.
  boardHost.addEventListener("pointerup", (event) => {
    if (!drag) {
      const tapped = press && Math.hypot(event.clientX - press.x, event.clientY - press.y) < 12 ? press.square : null;
      press = null;
      if (tapped) onSquare(tapped);
      return;
    }
    const { moved, wasSelected, from } = drag;
    endDrag();
    press = null;
    const under = moved ? document.elementFromPoint(event.clientX, event.clientY) : null;
    const cell = under && under.closest("#board [data-sq]");
    if (!moved || (cell && cell.dataset.sq === from)) {
      if (wasSelected) clearSelection();
      paintBoard();
      return;
    }
    if (cell && targets.some((t) => t.to === cell.dataset.sq)) onSquare(cell.dataset.sq);
    else { clearSelection(); paintBoard(); }
  });
  boardHost.addEventListener("pointercancel", () => { press = null; endDrag(); clearSelection(); paintBoard(); });
  engine.listener = (lines, problem) => {
    if (problem) {
      engine.enabled = false;
      document.getElementById("engine-note").textContent = problem;
      paintEngine();
      return;
    }
    paintBoard();
    paintEngine();
  };
  document.getElementById("play-start").onclick = () => {
    if (playing) { stopPlaying(); refresh(); return; }
    const fen = currentFen();
    if (!fen) return;
    startVariation();
    variation.cp = null;
    engine.enabled = false;
    engine.stop();
    clearSelection();
    playing = { color: fen.split(" ")[1], elo: +document.getElementById("play-elo").value, thinking: false };
    refresh();
    paintPlay();
  };
  document.getElementById("engine-toggle").onclick = () => {
    engine.enabled = !engine.enabled;
    if (!engine.enabled) engine.stop();
    refresh();
  };
  document.getElementById("variation").addEventListener("click", (event) => {
    if (event.target.closest("#leave-variation")) { go(ply); return; }
    const button = event.target.closest("[data-var]");
    if (button) { clearSelection(); variation.index = +button.dataset.var; refresh(); }
  });
  if (!line) boardHost.innerHTML = '<p class="note">This position can’t be replayed here. Open the original game instead.</p>';
  document.getElementById("first").onclick = () => go(0);
  document.getElementById("prev").onclick = () => step(-1);
  document.getElementById("next").onclick = () => step(1);
  document.getElementById("last").onclick = () => go(Infinity);
  app.addEventListener("click", plyClick);
  const graph = document.getElementById("eval");
  if (graph) graph.addEventListener("pointerdown", (event) => {
    const box = graph.getBoundingClientRect();
    go(Math.round((event.clientX - box.left) / box.width * (detail.evals.length - 1)));
  });
  keyHandler = (event) => {
    if (event.key === "ArrowLeft") step(-1);
    if (event.key === "ArrowRight") step(1);
  };
  document.addEventListener("keydown", keyHandler);
  function plyClick(event) {
    const button = event.target.closest("[data-ply]");
    if (!button) return;
    go(+button.dataset.ply);
    if (!button.closest("#moves")) boardHost.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  cleanup = () => { app.removeEventListener("click", plyClick); engine.stop(); engine.enabled = false; engine.listener = null; stopPlaying(); };
  go(ply);
}


const THEME_NAMES = { all: "All themes", week: "This week", hung_piece: "Hanging pieces", missed_material: "Winning a piece", allowed_mate: "Stopping mate", missed_mate: "Finding mate", low_clock: "Low on time", opening: "Opening", middlegame: "Middlegame", endgame: "Endgame" };
const PROGRESS_KEY = "pinkroses-practice-v1";
const REVIEW_DAYS = [0, 1, 3, 7, 21, 60];

function loadPractice() {
  try { return JSON.parse(localStorage.getItem(PROGRESS_KEY)) || { items: {}, solved: 0, attempts: 0, streak: 0, best: 0 }; }
  catch { return { items: {}, solved: 0, attempts: 0, streak: 0, best: 0 }; }
}
function savePractice(state) {
  try { localStorage.setItem(PROGRESS_KEY, JSON.stringify(state)); } catch { /* progress just won't persist */ }
}

let puzzleData = null;
async function getPuzzles() {
  if (!puzzleData) {
    const response = await fetch("data/puzzles.json");
    if (!response.ok) throw new Error("Could not load practice positions");
    puzzleData = await response.json();
  }
  return puzzleData;
}

function matchesTheme(p, theme) {
  if (theme === "all") return true;
  if (theme === "week") return p.at >= Date.now() - 7 * 864e5;
  return p.phase === theme || p.tags.includes(theme);
}

function choosePuzzle(list, state, skip) {
  const now = Date.now();
  const due = list.filter((p) => state.items[p.id] && state.items[p.id].due <= now && p.id !== skip);
  if (due.length) return due[0];
  const fresh = list.filter((p) => !state.items[p.id] && p.id !== skip);
  if (fresh.length) return fresh[Math.floor(Math.random() * Math.min(fresh.length, 150))];
  return null;
}

function wirePlayableBoard(host, { getFen, canMove, onPick }) {
  let selected = null, targets = [], drag = null, press = null;
  const mark = () => {
    host.querySelectorAll(".selected,.can-move,.can-take").forEach((c) => c.classList.remove("selected", "can-move", "can-take"));
    if (!selected) return;
    const from = host.querySelector(`[data-sq="${selected}"]`);
    if (from) from.classList.add("selected");
    for (const t of targets) {
      const cell = host.querySelector(`[data-sq="${t.to}"]`);
      if (cell) cell.classList.add(t.captured ? "can-take" : "can-move");
    }
  };
  const clear = () => { selected = null; targets = []; mark(); };
  const choose = (from, to) => { clear(); onPick(from, to); };
  host.addEventListener("pointerdown", (event) => {
    press = null;
    if (event.button || !canMove()) return;
    const cell = event.target.closest("[data-sq]");
    if (!cell) return;
    press = { square: cell.dataset.sq, x: event.clientX, y: event.clientY };
    const game = new Chess(getFen());
    const piece = game.get(cell.dataset.sq);
    if (!piece || piece.color !== game.turn()) return;
    const image = cell.querySelector(".pc");
    drag = { from: cell.dataset.sq, x: event.clientX, y: event.clientY, moved: false, was: selected === cell.dataset.sq, size: cell.offsetWidth, src: image ? image.src : "" };
    selected = cell.dataset.sq;
    targets = game.moves({ square: selected, verbose: true });
    mark();
    host.setPointerCapture(event.pointerId);
  });
  host.addEventListener("pointermove", (event) => {
    if (!drag) return;
    if (!drag.moved && Math.hypot(event.clientX - drag.x, event.clientY - drag.y) < 6) return;
    if (!drag.moved) {
      drag.moved = true;
      drag.ghost = document.createElement("img");
      drag.ghost.src = drag.src;
      drag.ghost.alt = "";
      drag.ghost.className = "drag-piece";
      drag.ghost.style.width = drag.ghost.style.height = `${drag.size}px`;
      document.body.appendChild(drag.ghost);
    }
    drag.ghost.style.left = `${event.clientX - drag.size / 2}px`;
    drag.ghost.style.top = `${event.clientY - drag.size / 2}px`;
  });
  host.addEventListener("pointerup", (event) => {
    if (!drag) {
      const tapped = press && Math.hypot(event.clientX - press.x, event.clientY - press.y) < 12 ? press.square : null;
      press = null;
      if (!tapped || !canMove()) return;
      if (selected && targets.some((t) => t.to === tapped)) choose(selected, tapped);
      else clear();
      return;
    }
    const { moved, was, from, ghost } = drag;
    if (ghost) ghost.remove();
    drag = null;
    press = null;
    const under = moved ? document.elementFromPoint(event.clientX, event.clientY) : null;
    const cell = under && under.closest("[data-sq]");
    if (!moved || (cell && cell.dataset.sq === from)) { if (was) clear(); return; }
    if (cell && host.contains(cell) && targets.some((t) => t.to === cell.dataset.sq)) choose(from, cell.dataset.sq);
    else clear();
  });
  host.addEventListener("pointercancel", () => { if (drag && drag.ghost) drag.ghost.remove(); drag = null; press = null; clear(); });
  return { clear, repaint: mark };
}

async function practiceView(themeArg) {
  setNav("practice");
  const all = await getPuzzles();
  let theme = THEME_NAMES[themeArg] ? themeArg : "all";
  const state = loadPractice();
  const counts = {};
  for (const key of Object.keys(THEME_NAMES)) counts[key] = all.filter((p) => matchesTheme(p, key)).length;
  app.innerHTML = `<h1 class="page-title">Practice your mistakes</h1>
    <p class="hint">Each position comes from one of your own games, right before a blunder. Find the better move. Positions you miss come back sooner. Your progress is saved in this browser.</p>
    <div class="filters"><select id="theme" aria-label="Theme">${Object.keys(THEME_NAMES).filter((k) => counts[k]).map((k) => `<option value="${k}" ${k === theme ? "selected" : ""}>${THEME_NAMES[k]} (${counts[k].toLocaleString()})</option>`).join("")}</select></div>
    <div id="practice-stats"></div>
    <div class="game-head"><div><div class="board-slot" id="pz-board"></div></div><div>
      <h2 id="pz-title"></h2><p class="meta" id="pz-meta"></p><p id="pz-message" aria-live="polite"></p>
      <div class="controls" id="pz-actions"></div><div class="controls" id="pz-steps" hidden><button id="pz-prev" aria-label="Previous move">${ICONS.prev}</button><button id="pz-next" aria-label="Next move">${ICONS.next}</button><span class="position" id="pz-pos"></span></div>
    </div></div>`;
  const host = document.getElementById("pz-board");
  const title = document.getElementById("pz-title");
  const meta = document.getElementById("pz-meta");
  const message = document.getElementById("pz-message");
  const actions = document.getElementById("pz-actions");
  const stepsBox = document.getElementById("pz-steps");
  let puzzle = null, stage = "solve", firstTry = true, flip = false, checking = false;
  let frames = [], marks = [], names = [], index = 0, attemptMark = null;

  const paintStats = () => {
    const seen = Object.keys(state.items).length;
    const due = Object.values(state.items).filter((i) => i.due <= Date.now()).length;
    const rate = state.attempts ? Math.round(state.solved * 100 / state.attempts) : 0;
    const tile = (value, label) => `<div class="stat"><b>${value}</b><span>${label}</span></div>`;
    document.getElementById("practice-stats").innerHTML = `<div class="stats">${tile(state.streak, `Streak, best ${state.best}`)}${tile(`${rate}%`, "First try")}${tile(seen.toLocaleString(), "Tried")}${tile(due, "Due")}</div>`;
  };
  const paint = (note) => {
    const fen = stage === "solve" ? puzzle.fen : frames[index];
    const mark = stage === "solve" ? attemptMark : marks[index];
    host.innerHTML = boardHTML(fen, flip, mark, "Practice position", note || null);
    board.repaint();
  };
  const record = (solved) => {
    const item = state.items[puzzle.id] || { box: 0 };
    state.attempts += 1;
    if (solved) {
      state.solved += 1;
      state.streak += 1;
      state.best = Math.max(state.best, state.streak);
      item.box = Math.min(item.box + 1, REVIEW_DAYS.length - 1);
    } else {
      state.streak = 0;
      item.box = 0;
    }
    item.due = Date.now() + (solved ? REVIEW_DAYS[item.box] : 0.5) * 864e5;
    state.items[puzzle.id] = item;
    savePractice(state);
    paintStats();
  };
  const flash = (good) => {
    message.className = good ? "pz-good" : "pz-bad";
    host.classList.remove("flash-good", "flash-bad");
    void host.offsetWidth;
    host.classList.add(good ? "flash-good" : "flash-bad");
  };
  const reveal = (text) => {
    stage = "done";
    frames = [puzzle.fen];
    marks = [null];
    names = ["Start"];
    const game = new Chess(puzzle.fen);
    for (const san of puzzle.line) {
      const move = game.move(san, { sloppy: true });
      if (!move) break;
      frames.push(game.fen());
      marks.push([move.from, move.to]);
      names.push(move.san);
    }
    index = Math.min(1, frames.length - 1);
    message.textContent = text;
    stepsBox.hidden = frames.length < 2;
    showStep();
    actions.innerHTML = `<button id="pz-again">Next position</button><a class="button-link" href="#/game/${esc(puzzle.game)}/${puzzle.ply}">Open the game</a>`;
    document.getElementById("pz-again").onclick = nextPuzzle;
  };
  const showStep = () => {
    paint(null);
    document.getElementById("pz-pos").textContent = index ? `Engine line: ${names.slice(1, index + 1).join(" ")}` : "Start";
  };
  const finishMiss = () => {
    record(false);
    flash(false);
    const drop = `${pawns(puzzle.before)} to ${pawns(puzzle.after)}`;
    reveal(`The move was ${puzzle.line[0]}. In the game you played ${puzzle.played}, going from ${drop}. This one comes back soon.`);
  };
  const correct = (text) => {
    if (firstTry) record(true); else record(false);
    flash(true);
    const drop = `${pawns(puzzle.before)} to ${pawns(puzzle.after)}`;
    reveal(`${text} In the game you played ${puzzle.played}, going from ${drop}.`);
  };
  const onPick = async (from, to) => {
    if (stage !== "solve" || checking) return;
    const game = new Chess(puzzle.fen);
    const target = new Chess(puzzle.fen).move(puzzle.line[0], { sloppy: true });
    const promotion = target && target.from === from && target.to === to ? target.promotion : "q";
    const move = game.move({ from, to, promotion });
    if (!move) return;
    attemptMark = [from, to];
    host.innerHTML = boardHTML(game.fen(), flip, attemptMark, "Your move", null);
    if (bareMove(move.san) === bareMove(puzzle.line[0])) { correct("Correct!"); return; }
    if (bareMove(move.san) === bareMove(puzzle.played)) {
      message.textContent = `That's the move you played in the game, ${puzzle.played}. Look for something better.`;
      firstTry = false;
      attemptMark = null;
      setTimeout(() => { if (stage === "solve") paint(null); }, 900);
      return;
    }
    checking = true;
    message.textContent = "Checking your move…";
    const score = await checkMove(game.fen());
    checking = false;
    if (stage !== "solve") return;
    const mine = puzzle.fen.split(" ")[1] === "w" ? 1 : -1;
    if (score != null && winPercent(score * mine) >= winPercent(puzzle.before) - 5) {
      correct(`${move.san} also works, about as well as the engine's ${puzzle.line[0]}.`);
      return;
    }
    firstTry = false;
    attemptMark = null;
    paint(null);
    flash(false);
    message.textContent = score == null ? `Not the engine's move. Try again.` : `${move.san} isn't good enough${score != null ? ` (${pawns(score * mine)})` : ""}. Try again.`;
  };
  const checkMove = async (fen) => {
    const listener = engine.listener;
    engine.listener = () => {};
    try {
      engine.analyse(fen);
      await new Promise((resolve) => setTimeout(resolve, engine.attempt ? 5000 : 1800));
      const top = engine.lines["1"];
      if (!top || engine.fen !== fen) return null;
      return top.kind === "mate" ? (top.value > 0 ? 1000 : -1000) : Math.max(-1000, Math.min(1000, top.value));
    } catch { return null; } finally {
      engine.stop();
      engine.listener = listener;
    }
  };
  const board = wirePlayableBoard(host, { getFen: () => puzzle.fen, canMove: () => stage === "solve" && !checking, onPick });
  const nextPuzzle = () => {
    const list = all.filter((p) => matchesTheme(p, theme));
    const chosen = choosePuzzle(list, state, puzzle && puzzle.id);
    stepsBox.hidden = true;
    if (!chosen) {
      host.innerHTML = "";
      title.textContent = "All caught up";
      meta.textContent = "";
      message.textContent = "Nothing is due in this theme. Pick another theme or come back later.";
      actions.innerHTML = "";
      return;
    }
    puzzle = chosen;
    stage = "solve";
    firstTry = true;
    attemptMark = null;
    flip = puzzle.fen.split(" ")[1] === "b";
    title.textContent = `${puzzle.fen.split(" ")[1] === "w" ? "White" : "Black"} to move`;
    meta.textContent = `${cap(puzzle.speed)} vs ${puzzle.opp}, ${dateText(puzzle.at)}. You're at ${pawns(puzzle.before)}.${puzzle.tags.length ? ` Theme: ${puzzle.tags.map((t) => THEME_NAMES[t] || t).join(", ")}.` : ""}`;
    message.className = "";
    host.classList.remove("flash-good", "flash-bad");
    message.textContent = "Find the best move.";
    actions.innerHTML = '<button id="pz-show">Show solution</button><button id="pz-skip">Skip</button>';
    document.getElementById("pz-show").onclick = finishMiss;
    document.getElementById("pz-skip").onclick = nextPuzzle;
    paint(null);
  };
  document.getElementById("pz-prev").onclick = () => { if (index > 0) { index -= 1; showStep(); } };
  document.getElementById("pz-next").onclick = () => { if (index < frames.length - 1) { index += 1; showStep(); } };
  document.getElementById("theme").onchange = (event) => { theme = event.target.value; puzzle = null; nextPuzzle(); };
  paintStats();
  nextPuzzle();
  cleanup = () => { engine.stop(); engine.listener = null; };
}

let openingData = null;
async function openingsView(arg) {
  setNav("openings");
  if (!openingData) {
    const response = await fetch("data/openings.json");
    if (!response.ok) throw new Error("Could not load openings");
    openingData = await response.json();
  }
  let color = arg === "black" ? "black" : "white";
  let path = [];
  app.innerHTML = `<h1 class="page-title">Your opening explorer</h1><p class="hint">Your own games, move by move. Score counts a draw as half a point. Error rate is how often that move was your mistake or blunder.</p>
    <div class="controls"><button data-color="white">As White</button><button data-color="black">As Black</button><button id="op-back">Back a move</button></div>
    <div class="game-head"><div><div class="board-slot" id="op-board"></div></div><div><p class="meta" id="op-line"></p><p id="op-stats"></p><div class="table-wrap" id="op-table"></div><div id="op-games"></div></div></div>`;
  const nodeAt = () => {
    let node = openingData[color];
    for (const move of path) node = node.c[move];
    return node;
  };
  const score = (n) => Math.round((n.w + n.d / 2) * 100 / n.n);
  const draw = () => {
    const node = nodeAt();
    const game = new Chess();
    let mark = null;
    for (const san of path) { const m = game.move(san); mark = [m.from, m.to]; }
    document.getElementById("op-board").innerHTML = boardHTML(game.fen(), color === "black", mark, "Opening position", null);
    document.querySelectorAll("[data-color]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.color === color));
    document.getElementById("op-line").textContent = path.length ? path.map((m, i) => (i % 2 ? m : `${i / 2 + 1}. ${m}`)).join(" ") : "Starting position";
    document.getElementById("op-stats").textContent = `${node.n.toLocaleString()} games, ${node.w} wins, ${node.d} draws, ${node.l} losses, ${score(node)}% score.`;
    const yourTurn = (path.length % 2 === 0) === (color === "white");
    const rows = Object.entries(node.c).sort((a, b) => b[1].n - a[1].n);
    document.getElementById("op-table").innerHTML = rows.length ? `<table><thead><tr><th>${yourTurn ? "Your move" : "Their move"}</th><th class="num">Games</th><th class="num">Score</th>${yourTurn ? '<th class="num">Error rate</th>' : ""}</tr></thead><tbody>${rows.map(([move, n]) => `<tr><td><button class="moveref" data-move="${esc(move)}">${esc(move)}</button></td><td class="num">${n.n.toLocaleString()}</td><td class="num">${score(n)}%</td>${yourTurn ? `<td class="num">${Math.round(n.e * 100 / n.n)}%</td>` : ""}</tr>`).join("")}</tbody></table>` : '<p class="note">Not enough games to go further from here.</p>';
    const byId = new Map(data.games.map((r) => [r[C.id], r]));
    document.getElementById("op-games").innerHTML = node.g.length ? `<h3 class="sub-head">Recent games from here</h3><ul class="rows">${node.g.map((id) => byId.get(id)).filter(Boolean).map(gameRow).join("")}</ul>` : "";
  };
  app.querySelector(".controls").addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    if (button.id === "op-back") path.pop();
    else { color = button.dataset.color; path = []; }
    draw();
  });
  document.getElementById("op-table").addEventListener("click", (event) => {
    const button = event.target.closest("[data-move]");
    if (button) { path.push(button.dataset.move); draw(); }
  });
  draw();
}

const SPEED_ICONS = {
  bullet: "M4 12c0-3 3-5 7-5h2l7 5-7 5h-2c-4 0-7-2-7-5z",
  blitz: "M13 2 5 14h6l-1 8 9-13h-6z",
  rapid: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zm1 4v5.4l4 2.4-1 1.6-5-3V7z",
  classical: "M7 3h10v2l-4 6 4 6v2H7v-2l4-6-4-6z",
};
function speedIcon(speed) {
  const d = SPEED_ICONS[speed] || SPEED_ICONS.rapid;
  return `<svg class="speed-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${d}"/></svg>`;
}

function gameRow(r) {
  const acc = r[C.acc];
  const bar = acc == null ? "" : `<span class="acc-bar" aria-hidden="true"><i style="width:${Math.max(2, Math.min(100, acc))}%"></i></span>`;
  const chips = [
    r[C.blunders] ? plural(r[C.blunders], "blunder") : "",
    r[C.sacrifices] ? `<b class="tone-brilliant">${r[C.sacrifices]} !!</b>` : "",
    r[C.great] ? `<b class="tone-great">${r[C.great]} !</b>` : "",
    r[C.reviewed] ? "reviewed" : "",
    r[C.bot] ? "bot" : "",
  ].filter(Boolean).join(", ");
  return `<li><a class="game-card result-${r[C.result]}" href="#/game/${r[C.id]}"><span class="res ${r[C.result]}">${resultWord[r[C.result]]}</span><span class="opp">${esc(r[C.opp])}${r[C.oppRating] ? ` <small>${r[C.oppRating]}</small>` : ""}</span><span class="acc-box">${acc == null ? "" : `${Math.round(acc)}%`}${bar}</span><span class="dt">${new Date(r[C.at]).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "2-digit" })}</span><span class="sub">${speedIcon(r[C.speed])}${SITE_NAMES[r[C.site]]}, ${esc(r[C.family])}${chips ? `<br>${chips}` : ""}</span></a></li>`;
}

function opponentView(name) {
  setNav("games");
  const games = data.games.filter((r) => r[C.opp] === name).sort((a, b) => b[C.at] - a[C.at]);
  if (!games.length) { app.innerHTML = '<h1 class="page-title">Opponent not found</h1><p><a href="#/games">Back to all games</a></p>'; return; }
  const tally = (list) => list.reduce((t, r) => { t[r[C.result]] += 1; return t; }, { win: 0, draw: 0, loss: 0 });
  const line = (t) => `${t.win} wins, ${t.draw} draws, ${t.loss} losses`;
  const all = tally(games);
  const asColor = (c) => games.filter((r) => r[C.color] === c);
  const openings = {};
  for (const r of games) { const o = openings[r[C.family]] || (openings[r[C.family]] = { n: 0, p: 0 }); o.n += 1; o.p += r[C.result] === "win" ? 1 : r[C.result] === "draw" ? .5 : 0; }
  const acc = games.filter((r) => r[C.acc] != null);
  app.innerHTML = `<h1 class="page-title">${esc(name)}</h1><p>${games.length} ${games.length === 1 ? "game" : "games"}: ${line(all)}.</p>
    <p class="meta">As White: ${line(tally(asColor("w")))}. As Black: ${line(tally(asColor("b")))}.${acc.length ? ` Your average accuracy: ${Math.round(acc.reduce((s, r) => s + r[C.acc], 0) / acc.length)}%.` : ""}</p>
    <section class="tight"><h2>Openings</h2><div class="table-wrap"><table><thead><tr><th>Opening</th><th class="num">Games</th><th class="num">Your score</th></tr></thead><tbody>${Object.entries(openings).sort((a, b) => b[1].n - a[1].n).slice(0, 8).map(([o, v]) => `<tr><td>${esc(o)}</td><td class="num">${v.n}</td><td class="num">${Math.round(v.p * 100 / v.n)}%</td></tr>`).join("")}</tbody></table></div></section>
    <section class="tight"><h2>Games</h2><ul class="rows">${games.slice(0, 100).map(gameRow).join("")}</ul></section>`;
}

function opponentsSection() {
  const counts = {};
  for (const r of data.games) if (!r[C.bot] && !/^(Anonymous|Stockfish level)/.test(r[C.opp])) { const o = counts[r[C.opp]] || (counts[r[C.opp]] = { n: 0, p: 0 }); o.n += 1; o.p += r[C.result] === "win" ? 1 : r[C.result] === "draw" ? .5 : 0; }
  const top = Object.entries(counts).filter(([, v]) => v.n >= 2).sort((a, b) => b[1].n - a[1].n).slice(0, 8);
  if (!top.length) return "";
  return `<section><h2>Most played opponents</h2><div class="table-wrap"><table><thead><tr><th>Opponent</th><th class="num">Games</th><th class="num">Your score</th></tr></thead><tbody>${top.map(([name, v]) => `<tr><td><a href="#/opponent/${encodeURIComponent(name)}">${esc(name)}</a></td><td class="num">${v.n}</td><td class="num">${Math.round(v.p * 100 / v.n)}%</td></tr>`).join("")}</tbody></table></div></section>`;
}

function clockSection() {
  const rows = data.clock_stats || [];
  if (!rows.length) return "";
  const labels = rows[0].buckets.map((b) => b.label);
  return `<section><h2>Mistakes by clock</h2><p class="hint">Mistakes and blunders per 100 of your moves, by how much of your starting time was left.</p><div class="table-wrap"><table><thead><tr><th>Time control</th>${labels.map((l) => `<th class="num">${l}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr><td>${cap(r.speed)}</td>${r.buckets.map((b) => `<td class="num">${b.rate == null ? "n/a" : b.rate.toFixed(1)}</td>`).join("")}</tr>`).join("")}</tbody></table></div></section>`;
}

function clockChart(detail, row) {
  const clocks = detail.clocks;
  if (!clocks || clocks.length < 4) return "";
  const top = Math.max(...clocks, 1), W = 600, H = 120, m = 34;
  const x = (i) => m + i / (clocks.length - 1) * (W - m - 8);
  const y = (v) => 8 + (top - v) / top * (H - 28);
  const path = (start) => clocks.map((v, i) => [i, v]).filter(([i]) => i % 2 === start).map(([i, v], k) => `${k ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join("");
  const mine = row[C.color] === "w" ? 0 : 1;
  const fmt = (s) => s >= 60 ? `${Math.floor(s / 60)}m` : `${s}s`;
  return `<section class="tight"><h2>Time left</h2><div class="legend"><span><i style="background:var(--s1)"></i>You</span><span><i style="background:var(--s2)"></i>${esc(row[C.opp])}</span></div><div class="chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Clock time left during the game"><line class="grid" x1="${m}" x2="${W - 8}" y1="${y(0)}" y2="${y(0)}"/><text x="${m - 4}" y="${y(top) + 4}" text-anchor="end">${fmt(top)}</text><text x="${m - 4}" y="${y(0) + 4}" text-anchor="end">0</text><path d="${path(mine)}" fill="none" stroke="var(--s1)" stroke-width="2"/><path d="${path(1 - mine)}" fill="none" stroke="var(--s2)" stroke-width="2"/></svg></div></section>`;
}

function trendSVG(values) {
  if (!values || values.length < 2) return "";
  const lo = Math.min(...values), hi = Math.max(...values), W = 90, H = 24;
  const d = values.map((v, i) => `${i ? "L" : "M"}${(i / (values.length - 1) * W).toFixed(1)} ${(H - 3 - (v - lo) / Math.max(1, hi - lo) * (H - 6)).toFixed(1)}`).join("");
  return `<svg class="trend" viewBox="0 0 ${W} ${H}" aria-hidden="true"><path d="${d}" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>`;
}

function progressSection() {
  const rows = (data.progress || []).filter((r) => SPEEDS.includes(r.speed)).sort((a, b) => b.games - a.games);
  if (!rows.length) return "";
  return `<section><h2>What's holding you back</h2><p class="hint">Based on your last ${rows[0].games} rated games in each time control, weighted by how much win chance each error cost.</p><ul class="focus-list">${rows.map((r) => {
    const change = r.previous == null ? "" : ` (${r.accuracy >= r.previous ? "up" : "down"} ${Math.abs(r.accuracy - r.previous).toFixed(1)} from the ${r.games} before)`;
    const leak = r.leak ? `Your clearest pattern is ${r.leak_text}, ${r.leak_share}% of win chance lost.` : "";
    const practice = r.leak ? `<a href="#/practice/${r.leak}">Practice this</a>` : "";
    return `<li><h3>${SITE_NAMES[r.site]} ${r.speed} ${trendSVG(r.trend)}</h3><p>Accuracy ${r.accuracy}%${change}. Most lost in ${r.phase_text} (${r.phase_share}%). ${leak} ${practice}</p></li>`;
  }).join("")}</ul></section>`;
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
    else if (hash.startsWith("practice")) await practiceView(hash.split("/")[1]);
    else if (hash.startsWith("openings")) await openingsView(hash.split("/")[1]);
    else if (hash.startsWith("opponent/")) opponentView(decodeURIComponent(hash.slice(9)));
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
