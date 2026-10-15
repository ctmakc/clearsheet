(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => (s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const GROUPS = [
    ["emergency", "Go to Emergency if"], ["warning", "Warning signs"], ["medication", "Medicines"],
    ["follow_up", "Appointments and tests"], ["self_care", "Looking after yourself"],
  ];
  const STATE_LABEL = { ok: "verified", review: "nurse check", blocked: "blocked" };
  let run = null, released = new Set(), edits = {}, selected = null, docText = "";

  async function init() {
    const st = await (await fetch("/api/status")).json();
    const b = $("backend");
    b.classList.add(st.mode);
    $("backendText").textContent = st.mode === "live"
      ? `Live · ${st.model} · ${st.backend}`
      : `Replay of a recorded run · ${st.recorded[1] || st.model} · ${st.recorded[0] || "AMD Instinct MI300X"}`;
    for (const [k, v] of Object.entries(st.languages)) $("lang").add(new Option(v, k, k === "uk", k === "uk"));
    const samples = await (await fetch("/api/samples")).json();
    samples.forEach((s, i) => $("case").add(new Option(`${String(i + 1).padStart(2, "0")} · ${s.title}`, s.id)));
    $("case").add(new Option("Paste your own (live endpoint only)", "__paste"));
    $("case").addEventListener("change", loadCase);
    $("controls").addEventListener("submit", (e) => { e.preventDefault(); doRun(); });
    $("release").addEventListener("click", releaseSheet);
    $("close").addEventListener("click", () => ($("overlay").hidden = true));
    $("print").addEventListener("click", () => $("sheetFrame").contentWindow.print());
    $("run").textContent = st.mode === "live" ? "Run on AMD" : "Run (replay)";
    await loadCase();
    loadEval();
  }

  async function loadCase() {
    const id = $("case").value;
    const paste = id === "__paste";
    $("paste").hidden = !paste; $("doc").hidden = paste;
    if (!paste) {
      const d = await (await fetch(`/api/sample/${id}`)).json();
      docText = d.text;
      $("doc").textContent = d.text;
    }
  }

  async function doRun() {
    const paste = $("case").value === "__paste";
    const text = paste ? $("paste").value : docText;
    if (!text.trim()) return;
    $("run").disabled = true; $("runinfo").textContent = "Gemma is reading the summary…";
    $("groups").innerHTML = '<p class="empty">Extracting facts, writing the plain version and the translation, back-translating for the nurse…</p>';
    const t0 = performance.now();
    try {
      const r = await fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, lang: $("lang").value, doc_id: paste ? "pasted" : $("case").value }) });
      const j = await r.json();
      if (!r.ok) { $("groups").innerHTML = `<p class="empty">${esc(j.message || j.detail || "Run failed")}</p>`; return; }
      run = j; edits = {}; selected = null;
      released = new Set(j.items.filter((i) => i.state === "ok").map((i) => i.id));
      $("runinfo").textContent = `${j.items.length} lines · ${((performance.now() - t0) / 1000).toFixed(1)} s`;
      $("paste").hidden = true; $("doc").hidden = false;
      renderDoc(); renderItems(true); renderLog();
    } catch (e) {
      $("groups").innerHTML = `<p class="empty">Network error: ${esc(String(e))}</p>`;
    } finally { $("run").disabled = false; }
  }

  function renderDoc(range) {
    const t = run ? run.scrubbed : docText;
    let html;
    if (range && range[0] >= 0) {
      html = withPh(t.slice(0, range[0])) + `<mark id="m">${withPh(t.slice(range[0], range[1]))}</mark>` + withPh(t.slice(range[1]));
    } else html = withPh(t);
    $("doc").innerHTML = html;
    const m = document.getElementById("m");
    if (m) { const d = $("doc"); d.scrollTo({ top: Math.max(0, m.offsetTop - d.clientHeight / 3), behavior: "smooth" }); requestAnimationFrame(() => requestAnimationFrame(() => m.classList.add("on"))); }
    const masked = run ? Object.entries(run.masked).map(([k, v]) => `${v} ${k.toLowerCase().replace("_", " ")}`).join(", ") : "";
    $("masked").textContent = masked ? `masked on this machine before any model call: ${masked}` : "identifiers are masked on this machine before any model call";
  }
  const withPh = (s) => esc(s).replace(/\[[A-Z_]+_\d+\]/g, (m) => `<span class="ph">${m}</span>`);

  function findQuote(q) {
    if (!q) return [-1, -1];
    const t = run.scrubbed, lt = t.toLowerCase(), lq = q.toLowerCase().trim();
    let i = lt.indexOf(lq);
    if (i < 0) { const n = lq.replace(/\s+/g, " "); i = lt.replace(/\s+/g, " ").indexOf(n); if (i >= 0) return [i, i + n.length]; }
    return i < 0 ? [-1, -1] : [i, i + lq.length];
  }

  function renderItems(enter) {
    const rtl = run.lang === "ar";
    let html = "", n = 0;
    for (const [kind, title] of GROUPS) {
      const its = run.items.filter((i) => i.kind === kind);
      if (!its.length) continue;
      html += `<h3>${title}</h3>`;
      for (const it of its) {
        const isRel = released.has(it.id), edited = it.id in edits;
        const canRel = it.state !== "blocked" || edited;
        const chip = isRel ? `<span class="chip released">released</span>` : `<span class="chip ${it.state}">${STATE_LABEL[it.state]}</span>`;
        const head = kind === "medication" ? `<div class="drug">${esc(it.data.name)}<small>${esc(it.data.dose)} ${esc(it.data.frequency)}</small></div>` : "";
        const pt = edited ? edits[it.id] : it.patient;
        const issues = [...it.issues.map((x) => `<li class="bad">${esc(x)}</li>`), ...it.translation_issues.map((x) => `<li class="warn">${esc(x)}</li>`), ...it.risk.map((x) => `<li class="warn">${esc(x)}</li>`)];
        html += `<div class="row ${enter ? "enter" : ""} ${selected === it.id ? "sel" : ""}" data-id="${it.id}" style="animation-delay:${enter ? n++ * 40 : 0}ms">
          <div class="rid">${it.id}</div>
          <div class="body">${head}${pt ? `<div class="pt" ${rtl ? 'dir="rtl"' : ""}>${esc(pt)}</div>` : `<div class="pt en">No patient text: this line is held back.</div>`}
            ${it.plain_en && run.lang !== "en" ? `<div class="en">${esc(it.plain_en)}</div>` : ""}</div>
          <div class="side">${chip}
            <label class="rel" onclick="event.stopPropagation()"><input type="checkbox" data-rel="${it.id}" ${isRel ? "checked" : ""} ${canRel ? "" : "disabled"}><span>release</span></label></div>
          <div class="details" onclick="event.stopPropagation()"><dl>
            <dt>Source</dt><dd class="q">${esc(it.data.source_quote || "")} <span class="note">(match ${it.grounding.toFixed(2)})</span></dd>
            ${run.lang !== "en" ? `<dt>Back-translation</dt><dd>${esc(it.back_en || "—")}</dd>` : ""}
            ${issues.length ? `<dt>Checks</dt><dd><ul style="margin:0;padding-left:16px">${issues.join("")}</ul></dd>` : `<dt>Checks</dt><dd>quote found verbatim, numbers match the source</dd>`}
            <dt>Edit</dt><dd><button class="edit" data-edit="${it.id}">${edited ? "Edit again" : "Write this line myself"}</button></dd>
          </dl></div></div>`;
      }
    }
    $("groups").innerHTML = html;
    $("groups").querySelectorAll(".row").forEach((r) => r.addEventListener("click", () => select(r.dataset.id)));
    $("groups").querySelectorAll("[data-rel]").forEach((c) => c.addEventListener("change", (e) => {
      const id = e.target.dataset.rel; e.target.checked ? released.add(id) : released.delete(id); renderItems(false); renderTally(id);
    }));
    $("groups").querySelectorAll("[data-edit]").forEach((b) => b.addEventListener("click", () => startEdit(b.dataset.edit)));
    renderTally();
  }

  function startEdit(id) {
    const it = run.items.find((i) => i.id === id);
    const dd = document.querySelector(`[data-edit="${id}"]`).parentElement;
    dd.innerHTML = `<textarea ${run.lang === "ar" ? 'dir="rtl"' : ""}>${esc(edits[id] ?? it.patient ?? "")}</textarea><button class="edit" style="margin-top:6px">Save line</button>`;
    dd.querySelector("button").addEventListener("click", () => {
      const v = dd.querySelector("textarea").value.trim();
      if (v) { edits[id] = v; released.add(id); }
      renderItems(false); renderTally(id);
    });
  }

  function select(id) {
    selected = selected === id ? null : id;
    const it = run.items.find((i) => i.id === id);
    renderItems(false);
    renderDoc(selected ? findQuote(it.data.source_quote) : null);
  }

  function renderTally(stampId) {
    const c = { ok: 0, review: 0, blocked: 0 };
    run.items.forEach((i) => c[i.state]++);
    $("tally").innerHTML = `<span class="chip ok">${c.ok} verified</span><span class="chip review">${c.review} nurse check</span><span class="chip blocked">${c.blocked} blocked</span>`;
    const pending = run.items.filter((i) => i.state !== "ok" && !released.has(i.id) && !(i.state === "blocked" && !(i.id in edits)));
    const blockedOpen = run.items.filter((i) => i.state === "blocked" && !(i.id in edits));
    $("releaseBar").hidden = false;
    $("leftCount").textContent = pending.length;
    $("leftText").textContent = pending.length
      ? `line${pending.length > 1 ? "s" : ""} still need a nurse decision` + (blockedOpen.length ? ` · ${blockedOpen.length} blocked line${blockedOpen.length > 1 ? "s" : ""} stay off the sheet` : "")
      : `all lines decided · ${released.size} will print` + (blockedOpen.length ? ` · ${blockedOpen.length} blocked stay off` : "");
    $("release").disabled = pending.length > 0 || released.size === 0;
    if (stampId) { const ch = document.querySelector(`.row[data-id="${stampId}"] .chip`); if (ch) ch.classList.add("stamp"); }
  }

  async function releaseSheet() {
    const r = await fetch("/api/sheet", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: run.run_id, approved: [...released], edits, reviewer: $("reviewer").value.trim() }) });
    const html = await r.text();
    if (!r.ok) { alert(html); return; }
    $("sheetFrame").srcdoc = html; $("overlay").hidden = false;
  }

  function renderLog() {
    $("log").hidden = false;
    $("logRows").innerHTML = run.stats.map((s) => `<tr><td>${esc(s.step)}${s.replayed ? ' <span class="note">(recorded)</span>' : ""}</td><td>${esc(s.backend)}</td><td>${esc(s.model)}</td><td class="n">${s.prompt_tokens}</td><td class="n">${s.completion_tokens}</td><td class="n">${s.latency_s.toFixed(1)}</td></tr>`).join("");
  }

  async function loadEval() {
    const r = await fetch("/api/eval"); if (!r.ok) return;
    const e = await r.json(), m = e.medications, pct = (x) => (x == null ? "—" : `${Math.round(x * 100)}%`);
    const tl = Object.entries(e.translation_clean_rate).map(([k, v]) => `${k} ${pct(v)}`).join(" · ");
    $("evalgrid").innerHTML = [
      [pct(m.recall), `medicines found (${m.tp}/${m.gt})`], [`${m.invented ?? "—"}`, `invented medicines (${m.extracted - m.tp} extra rows are taper steps or repeats)`],
      [pct(m.dose_exact), "doses exact"], [pct(e.mutation_test.rate), `injected errors caught (${e.mutation_test.caught}/${e.mutation_test.total})`],
      [pct(e.translation_mutation_test.rate), "wrong doses in translation caught"],
      ...(e.urgency_mutation_test ? [[pct(e.urgency_mutation_test.rate), `softened emergency lines caught (${e.urgency_mutation_test.caught}/${e.urgency_mutation_test.total})`]] : []), [`${e.completion_tokens_per_s_aggregate}`, "output tokens/s during this eval, 16 requests in parallel"],
    ].map(([a, b]) => `<div><b>${a}</b><span>${b}</span></div>`).join("");
    $("evalnote").textContent = `${e.docs} synthetic discharge summaries × ${e.languages.length} languages, ${e.calls} model calls, ${e.backend}, ${e.model}, ${e.run_at}. Translation lines with no automatic flag: ${tl}.`;
    $("evalbox").hidden = false;
  }
  init();
})();
