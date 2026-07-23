/* =========================================================================
   Cauzon site interactions — vanilla JS, no deps.
   ========================================================================= */
(() => {
  "use strict";
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];

  /* ---------- nav: scrolled state + mobile toggle + progress ---------- */
  const nav = $("#nav");
  const progress = $("#scrollProgress");
  const onScroll = () => {
    const y = window.scrollY;
    nav.classList.toggle("scrolled", y > 24);
    const h = document.documentElement.scrollHeight - window.innerHeight;
    progress.style.width = (h > 0 ? (y / h) * 100 : 0) + "%";
  };
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  const toggle = $("#navToggle");
  const links = $("#navLinks");
  toggle?.addEventListener("click", () => links.classList.toggle("open"));
  $$("#navLinks a").forEach((a) => a.addEventListener("click", () => links.classList.remove("open")));

  /* ---------- scroll reveal ---------- */
  const revealables = $$(".reveal");
  if ("IntersectionObserver" in window && !reduceMotion) {
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }),
      { threshold: 0.14 }
    );
    revealables.forEach((el) => io.observe(el));
  } else {
    revealables.forEach((el) => el.classList.add("in"));
  }

  /* ---------- number tickers ---------- */
  const tickers = $$("[data-count]");
  const runTicker = (el) => {
    const target = +el.dataset.count;
    if (reduceMotion || target === 0) { el.textContent = target; return; }
    const dur = 1200; const start = performance.now();
    const step = (t) => {
      const p = Math.min((t - start) / dur, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = Math.round(eased * target);
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  };
  if ("IntersectionObserver" in window) {
    const tio = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { runTicker(e.target); tio.unobserve(e.target); } }), { threshold: 0.5 });
    tickers.forEach((t) => tio.observe(t));
  } else tickers.forEach(runTicker);

  /* ---------- spotlight on cards + bento ---------- */
  $$(".card, .bento-cell").forEach((card) => {
    card.addEventListener("pointermove", (e) => {
      const r = card.getBoundingClientRect();
      card.style.setProperty("--mx", `${e.clientX - r.left}px`);
      card.style.setProperty("--my", `${e.clientY - r.top}px`);
    });
  });

  /* ---------- hero terminal typewriter ---------- */
  const term = $("#termBody");
  const TERM_LINES = [
    { c: "dim", t: "$ cauzon investigate --live\n" },
    { c: "p-detect", t: "[DETECT]      " }, { c: "", t: "daily_revenue — volume assertion failed\n" },
    { c: "p-scope", t: "[SCOPE]       " }, { c: "", t: "pulled 2 upstream nodes within 3 hops\n" },
    { c: "p-hyp", t: "[HYPOTHESIZE] " }, { c: "", t: "ranked candidates → raw_trips (51h stale, −100% rows)\n" },
    { c: "p-prove", t: "[PROVE]       " }, { c: "", t: "verified path raw_trips → trips_cleaned → daily_revenue\n" },
    { c: "p-wb", t: "[WRITEBACK]   " }, { c: "", t: "dossier saved · raw_trips tagged root-cause\n\n" },
    { c: "ok", t: "✔ grounded root cause: raw_trips  (confidence 80%)\n" },
  ];
  function typeTerminal() {
    if (!term) return;
    if (reduceMotion) { term.innerHTML = TERM_LINES.map(l => `<span class="${l.c}">${l.t}</span>`).join(""); return; }
    term.innerHTML = ""; let li = 0, ci = 0; let cursor = document.createElement("span"); cursor.className = "cursor";
    let span = null;
    const tick = () => {
      if (li >= TERM_LINES.length) { cursor.remove(); return; }
      const line = TERM_LINES[li];
      if (ci === 0) { span = document.createElement("span"); span.className = line.c; term.appendChild(span); term.appendChild(cursor); }
      span.textContent += line.t[ci];
      term.insertBefore(cursor, null);
      ci++;
      if (ci >= line.t.length) { li++; ci = 0; }
      const delay = line.t[ci - 1] === "\n" ? 90 : 12 + Math.random() * 22;
      setTimeout(tick, delay);
    };
    tick();
  }
  if ("IntersectionObserver" in window) {
    const tio2 = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { typeTerminal(); tio2.unobserve(e.target); } }), { threshold: 0.3 });
    if (term) tio2.observe(term);
  } else typeTerminal();

  /* ---------- interactive proof investigation ---------- */
  const phases = ["detect", "scope", "hypothesize", "prove", "writeback"];
  const nodes = { symptom: $("#n-symptom"), mid: $("#n-mid"), cause: $("#n-cause") };
  const edges = [$("#e-1"), $("#e-2")];
  const track = $$("#phaseTrack span");
  const dossier = $("#dossier");
  const evidence = $$("#evidence li");
  const sqlBlock = $("#sqlBlock");
  const conf = $("#confBadge");
  const causeMeta = $("#cause-meta");
  const wbChips = $$("#writebackRow .wb-chip");
  const replayBtn = $("#replayBtn");
  let playing = false;

  const wait = (ms) => new Promise((r) => setTimeout(r, ms));

  function resetProof() {
    track.forEach((s) => s.classList.remove("active", "done"));
    Object.values(nodes).forEach((n) => n.classList.remove("scanning", "cause-found"));
    edges.forEach((e) => e.classList.remove("beam", "lit"));
    dossier.classList.remove("revealed");
    evidence.forEach((li) => li.classList.remove("show"));
    sqlBlock.classList.remove("show");
    wbChips.forEach((c) => c.classList.remove("show"));
    conf.textContent = "—";
    causeMeta.textContent = "upstream";
  }

  const setPhase = (i) => {
    track.forEach((s, idx) => {
      s.classList.toggle("active", idx === i);
      s.classList.toggle("done", idx < i);
    });
  };

  async function playProof() {
    if (playing) return;
    playing = true; resetProof();
    replayBtn.disabled = true; replayBtn.textContent = "Investigating…";

    // 1 detect
    setPhase(0); nodes.symptom.classList.add("scanning"); await wait(900);
    nodes.symptom.classList.remove("scanning");

    // 2 scope — beam down the edges
    setPhase(1);
    edges[0].classList.add("beam"); await wait(700); edges[0].classList.add("lit");
    nodes.mid.classList.add("scanning"); await wait(500); nodes.mid.classList.remove("scanning");
    edges[1].classList.add("beam"); await wait(700); edges[1].classList.add("lit");

    // 3 hypothesize — scan cause
    setPhase(2); nodes.cause.classList.add("scanning"); await wait(1000);

    // 4 prove — cause found + evidence
    setPhase(3);
    nodes.cause.classList.remove("scanning"); nodes.cause.classList.add("cause-found");
    causeMeta.textContent = "⛳ root cause · ingestion stalled";
    dossier.classList.add("revealed");
    conf.textContent = "confidence 80%";
    for (const li of evidence) { li.classList.add("show"); await wait(400); }
    sqlBlock.classList.add("show"); await wait(700);

    // 5 writeback
    setPhase(4);
    for (const c of wbChips) { c.classList.add("show"); await wait(350); }
    track.forEach((s) => s.classList.add("done"));
    track[4].classList.remove("done"); track[4].classList.add("active");

    replayBtn.disabled = false; replayBtn.textContent = "▶ Replay investigation";
    playing = false;
  }

  replayBtn?.addEventListener("click", playProof);
  // autoplay once when scrolled into view
  if ("IntersectionObserver" in window && $("#proof")) {
    const pio = new IntersectionObserver((es) => es.forEach((e) => {
      if (e.isIntersecting) { if (!reduceMotion) playProof(); else { resetProof(); setPhase(4); dossier.classList.add("revealed"); nodes.cause.classList.add("cause-found"); evidence.forEach(l=>l.classList.add("show")); sqlBlock.classList.add("show"); wbChips.forEach(c=>c.classList.add("show")); conf.textContent="confidence 80%"; } pio.unobserve(e.target); }
    }), { threshold: 0.35 });
    pio.observe($("#proof"));
  }

  /* ---------- year in footer (if present) ---------- */
})();
