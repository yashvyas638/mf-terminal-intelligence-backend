const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const test = require("node:test");

function extractHelper(source, multiline = false) {
  const start = source.indexOf("function safeHttpUrl(");
  assert.notEqual(start, -1, "safeHttpUrl helper must exist");
  const end = multiline ? source.indexOf("\n}", start) + 2 : source.indexOf("\n", start);
  assert.ok(end > start, "safeHttpUrl helper must be a complete function");
  return source.slice(start, end);
}

function loadSafeUrl(helper) {
  const context = { URL };
  vm.runInNewContext(helper + "\nthis.safeHttpUrl = safeHttpUrl;", context);
  return context.safeHttpUrl;
}

test("dashboard and fund detail reject unsafe URL schemes", () => {
  const dashboard = fs.readFileSync("app/static/dashboard.js", "utf8");
  const fundDetail = fs.readFileSync("app/static/fund-detail.js", "utf8");
  for (const helper of [extractHelper(dashboard), extractHelper(fundDetail, true)]) {
    const safeHttpUrl = loadSafeUrl(helper);
    assert.equal(safeHttpUrl("javascript:alert(1)"), "");
    assert.equal(safeHttpUrl("data:text/html,<script>alert(1)</script>"), "");
    assert.equal(safeHttpUrl("//attacker.example/path"), "");
    assert.equal(safeHttpUrl("https://amfiindia.com/factsheet.pdf"), "https://amfiindia.com/factsheet.pdf");
    assert.equal(safeHttpUrl("http://example.org/source.pdf"), "http://example.org/source.pdf");
  }
});

test("all source-document links pass through the URL allow-list", () => {
  const dashboard = fs.readFileSync("app/static/dashboard.js", "utf8");
  const fundDetail = fs.readFileSync("app/static/fund-detail.js", "utf8");
  assert.match(dashboard, /safeHttpUrl\(source\.source_document_url\)/);
  assert.match(fundDetail, /safeHttpUrl\(source\.url\)/);
  assert.match(fundDetail, /safeHttpUrl\(item\.source_document_url\)/);
  assert.match(dashboard, /escapeHtml\(m\.start_date\)/);
  assert.match(dashboard, /escapeHtml\(m\.end_date\)/);
});
