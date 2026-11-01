// Read-only website frontend. No order controls exist or may be added here.
"use strict";

const TA = {
  async api(path) {
    const res = await fetch(path, { headers: { Accept: "application/json" } });
    if (res.status === 401) {
      window.location.replace("/auth/login");
      throw new Error("unauthenticated");
    }
    if (!res.ok) throw new Error(`${path} -> HTTP ${res.status}`);
    return res.json();
  },
  money(v) {
    if (v === null || v === undefined) return "-";
    return Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  },
  num(v) {
    if (v === null || v === undefined) return "-";
    return Number(v).toLocaleString("en-US", { maximumFractionDigits: 4 });
  },
  ts(v) {
    if (!v) return "-";
    try { return new Date(v).toISOString().replace("T", " ").slice(0, 19) + "Z"; }
    catch { return String(v); }
  },
  esc(v) {
    return String(v ?? "").replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  },
  flags(el, envelope) {
    const elx = document.querySelector(el);
    if (!elx) return;
    const flags = envelope.quality_flags || [];
    elx.innerHTML = flags.length
      ? flags.map((f) => `<span class="flag">${this.esc(f)}</span>`).join("")
      : '<span class="flags-ok">data current</span>';
  },
  table(el, columns, rows) {
    const box = document.querySelector(el);
    if (!box) return;
    const head = columns.map((c) =>
      `<th class="${c.align || ""}">${this.esc(c.label)}</th>`).join("");
    const body = rows.map((r) =>
      `<tr>${columns.map((c) =>
        `<td class="${c.align || ""} ${c.cls || ""}">${c.render(r)}</td>`).join("")}</tr>`
    ).join("");
    box.innerHTML = rows.length ? `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`
                                : '<p class="muted">no records</p>';
  },
  loadRuns(selectEl) {
    return this.api("/api/v1/runs").then((env) => {
      const runs = env.payload.runs || [];
      selectEl.innerHTML = runs.length
        ? `<option value="">latest run</option>` + runs.map((r) =>
            `<option value="${this.esc(r.run_id)}">${this.esc(r.run_id.slice(-12))} ${this.esc(r.status)}</option>`).join("")
        : '<option value="">no runs yet</option>';
      return runs;
    });
  },
  runParam() {
    const sel = document.querySelector("[data-run-select]");
    if (!sel || !sel.value) return "";
    return `run_id=${encodeURIComponent(sel.value)}`;
  },
  chart(el, series) {
    const box = document.querySelector(el);
    if (!box) return;
    const points = series.filter((p) => p.equity !== null && p.equity !== undefined);
    if (points.length < 2) { box.innerHTML = '<p class="muted" style="padding:12px">not enough data to chart</p>'; return; }
    const w = 1100, h = 220, pad = 10;
    const vals = points.map((p) => Number(p.equity));
    const min = Math.min(...vals), max = Math.max(...vals);
    const span = max - min || 1;
    const xy = points.map((p, i) => [
      pad + (i * (w - 2 * pad)) / (points.length - 1),
      h - pad - ((Number(p.equity) - min) / span) * (h - 2 * pad),
    ]);
    const path = xy.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
    box.innerHTML = `<svg viewBox="0 0 ${w} ${h}" style="width:100%;display:block">
      <path d="${path}" fill="none" stroke="#58a6ff" stroke-width="1.5"/>
      <text x="${pad}" y="16" fill="#8b949e" font-size="12">max ${max.toFixed(2)}</text>
      <text x="${pad}" y="${h - 2}" fill="#8b949e" font-size="12">min ${min.toFixed(2)} · ${points.length} points</text>
    </svg>`;
  },
};

