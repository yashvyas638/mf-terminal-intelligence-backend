import subprocess
import textwrap


def test_portfolio_detail_responses_are_bound_to_the_authenticated_account():
    """A late report-history response must not cross an A-to-B account switch."""
    script = r"""
    const fs = require("node:fs");
    const vm = require("node:vm");
    const source = fs.readFileSync("app/static/dashboard.js", "utf8");

    function extractFunction(signature) {
      const start = source.indexOf(signature);
      if (start < 0) throw new Error("Missing production function: " + signature);
      const open = source.indexOf("{", start);
      let depth = 0, quote = null, escaped = false;
      for (let i = open; i < source.length; i++) {
        const ch = source[i];
        if (quote) {
          if (escaped) escaped = false;
          else if (ch === "\\") escaped = true;
          else if (ch === quote) quote = null;
          continue;
        }
        if (ch === "'" || ch === '"' || ch === String.fromCharCode(96)) { quote = ch; continue; }
        if (ch === "{") depth++;
        else if (ch === "}" && --depth === 0) return source.slice(start, i + 1);
      }
      throw new Error("Unclosed production function: " + signature);
    }

    const guard = extractFunction("function isCurrentPortfolioRequest(");
    const loader = extractFunction("async function loadPortfolioReports()");
    const reset = extractFunction("function resetPrivatePortfolioWorkspace()");
    const elements = new Map();
    function $(id) {
      if (!elements.has(id)) {
        elements.set(id, {
          id, value: "77", innerHTML: "PRIVATE-USER-A", textContent: "PRIVATE-USER-A",
          disabled: false,
        });
      }
      return elements.get(id);
    }

    let resolveOld;
    const context = {
      portfolioViewRequest: 8,
      authWorkspaceRequest: 21,
      portfolioId: () => "77",
      $,
      api: () => new Promise(resolve => { resolveOld = resolve; }),
      document: { querySelectorAll() { return []; } },
      escapeHtml: String,
      pendingImportCsv: "old csv",
      pendingImportToken: "old token",
      pendingImportPortfolioId: "77",
      loadedAuthUserId: "user-a",
      lastPortfolioRisk: { private: true },
      lastPortfolioRiskPortfolioId: "77",
      Promise, Number, String, Error,
    };
    vm.createContext(context);
    vm.runInContext(guard + "\n" + loader + "\n" + reset, context);

    (async () => {
      const pending = vm.runInContext("loadPortfolioReports()", context);
      if (typeof resolveOld !== "function") throw new Error("Report-history request did not start.");

      // Keep the same portfolio ID and view generation deliberately. Only identity changes.
      context.authWorkspaceRequest = 22;
      resolveOld({ items: [{ report_id: 9001, generated_at: "2026-11-14", source_max_nav_date: "2026-11-13", content_sha256: "old-user-hash" }] });
      await pending;

      if ($("portfolioReportHistory").innerHTML !== "PRIVATE-USER-A") {
        throw new Error("A late User-A report response mutated the User-B workspace.");
      }
      if (vm.runInContext('isCurrentPortfolioRequest(8, "77", 21)', context) !== false) {
        throw new Error("The portfolio request guard accepted an obsolete account generation.");
      }
      if (vm.runInContext('isCurrentPortfolioRequest(8, "77", 22)', context) !== true) {
        throw new Error("The portfolio request guard rejected the current account generation.");
      }

      vm.runInContext("resetPrivatePortfolioWorkspace()", context);
      if ($("portfolioId").value !== "") throw new Error("Account reset did not clear the selected private portfolio.");
      if ($("portfolioReportHistory").innerHTML.includes("PRIVATE-USER-A")) {
        throw new Error("Account reset did not clear the previous user's report history.");
      }
      if (context.portfolioViewRequest !== 9) throw new Error("Account reset did not invalidate pending portfolio-view requests.");
      if (context.lastPortfolioRisk !== null) throw new Error("Account reset retained prior-user risk data.");
    })().catch(error => {
      console.error(error);
      process.exitCode = 1;
    });
    """
    result = subprocess.run(
        ["node", "-e", textwrap.dedent(script)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
