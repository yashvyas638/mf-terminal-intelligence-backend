/* Detailed fund profile renderer. The auth, API, screener and watchlist
   controllers remain owned by research.js; this file does not replace them. */
function navLineChart(points) {
  if (!points || points.length < 2) {
    return '<p class="muted">Not enough stored NAV observations for a history chart. The available profile metrics are still shown.</p>';
  }
  const values = points.map(point => Number(point.nav));
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
  const width = 720, height = 210, pad = 24;
  const coordinates = values.map((value, index) => {
    const x = pad + index * (width - 2 * pad) / (values.length - 1);
    const y = height - pad - ((value - min) / span) * (height - 2 * pad);
    return x.toFixed(1) + "," + y.toFixed(1);
  }).join(" ");
  return '<div class="chart"><svg viewBox="0 0 720 220" role="img" aria-label="Stored NAV history line chart">' +
    '<polyline points="' + coordinates + '" fill="none" stroke="#2563bd" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>' +
    '<text x="18" y="18" fill="#687585" font-size="12">NAV history · ' + points.length + ' observations</text>' +
    '<text x="18" y="210" fill="#687585" font-size="11">' + esc(points[0].date) + '</text>' +
    '<text x="702" y="210" text-anchor="end" fill="#687585" font-size="11">' + esc(points[points.length - 1].date) + '</text></svg></div>';
}

function evidencePackPanel(result) {
  if (!result || result.generation_status !== "EVIDENCE_ONLY_NO_LLM_GENERATION") {
    return '<div class="panel"><h3>Source evidence pack</h3><p class="muted">Evidence pack unavailable: ' + esc(result?.message || "request failed") + '</p></div>';
  }
  const sourceById = Object.fromEntries((result.sources || []).map(source => [source.source_id, source]));
  const items = (result.evidence || []).map(item => {
    const source = sourceById[item.source_id];
    return '<div class="metricrow"><div><strong>' + esc(item.claim) + '</strong><div class="muted">' + esc(item.evidence_type) + (source ? ' · ' + esc(source.title) : '') + '</div><div class="muted">' + esc(typeof item.value === "object" ? JSON.stringify(item.value) : item.value) + '</div></div></div>';
  }).join("") || '<p class="muted">No source-backed evidence is available in the selected period.</p>';
  const sources = (result.sources || []).map(source =>
    '<li><a href="' + esc(source.url) + '" target="_blank" rel="noopener noreferrer">' + esc(source.title) + '</a> · ' + esc(source.source_type) + (source.as_of_date || source.effective_nav_date ? ' · As of ' + esc(source.as_of_date || source.effective_nav_date) : '') + '</li>'
  ).join("") || '<li class="muted">No source documents attached.</li>';
  const gaps = (result.data_gaps || []).map(gap => '<li>' + esc(gap) + '</li>').join("");
  return '<div class="panel"><div class="detailhead"><h3>Source evidence pack</h3><span class="tag">Evidence only · No AI claims generated</span></div><div class="metriclist">' + items + '</div><h4>Sources</h4><ul>' + sources + '</ul>' + (gaps ? '<h4>Data gaps</h4><ul>' + gaps + '</ul>' : '') + '<p class="footnote">Generated ' + esc(result.generated_at) + '. Any downstream AI summary must preserve these source references and distinguish source facts from derived calculations.</p></div>';
}