document.addEventListener("DOMContentLoaded", () => {
  const runSel = document.querySelector("[data-run-select]");
  if (runSel) runSel.addEventListener("change", () => window.location.reload());
  const page = document.body.dataset.page;
  if (page === "overview") {
    TA.api("/api/v1/health").then((env) => {
      document.querySelector("[data-health]").innerHTML =
        `<span class="muted">db:${env.payload.database} web:${env.payload.web} recon:${TA.esc(env.payload.last_reconciliation)}</span>`;
    }).catch(() => {});
    TA.api("/api/v1/overview" + (runSel && runSel.value ? "?" + TA.runParam() : "")).then((env) => {
      const p = env.payload;
      if (p.note) document.querySelector("[data-overview-note]").textContent = p.note;
      TA.flags("[data-flags-overview]", env);
      const cards = [["authority", p.authority || ""], ["initial cash", "$" + TA.money(p.initial_cash)],
                     ["decisions", p.counts && p.counts.decisions], ["orders", p.counts && p.counts.orders],
                     ["fills", p.counts && p.counts.fills], ["reconciliation", p.reconciliation && p.reconciliation.last_status]];
      document.querySelector("[data-cards]").innerHTML = cards.filter(([, v]) => v !== undefined)
        .map(([k, v]) => `<div class="card"><div class="k">${k}</div><div class="v">${TA.esc(String(v))}</div></div>`).join("");
      if (p.books && p.books.length) TA.table("[data-books]", [
        { label: "Book", render: (r) => TA.esc(r.label || r.key) },
        { label: "Equity", align: "right", cls: "num", render: (r) => "$" + TA.money(r.equity) },
        { label: "Cash", align: "right", cls: "num", render: (r) => "$" + TA.money(r.cash) },
        { label: "Gross exposure", align: "right", cls: "num", render: (r) => "$" + TA.money(r.gross_exposure) },
        { label: "Reconciliation", render: (r) => `<span class="${r.reconciliation_status === "ok" ? "" : "stale"}">${TA.esc(r.reconciliation_status)}</span>` },
        { label: "As of", render: (r) => `<span class="muted">${TA.ts(r.as_of)}</span>` },
      ], p.books);
      const q = runSel && runSel.value ? "?" + TA.runParam() : "";
      TA.api("/api/v1/equity-curve" + q).then((c) => TA.chart("[data-chart]", (c.payload.series || []).slice(-500)));
    }).catch(() => {});
  }
  if (page === "portfolio") {
    const q = runSel && runSel.value ? "?" + TA.runParam() : "";
    TA.api("/api/v1/positions" + q).then((env) => {
      const p = env.payload;
      TA.flags("[data-flags-portfolio]", env);
      document.querySelector("[data-summary]").innerHTML =
        `<div class="card"><div class="k">Cash</div><div class="v num">$${TA.money(p.cash)}</div></div>
         <div class="card"><div class="k">Equity</div><div class="v num">$${TA.money(p.equity)}</div></div>
         <div class="card"><div class="k">Gross exposure</div><div class="v num">$${TA.money(p.gross_exposure)}</div></div>`;
      TA.table("[data-positions]", [
        { label: "Instrument", render: (r) => `<a href="/instruments/${TA.esc(r.instrument_id)}">${TA.esc(r.instrument_id)}</a>` },
        { label: "Quantity", align: "right", cls: "num", render: (r) => TA.num(r.quantity) },
        { label: "Avg cost", align: "right", cls: "num", render: (r) => TA.money(r.average_cost) },
        { label: "Mark", align: "right", cls: "num", render: (r) => `<span class="${r.mark_stale ? "stale" : ""}">${TA.money(r.mark)}${r.mark_stale ? " (stale)" : ""}</span>` },
        { label: "Market value", align: "right", cls: "num", render: (r) => "$" + TA.money(r.market_value) },
        { label: "Mark as of", render: (r) => `<span class="muted">${TA.ts(r.mark_as_of)}</span>` },
      ], p.positions);
    }).catch(() => {});
  }
  if (page === "orders") {
    const load = () => {
      const status = document.querySelector("[data-status-filter]")?.value;
      const q = Object.entries({ run_id: runSel && runSel.value, status: status || undefined })
        .filter(([, v]) => v) .map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
      TA.api("/api/v1/orders" + (q ? "?" + q : "")).then((env) => {
        TA.flags("[data-flags-orders]", env);
        TA.table("[data-orders]", [
          { label: "Order", render: (r) => `<a class="mono" href="/orders/${TA.esc(r.order_id)}">${TA.esc(r.order_id.slice(-10))}</a>` },
          { label: "Instrument", render: (r) => TA.esc(r.instrument_id) },
          { label: "Side", render: (r) => TA.esc(r.side) },
          { label: "Qty", align: "right", cls: "num", render: (r) => TA.num(r.quantity) },
          { label: "Filled", align: "right", cls: "num", render: (r) => TA.num(r.filled_quantity) },
          { label: "Limit", align: "right", cls: "num", render: (r) => TA.money(r.limit_price) },
          { label: "Status", render: (r) => `<span class="${/fail|cancel|reject/i.test(r.status || "") ? "error" : ""}">${TA.esc(r.status)}</span>` },
          { label: "Updated", render: (r) => `<span class="muted">${TA.ts(r.updated_at)}</span>` },
        ], env.payload.orders);
      }).catch(() => {});
    };
    document.querySelector("[data-status-filter]")?.addEventListener("change", load);
    load();
  }
  if (page === "order-detail") {
    const id = document.body.dataset.orderId;
    TA.api(`/api/v1/orders/${encodeURIComponent(id)}`).then((env) => {
      const p = env.payload;
      if (p.error) { document.querySelector("[data-order]").innerHTML = `<p class="error">${TA.esc(p.error)}</p>`; return; }
      TA.flags("[data-flags-order]", env);
      const o = p.order;
      document.querySelector("[data-order]").innerHTML =
        `<div class="cards">
           <div class="card"><div class="k">Instrument</div><div class="v">${TA.esc(o.instrument_id)}</div></div>
           <div class="card"><div class="k">Side</div><div class="v">${TA.esc(o.side)}</div></div>
           <div class="card"><div class="k">Qty / filled</div><div class="v num">${TA.num(o.quantity)} / ${TA.num(o.filled_quantity)}</div></div>
           <div class="card"><div class="k">Status</div><div class="v">${TA.esc(o.status)}</div></div>
           <div class="card"><div class="k">VWAP</div><div class="v num">${p.vwap && p.vwap[o.side] ? "$" + TA.money(p.vwap[o.side]) : "-"}</div></div>
         </div>
         <h2>Decision</h2><pre class="mono">${TA.esc(JSON.stringify(p.decision, null, 2))}</pre>
         <h2>Risk evaluation</h2><pre class="mono">${TA.esc(JSON.stringify(p.risk_evaluation, null, 2))}</pre>
         <h2>Submission attempts</h2><pre class="mono">${TA.esc(JSON.stringify(p.attempts, null, 2))}</pre>
         <h2>Status transitions</h2><pre class="mono">${TA.esc(JSON.stringify(p.events, null, 2))}</pre>`;
      TA.table("[data-order-fills]", [
        { label: "Fill", render: (r) => `<span class="mono">${TA.esc(r.fill_id.slice(-10))}</span>` },
        { label: "Ts", render: (r) => TA.ts(r.ts) },
        { label: "Side", render: (r) => TA.esc(r.side) },
        { label: "Qty", align: "right", cls: "num", render: (r) => TA.num(r.quantity) },
        { label: "Price", align: "right", cls: "num", render: (r) => "$" + TA.money(r.price) },
        { label: "Fee", align: "right", cls: "num", render: (r) => TA.money(r.fee) },
      ], p.fills);
    }).catch(() => {});
  }
  if (page === "activity") {
    let cursor = null;
    let events = [];
    const load = () => {
      const q = Object.entries({ run_id: runSel && runSel.value, cursor, limit: 20 })
        .filter(([, v]) => v !== null && v !== undefined && v !== "")
        .map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
      TA.api("/api/v1/activity" + (q ? "?" + q : "")).then((env) => {
        TA.flags("[data-flags-activity]", env);
        cursor = env.pagination.next_cursor || null;
        document.querySelector("[data-load-more]").disabled = !cursor;
        events = events.concat(env.payload.events);
        TA.table("[data-activity]", [
          { label: "Ts", render: (r) => `<span class="muted">${TA.ts(r.ts)}</span>` },
          { label: "Origin", render: (r) => `<span class="muted">${TA.esc(r.origin)}</span>` },
          { label: "Type", render: (r) => TA.esc(r.event_type) },
          { label: "Payload", render: (r) => `<span class="mono">${TA.esc(JSON.stringify(r.payload)).slice(0, 120)}</span>` },
        ], events);
      }).catch(() => {});
    };
    document.querySelector("[data-load-more]")?.addEventListener("click", load);
    load();
  }
  if (page === "instrument") {
    const id = document.body.dataset.instrumentId;
    TA.api(`/api/v1/instruments/${encodeURIComponent(id)}`).then((env) => {
      TA.flags("[data-flags-instrument]", env);
      document.querySelector("[data-instrument]").innerHTML =
        `<div class="cards">${Object.entries(env.payload.instrument || {})
          .map(([k, v]) => `<div class="card"><div class="k">${TA.esc(k)}</div><div class="v">${TA.esc(typeof v === "object" ? JSON.stringify(v) : v)}</div></div>`).join("")}</div>`;
      TA.api(`/api/v1/prices/${encodeURIComponent(id)}`).then((pe) => {
        TA.flags("[data-flags-prices]", pe);
        TA.table("[data-prices]", [
          { label: "Ts", render: (r) => TA.ts(r.ts) },
          { label: "Bid", align: "right", cls: "num", render: (r) => TA.money(r.bid) },
          { label: "Ask", align: "right", cls: "num", render: (r) => TA.money(r.ask) },
          { label: "Last", align: "right", cls: "num", render: (r) => TA.money(r.last) },
        ], (pe.payload.prices || []).slice(-50));
      }).catch(() => {});
    }).catch(() => {});
  }
  if (page === "login") {
    const form = document.querySelector("[data-login-form]");
    form?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const token = form.token.value;
      const res = await fetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: `token=${encodeURIComponent(token)}`,
      });
      if (res.ok && res.redirected) window.location.replace(res.url);
      else if (res.ok) window.location.replace("/");
      else document.querySelector("[data-login-error]").textContent = "invalid owner token";
    });
  }
});
