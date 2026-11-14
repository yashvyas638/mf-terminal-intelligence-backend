import subprocess
import textwrap


def test_private_portfolio_action_responses_are_discarded_after_account_switch():
    """Stress, report verification and PDF download cannot repaint a newer account."""
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
    const stress = extractFunction("async function runPortfolioStress()");
    const verify = extractFunction("async function verifyPortfolioReport(");
    const download = extractFunction("async function downloadPortfolioReport(");
    const elements = new Map();
    function $(id) {
      if (!elements.has(id)) {
        elements.set(id, {
          id, value: "77", innerHTML: "PRIVATE-USER-A",
          textContent: "PRIVATE-USER-A", className: "",
        });
      }
      return elements.get(id);
    }

    const apiResolvers = [];
    let resolvePdf;
    let createElementCalls = 0;
    const context = {
      portfolioViewRequest: 8,
      authWorkspaceRequest: 1,
      portfolioId: () => "77",
      $,
      lastPortfolioRisk: { holdings: [{ scheme_code: 1001 }] },
      lastPortfolioRiskPortfolioId: "77",
      document: {
        querySelectorAll() { return [{ value: "0", dataset: { schemeCode: "1001" } }]; },
        createElement() { createElementCalls++; return {}; },
        body: { appendChild() {} },
      },
      api: () => new Promise(resolve => apiResolvers.push(resolve)),
      fetch: () => new Promise(resolve => { resolvePdf = resolve; }),
      headers: () => ({}),
      base: "https://example.test",
      Promise, Number, String, Error, Blob,
      URL: { createObjectURL() { return "blob:test"; } },
      setTimeout() {},
    };
    vm.createContext(context);
    vm.runInContext(guard + "\n" + stress + "\n" + verify + "\n" + download, context);

    (async () => {
      const stressPending = vm.runInContext("runPortfolioStress()", context);
      if (apiResolvers.length !== 1) throw new Error("Stress request did not start.");
      context.authWorkspaceRequest = 2;
      apiResolvers.shift()({
        scenario_name: "A-only scenario", base_portfolio_value: 1000,
        estimated_portfolio_impact: -100, stressed_portfolio_value: 900,
        scenario_type: "SYNTHETIC",
      });
      await stressPending;
      if ($("portfolioStressResult").textContent !== "PRIVATE-USER-A") {
        throw new Error("A late stress response repainted the switched workspace.");
      }

      const verifyPending = vm.runInContext('verifyPortfolioReport(901, 2, 8, "77")', context);
      if (apiResolvers.length !== 1) throw new Error("Report verification request did not start.");
      context.authWorkspaceRequest = 3;
      apiResolvers.shift()({ integrity_status: "VERIFIED", content_sha256: "old-account-hash" });
      await verifyPending;
      if ($("portfolioReportResult").textContent !== "PRIVATE-USER-A") {
        throw new Error("A late report verification response repainted the switched workspace.");
      }

      const downloadPending = vm.runInContext('downloadPortfolioReport(901, 3, 8, "77")', context);
      if (typeof resolvePdf !== "function") throw new Error("PDF download request did not start.");
      context.authWorkspaceRequest = 4;
      resolvePdf({ ok: true, blob: async () => new Blob(["synthetic-pdf"]) });
      await downloadPending;
      if (createElementCalls !== 0) {
        throw new Error("A PDF belonging to the prior account was downloaded after the account switch.");
      }
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