function benchmarkComparisonPanel(result) {
  if (!result || result.status === "UNMAPPED") {
    return '<div class="panel"><h3>Benchmark TRI comparison</h3><p class="muted">No verified active benchmark mapping is available for this scheme. The system will not guess a benchmark from the fund category.</p></div>';
  }
  const comparisons = result.comparisons || [];
  if (!comparisons.length) {
    return '<div class="panel"><h3>Benchmark TRI comparison</h3><p class="muted">No benchmark comparison data is currently available.</p></div>';
  }
  return '<div class="panel"><h3>Benchmark TRI comparison</h3><p class="footnote">Only verified, effective-dated benchmark assignments are shown. Fund NAV and TRI are matched on exact common dates; no forward-fill or interpolation.</p>' +
    comparisons.map(item => {
      const metric = item.metrics || {};
      const insufficient = metric.status !== "OK";
      return '<div class="metriclist" style="margin-top:12px"><div class="detailhead"><div><strong>Tier ' + esc(item.tier) + ' · ' + esc(item.benchmark_name) + '</strong><div class="muted">' + esc(item.provider) + ' · ' + esc(item.variant) + ' · ' + (metric.common_observations || 0) + ' common observations</div></div><span class="tag">' + (insufficient ? 'Insufficient aligned data' : 'Aligned comparison') + '</span></div>' +
        (insufficient ? '<p class="muted">More overlapping NAV and TRI observations are needed before returns can be compared.</p>' :
          '<div class="stats" style="margin-top:10px">' +
            '<div class="stat"><label>Fund CAGR</label><strong>' + pct(metric.fund_cagr) + '</strong></div>' +
            '<div class="stat"><label>Benchmark CAGR</label><strong>' + pct(metric.benchmark_cagr) + '</strong></div>' +
            '<div class="stat"><label>Excess total return</label><strong>' + pct(metric.active_total_return_percentage_points) + '</strong></div>' +
            '<div class="stat"><label>Relative wealth return</label><strong>' + pct(metric.relative_wealth_return) + '</strong></div>' +
          '</div>' +
          '<div class="metriclist"><div class="metricrow"><span>Alpha (annualised)</span><strong>' + pct(metric.alpha_annualized) + '</strong></div>' +
          '<div class="metricrow"><span>Beta</span><strong>' + num(metric.beta) + '</strong></div>' +
          '<div class="metricrow"><span>Tracking error</span><strong>' + pct(metric.tracking_error) + '</strong></div>' +
          '<div class="metricrow"><span>Information ratio</span><strong>' + num(metric.information_ratio) + '</strong></div></div>') +
        '<p class="footnote">Mapping evidence: <a href="' + esc(item.source_document_url) + '" target="_blank" rel="noopener noreferrer">source document</a> · SHA-256 ' + esc(item.source_document_sha256) + '</p></div>';
    }).join("") +
    '<p class="footnote">' + (result.limitations || []).map(esc).join(" ") + '</p></div>';
}

