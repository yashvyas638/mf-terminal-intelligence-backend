/* Fund detail experience: explicit selection, reliable loading and transparent empty states. */
api = async function(path) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20000);
  let response;
  try {
    response = await fetch(path, { headers: headers(), signal: controller.signal });
  } catch (error) {
    if (error.name === "AbortError") throw new Error("The request timed out. Please retry; the fund data has not been changed.");
    throw new Error("Could not reach the research API: " + error.message);
  } finally {
    clearTimeout(timeout);
  }
  const data = await response.json().catch(() => ({ detail: response.statusText }));
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || "Request failed (" + response.status + ")"));
  return data;
};

function renderRows() {
  const sorted = [...items].sort((a, b) => {
    const x = a[sortKey], y = b[sortKey];
    if (x == null && y == null) return 0;
    if (x == null) return 1;
    if (y == null) return -1;
    return (typeof x === "string" ? x.localeCompare(y) : x - y) * sortDir;
  });
  $("fundRows").innerHTML = sorted.map(x =>
    '<tr data-code="' + esc(x.scheme_code) + '">' +
      '<td><div class="fund">' + esc(x.scheme_name) + '</div><div class="subfund">Code ' + esc(x.scheme_code) + ' · ' + esc(x.plan_type || "Plan unavailable") + ' · ' + esc(x.option_type || "Option unavailable") + '</div></td>' +
      '<td>₹' + (x.latest_nav ? num(x.latest_nav) : "—") + '<div class="subfund">' + esc(x.nav_date || "No NAV") + '</div></td>' +
      '<td>' + pct(x.return_1m) + '</td><td class="' + (x.return_1y == null ? "" : x.return_1y >= 0 ? "positive" : "negative") + '">' + pct(x.return_1y) + '</td>' +
      '<td class="' + (x.return_3y == null ? "" : x.return_3y >= 0 ? "positive" : "negative") + '">' + pct(x.return_3y) + '</td>' +
      '<td>' + pct(x.volatility) + '</td><td>' + num(x.sharpe_ratio) + '</td><td>' + num(x.sortino_ratio) + '</td>' +
      '<td class="negative">' + pct(x.max_drawdown) + '</td><td>' + pct(x.positive_month_rate) + '</td>' +
      '<td><button type="button" class="view-fund" data-view-code="' + esc(x.scheme_code) + '">View details →</button></td></tr>'
  ).join("") || '<tr><td colspan="11" class="muted">No funds match these filters. Try clearing plan/option filters or check whether NAV ingestion has completed.</td></tr>';

  document.querySelectorAll(".view-fund").forEach(button => {
    button.addEventListener("click", () => openFundProfile(button.dataset.viewCode));
  });
  document.querySelectorAll("#fundRows tr[data-code]").forEach(row => {
    row.addEventListener("dblclick", () => openFundProfile(row.dataset.code));
  });
}

async function openFundProfile(code) {
  activate("profile");
  $("profileCode").value = String(code);
  $("profileBody").innerHTML = '<div class="panel"><strong>Loading fund details…</strong><p class="muted">Fetching scheme metadata, NAV history and research metrics.</p></div>';
  $("profileBody").scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    await loadProfile();
  } catch (error) {
    $("profileBody").innerHTML = '<div class="notice error">' + esc(error.message) + '</div>';
    note(error.message, true);
  }
}

function navLineChart(points) {
  if (!points || points.length < 2) return '<p class="muted">Not enough stored NAV observations to draw a history chart. The fund profile and available metadata are still shown.</p>';
  const values = points.map(p => Number(p.nav));
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
  const width = 720, height = 210, pad = 24;
  const coords = values.map((v, i) => {
    const x = pad + i * (width - 2 * pad) / (values.length - 1);
    const y = height - pad - ((v - min) / span) * (height - 2 * pad);
    return x.toFixed(1) + "," + y.toFixed(1);
  }).join(" ");
  return '<div class="chart"><svg viewBox="0 0 720 220" role="img" aria-label="Stored NAV history line chart">' +
    '<polyline points="' + coords + '" fill="none" stroke="#2563bd" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>' +
    '<text x="18" y="18" fill="#687585" font-size="12">NAV history · ' + points.length + ' observations</text>' +
    '<text x="18" y="210" fill="#687585" font-size="11">' + esc(points[0].date) + '</text>' +
    '<text x="702" y="210" text-anchor="end" fill="#687585" font-size="11">' + esc(points[points.length - 1].date) + '</text></svg></div>';
}

