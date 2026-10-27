(function () {
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const rs = (x) => {
    x = Number(x) || 0;
    const a = Math.abs(x);
    if (a >= 1e6) return "Rs " + (x / 1e6).toFixed(1) + "m";
    if (a >= 1e4) return "Rs " + Math.round(x / 1e3).toLocaleString("en-US") + "k";
    return "Rs " + Math.round(x).toLocaleString("en-US");
  };
  const pct = (x, d = 1) => (100 * (Number(x) || 0)).toFixed(d) + "%";
  const num = (x) => Math.round(Number(x) || 0).toLocaleString("en-US");
  const bold = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  const $ = (id) => document.getElementById(id);

  function table(el, head, rows, numCols = []) {
    const th = head.map((h, i) => `<th class="${numCols.includes(i) ? "num" : ""}">${esc(h)}</th>`).join("");
    const tb = rows.map((r) => "<tr>" + r.map((c, i) => `<td class="${numCols.includes(i) ? "num" : ""}">${c}</td>`).join("") + "</tr>").join("");
    el.innerHTML = `<thead><tr>${th}</tr></thead><tbody>${tb}</tbody>`;
  }

  function baseOptions(extra = {}) {
    const grid = css("--grid"), muted = css("--muted");
    return Object.assign({
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { labels: { color: muted, boxWidth: 12, usePointStyle: true } } },
      scales: {
        x: { grid: { display: false }, ticks: { color: muted, maxRotation: 0, autoSkipPadding: 18 } },
        y: { grid: { color: grid }, ticks: { color: muted }, beginAtZero: true },
      },
    }, extra);
  }

  fetch("data/dashboard.json", { cache: "no-store" }).then((r) => r.json()).then(render).catch((e) => {
    $("asof").textContent = "Could not load data";
    console.error(e);
  });

  function render(d) {
    const k = d.kpis, m = d.meta;
    $("asof").textContent = `Data as of ${m.as_of_label} · updated ${m.generated_at}`;
    $("note").textContent = m.note;
    document.querySelectorAll(".grace").forEach((e) => (e.textContent = m.grace_days));

    $("brief").innerHTML = d.brief.map((b) => `<li class="${b.startsWith("**Employer alert") ? "alert" : ""}">${bold(b)}</li>`).join("");
    $("calls-total").textContent = num(d.calls.total);
    $("sms-total").textContent = num(d.calls.sms);
    $("by-action").innerHTML = d.calls.by_action.sort((a, b) => b.calls - a.calls)
      .map((a) => `<li><span>${esc(a.action)}</span><span>${a.calls} · ${rs(a.amount)}</span></li>`).join("");

    const up = (x) => (x > 0 ? "▲ " : x < 0 ? "▼ " : "");
    const kpis = [
      ["Amount receivable", rs(k.portfolio_outstanding), `${num(k.active_loans)} active loans · incl. markup`, ""],
      [`Collected on ${m.as_of_label.slice(0, 6)}`, rs(k.collected_day), `${num(k.payments_day)} payments`, ""],
      ["Collection rate, month to date", pct(k.collection_efficiency_mtd, 0), `of ${rs(k.due_mtd)} due`, ""],
      ["PAR30", pct(k.par30, 2), `${up(k.par30_change_7d)}${Math.abs(100 * k.par30_change_7d).toFixed(2)} pts vs last week`, k.par30_change_7d > 0 ? "bad" : "good"],
      ["PAR90", pct(k.par90, 2), `${up(k.par90_change_7d)}${Math.abs(100 * k.par90_change_7d).toFixed(2)} pts vs last week`, k.par90_change_7d > 0 ? "bad" : "good"],
      ["Predicted late, next 7 days", rs(k.expected_late_7d), `of ${rs(k.due_next_7d)} falling due`, ""],
    ];
    $("kpis").innerHTML = kpis.map(([l, v, s, c]) =>
      `<div class="kpi"><div class="label">${esc(l)}</div><div class="value">${v}</div><div class="delta ${c}">${esc(s)}</div></div>`).join("");

    // PAR trend
    new Chart($("par-chart"), {
      type: "line",
      data: {
        labels: d.history.map((h) => h.date.slice(5)),
        datasets: [
          { label: "PAR30", data: d.history.map((h) => 100 * h.par30), borderColor: css("--c1"), backgroundColor: css("--c1"), pointRadius: 0, borderWidth: 2, tension: 0.2 },
          { label: "PAR90", data: d.history.map((h) => 100 * h.par90), borderColor: css("--c2"), backgroundColor: css("--c2"), pointRadius: 0, borderWidth: 2, tension: 0.2 },
        ],
      },
      options: baseOptions({ plugins: { legend: { labels: { color: css("--muted"), boxWidth: 12, usePointStyle: true } },
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.y.toFixed(2)}%` } } },
        scales: { x: { grid: { display: false }, ticks: { color: css("--muted"), maxTicksLimit: 7, maxRotation: 0 } },
          y: { grid: { color: css("--grid") }, ticks: { color: css("--muted"), callback: (v) => v + "%" }, beginAtZero: true } } }),
    });

    // Cash
    new Chart($("cash-chart"), {
      data: {
        labels: d.collections.map((c) => c.day.slice(5)),
        datasets: [
          { type: "bar", label: "Collected", data: d.collections.map((c) => c.collected / 1e6), backgroundColor: css("--c1"), borderRadius: 2 },
          { type: "line", label: "Falling due", data: d.collections.map((c) => c.due / 1e6), borderColor: css("--c3"), backgroundColor: css("--c3"), pointRadius: 0, borderWidth: 1.5, borderDash: [4, 3] },
        ],
      },
      options: baseOptions({ plugins: { legend: { labels: { color: css("--muted"), boxWidth: 12, usePointStyle: true } },
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: Rs ${c.parsed.y.toFixed(2)}m` } } },
        scales: { x: { grid: { display: false }, ticks: { color: css("--muted"), maxTicksLimit: 8, maxRotation: 0 } },
          y: { grid: { color: css("--grid") }, ticks: { color: css("--muted"), callback: (v) => "Rs " + v + "m" }, beginAtZero: true } } }),
    });

    // Partners
    const maxRate = Math.max(0.3, ...d.partners.map((p) => Math.max(p.recent_late_rate, p.baseline_late_rate)));
    table($("partners"), ["Status", "Employer", "Loans", "Receivable", "PAR30", "Late: recent vs normal"],
      d.partners.map((p) => [
        `<span class="pill ${esc(p.status)}">${esc(p.status)}</span>`,
        `${esc(p.sector)} <span class="note">${esc(p.partner_id)} · ${esc(p.city)}</span>`, num(p.active_loans), rs(p.outstanding), pct(p.par30),
        `<span class="bars" title="recent ${pct(p.recent_late_rate, 0)} · normal ${pct(p.baseline_late_rate, 0)}">` +
          `<i class="now ${p.status === "Alert" ? "hot" : ""}" style="width:${(100 * p.recent_late_rate / maxRate).toFixed(0)}%"></i>` +
          `<i style="width:${(100 * p.baseline_late_rate / maxRate).toFixed(0)}%"></i></span> ` +
          `<b>${pct(p.recent_late_rate, 0)}</b> <span class="note">vs ${pct(p.baseline_late_rate, 0)}</span>`,
      ]), [2, 3, 4]);

    // Buckets
    const active = d.buckets.filter((b) => !["Closed", "Written off"].includes(b.bucket));
    new Chart($("bucket-chart"), {
      type: "bar",
      data: { labels: active.map((b) => b.bucket === "Current" ? "Current" : b.bucket + " days"),
        datasets: [{ data: active.map((b) => b.outstanding / 1e6), backgroundColor: active.map((b, i) => i === 0 ? css("--c1") : i === 1 ? css("--c3") : css("--c2")), borderRadius: 3 }] },
      options: baseOptions({ indexAxis: "y", plugins: { legend: { display: false },
        tooltip: { callbacks: { label: (c) => `Rs ${c.parsed.x.toFixed(1)}m · ${num(active[c.dataIndex].loans)} loans` } } },
        scales: { x: { grid: { color: css("--grid") }, ticks: { color: css("--muted"), callback: (v) => "Rs " + v + "m" } }, y: { grid: { display: false }, ticks: { color: css("--muted") } } } }),
    });
    const wo = d.buckets.find((b) => b.bucket === "Written off");
    if (wo) $("writeoff").textContent = `Written off (over ${m.write_off_dpd} days past due): ${num(wo.loans)} loans, ${rs(wo.outstanding)}.`;

    // Roll matrix
    const heat = (v) => `background: color-mix(in srgb, ${css("--accent")} ${Math.round(v * 70)}%, transparent)`;
    table($("roll"), ["From \\ To", ...d.roll.to],
      d.roll.from.map((f, i) => [`<b>${esc(f)}</b>`, ...d.roll.share[i].map((v) => v > 0 ? `<span style="${heat(v)};display:block;border-radius:4px;padding:2px 0">${pct(v, 0)}</span>` : "·")]));

    // Recon
    $("recon-summary").innerHTML = d.recon.summary.length
      ? d.recon.summary.map((s) => `<span>${esc(s.issue)}: <b>${s.count}</b> · ${rs(s.amount)}</span>`).join("")
      : `<span style="background:var(--good-soft);color:var(--good)">No exceptions in the last 7 days</span>`;
    table($("recon"), ["Date", "Issue", "Reference", "Amount"],
      d.recon.rows.slice(0, 8).map((r) => [esc(r.txn_date.slice(5)), `${esc(r.issue)} <span class="note">${esc(r.channel)}</span>`, `<code>${esc(r.reference)}</code>`, rs(r.amount)]), [3]);

    // Calls
    table($("calls"), ["Agent", "#", "Action", "Loan", "Employer", "DPD", "To collect", "Next due", "Risk"],
      d.calls.top.map((c) => [esc(c.agent), c.rank_for_agent, esc(c.action), `<code>${esc(c.loan_id)}</code>`,
        `${esc(c.sector)} <span class="note">${esc(c.city)}</span>`, c.dpd || "–", rs(c.amount_to_collect), esc(c.next_due || "–"),
        c.action.startsWith("Courtesy") && c.risk !== "" ? pct(Math.min(c.risk, 0.99), 0) : "–"]), [1, 5, 6, 8]);

    // Model
    const md = d.model;
    $("model-stats").innerHTML =
      `<div><b>${md.auc.toFixed(2)}</b><span>AUC on ${num(md.test_size)} unseen instalments (0.5 = guessing)</span></div>` +
      `<div><b>${pct(md.top20_capture, 0)}</b><span>of late instalments are in the riskiest 20%</span></div>` +
      `<div><b>${pct(md.top20_capture_current, 0)}</b><span>same, for borrowers who were up to date (chance would be 20%)</span></div>`;
    const drivers = md.drivers.filter((x) => Math.abs(x.weight) > 0.05);
    // On narrow screens split long labels over two lines so they are not cut off.
    const wrap = (s) => {
      if (window.innerWidth >= 640 || s.length <= 18) return s;
      const mid = s.lastIndexOf(" ", Math.ceil(s.length / 2) + 3);
      return mid > 0 ? [s.slice(0, mid), s.slice(mid + 1)] : s;
    };
    new Chart($("driver-chart"), {
      type: "bar",
      data: { labels: drivers.map((x) => wrap(x.feature)), datasets: [{ data: drivers.map((x) => x.weight), backgroundColor: drivers.map((x) => x.weight > 0 ? css("--c2") : css("--c1")), borderRadius: 3 }] },
      options: baseOptions({ indexAxis: "y", plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `weight ${c.parsed.x.toFixed(2)} (${c.parsed.x > 0 ? "raises" : "lowers"} risk)` } } },
        scales: { x: { grid: { color: css("--grid") }, ticks: { color: css("--muted") }, title: { display: true, text: window.innerWidth < 640 ? "Weight (bigger = more likely late)" : "Standardised weight: bigger = stronger push towards late", color: css("--muted") } },
          y: { grid: { display: false }, ticks: { color: css("--muted"), autoSkip: false, font: { size: window.innerWidth < 640 ? 10 : 12 } } } } }),
    });
  }
})();