window.renderFundDetail = async function(code, days) {
  const [research, history, benchmark, evidence] = await Promise.all([
    api("/v1/analytics/research/" + encodeURIComponent(code) + "?days=" + days),
    api("/v1/nav/history/" + encodeURIComponent(code) + "?days=" + days).catch(error => ({ items: [], status: "UNAVAILABLE", message: error.message })),
    api("/v1/analytics/research/" + encodeURIComponent(code) + "/benchmark?days=" + days).catch(error => ({
      status: "UNAVAILABLE",
      message: error.message
    })),
    api("/v1/analytics/research/" + encodeURIComponent(code) + "/evidence?days=" + days).catch(error => ({
      status: "UNAVAILABLE",
      message: error.message
    }))
  ]);
  const metrics = research.metrics || {};
  const scheme = research.scheme || {};
  const rolling1y = metrics.rolling_1y || {};
  const rolling3y = metrics.rolling_3y || {};
  const monthly = metrics.monthly_returns || [];
  const snapshotMetrics = [
    ["CAGR", pct(metrics.cagr)],
    ["Total NAV return", pct(metrics.total_return)],
    ["Annualised volatility", pct(metrics.annualized_volatility)],
    ["Maximum drawdown", pct(metrics.max_drawdown)],
    ["Sharpe ratio", num(metrics.sharpe_ratio)],
    ["Sortino ratio", num(metrics.sortino_ratio)],
    ["Downside deviation", pct(metrics.downside_deviation)],
    ["Positive months", pct(metrics.positive_month_rate)],
    ["Positive 1Y rolling windows", pct(rolling1y.positive_window_rate)],
    ["NAV observations", String(research.coverage.observations ?? 0)]
  ];
  const monthlyBars = monthly.slice(-24);
  const scale = Math.max(0.02, ...monthlyBars.map(item => Math.abs(item.return || 0)));
  const monthlyChart = monthlyBars.length
    ? '<div class="chart"><svg viewBox="0 0 720 220" role="img" aria-label="Monthly NAV return bars">' +
      monthlyBars.map((item, index) => {
        const width = 680 / monthlyBars.length;
        const height = Math.abs(item.return || 0) / scale * 82;
        const y = (item.return || 0) >= 0 ? 104 - height : 104;
        return '<rect x="' + (20 + index * width) + '" y="' + y + '" width="' + Math.max(4, width - 3) + '" height="' + Math.max(1, height) + '" rx="2" fill="' + ((item.return || 0) >= 0 ? "#26966b" : "#cf6258") + '"><title>' + esc(item.month) + ': ' + pct(item.return) + '</title></rect>';
      }).join("") +
      '<line x1="12" y1="104" x2="708" y2="104" stroke="#aeb8c4"/><text x="14" y="18" fill="#687585" font-size="12">Monthly NAV return · latest ' + monthlyBars.length + ' observations</text></svg></div>'
    : '<p class="muted">Monthly return chart unavailable: insufficient dated NAV observations.</p>';
  const rollingRows = data => (data.items || []).slice(-12).map(item =>
    '<tr><td style="text-align:left">' + esc(item.start_date) + '</td><td>' + esc(item.end_date) + '</td><td>' + pct(item.total_return) + '</td><td>' + pct(item.annualized_return) + '</td></tr>'
  ).join("") || '<tr><td colspan="4" class="muted">No complete rolling windows in this period.</td></tr>';
  const coverageText = (research.coverage.observations || 0) < 2
    ? "Only " + (research.coverage.observations || 0) + " stored NAV observation(s) are available. Metrics are withheld until sufficient dated data exists."
    : "Metrics use " + research.coverage.observations + " actual stored NAV observations.";
  $("profileBody").innerHTML =
    '<div class="detailhead"><div><h2>' + esc(scheme.scheme_name || "Fund") + '</h2>' +
    '<div class="muted">AMFI scheme code ' + esc(scheme.scheme_code) + ' · Growth ISIN ' + esc(scheme.isin_growth || "Unavailable") +
    ' · IDCW reinvestment ISIN ' + esc(scheme.isin_dividend_reinvestment || "Unavailable") + '</div>' +
    '<div><span class="tag">' + esc(scheme.amc || "AMC unavailable") + '</span><span class="tag">' + esc(scheme.structure || "Structure unavailable") + '</span>' +
    '<span class="tag">' + esc(scheme.plan_type || "Plan unavailable") + '</span><span class="tag">' + esc(scheme.option_type || "Option unavailable") + '</span>' +
    '<span class="tag">' + esc(scheme.category || "Category unavailable") + '</span></div>' +
    '<p class="muted">Latest NAV ₹' + esc(research.latest_nav || "—") + ' · NAV date ' + esc(research.latest_nav_date || "—") +
    ' · Coverage ' + esc(research.coverage.start_date || "—") + ' to ' + esc(research.coverage.end_date || "—") + '</p></div>' +
    '<div><button type="button" id="addProfileWatchlist" class="view-fund">+ Add to watchlist</button><div style="margin-top:8px"><button type="button" id="backToScreener">← Back to screener</button></div></div></div>' +
    '<div class="notice">' + esc(coverageText) + '</div>' +
    '<h3>Performance snapshot</h3><div class="stats">' + snapshotMetrics.slice(0, 4).map(item => '<div class="stat"><label>' + item[0] + '</label><strong>' + item[1] + '</strong></div>').join("") + '</div>' +
    '<div class="twocol" style="margin-top:15px"><div class="panel"><h3>NAV history</h3>' + navLineChart(history.items || []) + '<p class="footnote">' + (history.status === "UNAVAILABLE" ? 'NAV history unavailable: ' + esc(history.message || "unknown error") + '. ' : '') + 'Source: stored AMFI NAV observations. No interpolation is applied.</p></div>' +
    '<div class="panel"><h3>Monthly return trend</h3>' + monthlyChart + '</div></div>' +
    '<div class="panel"><h3>Risk & consistency</h3><div class="metriclist">' + snapshotMetrics.slice(4).map(item => '<div class="metricrow"><span>' + item[0] + '</span><strong>' + item[1] + '</strong></div>').join("") + '</div></div>' +
    '<div class="panel"><h3>Rolling 1Y returns</h3><div class="muted">Windows: ' + (rolling1y.observations ?? 0) + ' · Positive: ' + (rolling1y.positive_windows ?? 0) + ' · Negative/zero: ' + (rolling1y.negative_or_zero_windows ?? 0) + '</div>' +
    '<div class="tablewrap"><table style="min-width:500px"><thead><tr><th>Start</th><th>End</th><th>Total return</th><th>Annualised</th></tr></thead><tbody>' + rollingRows(rolling1y) + '</tbody></table></div></div>' +
    '<div class="panel"><h3>Rolling 3Y returns</h3><div class="muted">Windows: ' + (rolling3y.observations ?? 0) + ' · Positive: ' + (rolling3y.positive_windows ?? 0) + ' · Negative/zero: ' + (rolling3y.negative_or_zero_windows ?? 0) + '</div>' +
    '<div class="tablewrap"><table style="min-width:500px"><thead><tr><th>Start</th><th>End</th><th>Total return</th><th>Annualised</th></tr></thead><tbody>' + rollingRows(rolling3y) + '</tbody></table></div></div>' +
    benchmarkComparisonPanel(benchmark) +
    evidencePackPanel(evidence) +
    '<div class="notice">Data limitations: ' + (research.data_limitations || []).map(esc).join(" ") + ' AMC, category, AUM, expense ratio, holdings and manager history are not supplied by the current AMFI NAV source.</div>';
  $("addProfileWatchlist").onclick = () => addToWatchlist(Number(scheme.scheme_code)).catch(error => note(error.message, true));
  $("backToScreener").onclick = () => activate("screener");
};