loadProfile = async function() {
  const code = $("profileCode").value.trim();
  if (!/^\d+$/.test(code)) throw new Error("Enter a valid numeric scheme code.");
  if (key.length < 32) throw new Error("Connect with the server API key before opening fund details.");
  const days = $("profileDays").value;
  const [d, history] = await Promise.all([
    api("/v1/analytics/research/" + encodeURIComponent(code) + "?days=" + days),
    api("/v1/nav/history/" + encodeURIComponent(code) + "?days=" + days)
  ]);
  const m = d.metrics || {}, s = d.scheme || {}, roll = m.rolling_1y || {}, roll3 = m.rolling_3y || {};
  const months = m.monthly_returns || [];
  const metrics = [
    ["CAGR", pct(m.cagr)], ["Total NAV return", pct(m.total_return)],
    ["Annualised volatility", pct(m.annualized_volatility)], ["Maximum drawdown", pct(m.max_drawdown)],
    ["Sharpe ratio", num(m.sharpe_ratio)], ["Sortino ratio", num(m.sortino_ratio)],
    ["Downside deviation", pct(m.downside_deviation)], ["Positive months", pct(m.positive_month_rate)],
    ["Positive 1Y rolling windows", pct(roll.positive_window_rate)], ["NAV observations", String(d.coverage.observations ?? 0)]
  ];
  const bars = months.slice(-24);
  const scale = Math.max(0.02, ...bars.map(x => Math.abs(x.return || 0)));
  const monthlyChart = bars.length
    ? '<div class="chart"><svg viewBox="0 0 720 220" role="img" aria-label="Monthly NAV return bars">' +
      bars.map((x, i) => { const w = 680 / bars.length, h = Math.abs(x.return || 0) / scale * 82, y = (x.return || 0) >= 0 ? 104 - h : 104; return '<rect x="' + (20 + i * w) + '" y="' + y + '" width="' + Math.max(4, w - 3) + '" height="' + Math.max(1, h) + '" rx="2" fill="' + ((x.return || 0) >= 0 ? "#26966b" : "#cf6258") + '"><title>' + esc(x.month) + ': ' + pct(x.return) + '</title></rect>'; }).join("") +
      '<line x1="12" y1="104" x2="708" y2="104" stroke="#aeb8c4"/><text x="14" y="18" fill="#687585" font-size="12">Monthly NAV return · latest ' + bars.length + ' observations</text></svg></div>'
    : '<p class="muted">Monthly return chart unavailable: insufficient dated NAV observations.</p>';
  const rollingTable = (data) => (data.items || []).slice(-12).map(x =>
    '<tr><td style="text-align:left">' + esc(x.start_date) + '</td><td>' + esc(x.end_date) + '</td><td>' + pct(x.total_return) + '</td><td>' + pct(x.annualized_return) + '</td></tr>'
  ).join("") || '<tr><td colspan="4" class="muted">No complete rolling windows in the selected period.</td></tr>';
  const dataStatus = (d.coverage.observations || 0) < 2
    ? "Only " + (d.coverage.observations || 0) + " stored NAV observation(s) are available in this period. Performance and risk metrics need multiple dated NAV observations; they are intentionally not fabricated."
    : "Metrics are calculated from " + d.coverage.observations + " actual stored NAV observations.";
  $("profileBody").innerHTML =
    '<div class="detailhead"><div><h2>' + esc(s.scheme_name || "Fund") + '</h2>' +
    '<div class="muted">AMFI scheme code ' + esc(s.scheme_code) + ' · Growth ISIN ' + esc(s.isin_growth || "Unavailable") +
    ' · IDCW reinvestment ISIN ' + esc(s.isin_dividend_reinvestment || "Unavailable") + '</div>' +
    '<div><span class="tag">' + esc(s.amc || "AMC unavailable") + '</span><span class="tag">' + esc(s.structure || "Structure unavailable") + '</span>' +
    '<span class="tag">' + esc(s.plan_type || "Plan unavailable") + '</span><span class="tag">' + esc(s.option_type || "Option unavailable") + '</span>' +
    '<span class="tag">' + esc(s.category || "Category unavailable") + '</span></div>' +
    '<p class="muted">Latest NAV ₹' + esc(d.latest_nav || "—") + ' · NAV date ' + esc(d.latest_nav_date || "—") +
    ' · Data coverage ' + esc(d.coverage.start_date || "—") + ' to ' + esc(d.coverage.end_date || "—") + '</p></div>' +
    '<button type="button" id="backToScreener">← Back to screener</button></div>' +
    '<div class="notice">' + esc(dataStatus) + '</div>' +
    '<h3>Performance snapshot</h3><div class="stats">' + metrics.slice(0, 4).map(x => '<div class="stat"><label>' + x[0] + '</label><strong>' + x[1] + '</strong></div>').join("") + '</div>' +
    '<div class="twocol" style="margin-top:15px"><div class="panel"><h3>NAV history</h3>' + navLineChart(history.items || []) + '<p class="footnote">Source: stored AMFI NAV observations. No interpolation is applied.</p></div>' +
    '<div class="panel"><h3>Monthly return trend</h3>' + monthlyChart + '</div></div>' +
    '<div class="panel"><h3>Risk & consistency</h3><div class="metriclist">' + metrics.slice(4).map(x => '<div class="metricrow"><span>' + x[0] + '</span><strong>' + x[1] + '</strong></div>').join("") + '</div></div>' +
    '<div class="panel"><h3>Rolling 1Y returns</h3><div class="muted">Windows: ' + (roll.observations ?? 0) + ' · Positive: ' + (roll.positive_windows ?? 0) + ' · Negative/zero: ' + (roll.negative_or_zero_windows ?? 0) + '</div>' +
    '<div class="tablewrap"><table style="min-width:500px"><thead><tr><th>Start</th><th>End</th><th>Total return</th><th>Annualised</th></tr></thead><tbody>' + rollingTable(roll) + '</tbody></table></div></div>' +
    '<div class="panel"><h3>Rolling 3Y returns</h3><div class="muted">Windows: ' + (roll3.observations ?? 0) + ' · Positive: ' + (roll3.positive_windows ?? 0) + ' · Negative/zero: ' + (roll3.negative_or_zero_windows ?? 0) + '</div>' +
    '<div class="tablewrap"><table style="min-width:500px"><thead><tr><th>Start</th><th>End</th><th>Total return</th><th>Annualised</th></tr></thead><tbody>' + rollingTable(roll3) + '</tbody></table></div></div>' +
    '<div class="notice">Data limitations: ' + (d.data_limitations || []).map(esc).join(" ") + ' AMC, category, AUM, expense ratio, holdings and manager history are not supplied by the current AMFI NAV source.</div>';
  $("backToScreener").onclick = () => activate("screener");
};
