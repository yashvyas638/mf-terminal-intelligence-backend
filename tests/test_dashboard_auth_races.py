import subprocess
import textwrap


def test_dashboard_discards_late_private_workspace_responses_after_a_b_a_switch():
    """Execute the production dashboard loaders with delayed responses from an old session."""
    script = r"""
    const fs = require("node:fs");
    const vm = require("node:vm");
    const source = fs.readFileSync("app/static/dashboard.js", "utf8");

    function extractOneLineFunction(signature) {
      const start = source.indexOf(signature);
      if (start < 0) throw new Error("Missing production function: " + signature);
      const end = source.indexOf("\n", start);
      return source.slice(start, end);
    }

    const loadGoalsSource = extractOneLineFunction("async function loadGoals()");
    const loadPortfoliosSource = extractOneLineFunction("async function loadPortfolios()");
    const elements = new Map();
    function element(id) {
      if (!elements.has(id)) {
        elements.set(id, {
          id, value: "", innerHTML: "", textContent: "", disabled: false,
          classList: { toggle() {}, add() {}, remove() {} },
        });
      }
      return elements.get(id);
    }

    const pendingOld = [];
    let session = { access_token: "token-a-old", user: { id: "user-a" } };
    let authWorkspaceRequest = 1;

    function api(path) {
      const token = session.access_token;
      if (token === "token-a-old") {
        return new Promise(resolve => pendingOld.push({ path, resolve }));
      }
      const identity = token === "token-a-new" ? "A-NEW" : "B";
      if (path === "/v1/goals") {
        return Promise.resolve({ items: [{ name: identity + "-GOAL" }] });
      }
      if (path === "/v1/portfolios") {
        return Promise.resolve({ items: [{ id: identity === "A-NEW" ? 303 : 202, name: identity + "-PORTFOLIO" }] });
      }
      throw new Error("Unexpected API path: " + path);
    }

    const context = {
      session, authWorkspaceRequest,
      api,
      isCurrentAuthWorkspace(requestId, userId) {
        return requestId === authWorkspaceRequest &&
          !!session?.access_token && session.user.id === userId;
      },
      renderGoals(goals) {
        element("goalList").innerHTML = goals.map(goal => goal.name).join(",");
      },
      loadPortfolioCommandCentre: async portfolios => {
        element("ccPortfolioCards").innerHTML = portfolios.map(p => p.name).join(",");
      },
      showError(error) { throw error; },
      escapeHtml(value) { return String(value); },
      $: element,
      Promise, String, Number, Error,
    };

    vm.createContext(context);
    vm.runInContext(loadGoalsSource + "\n" + loadPortfoliosSource, context);

    (async () => {
      const oldGoals = vm.runInContext("loadGoals()", context);
      const oldPortfolios = vm.runInContext("loadPortfolios()", context);
      if (pendingOld.length !== 2) throw new Error("Expected old-session goals and portfolio requests.");

      context.session = { access_token: "token-b", user: { id: "user-b" } };
      context.authWorkspaceRequest = 2;
      await Promise.all([
        vm.runInContext("loadGoals()", context),
        vm.runInContext("loadPortfolios()", context),
      ]);

      context.session = { access_token: "token-a-new", user: { id: "user-a" } };
      context.authWorkspaceRequest = 3;
      await Promise.all([
        vm.runInContext("loadGoals()", context),
        vm.runInContext("loadPortfolios()", context),
      ]);

      if (!element("goalList").innerHTML.includes("A-NEW-GOAL")) {
        throw new Error("The current account's goals were not rendered.");
      }
      if (!element("portfolioSelect").innerHTML.includes("A-NEW-PORTFOLIO")) {
        throw new Error("The current account's portfolio list was not rendered.");
      }

      for (const request of pendingOld) {
        request.resolve(request.path === "/v1/goals"
          ? { items: [{ name: "A-OLD-GOAL" }] }
          : { items: [{ id: 101, name: "A-OLD-PORTFOLIO" }] });
      }
      await Promise.all([oldGoals, oldPortfolios]);

      if (!element("goalList").innerHTML.includes("A-NEW-GOAL") ||
          element("goalList").innerHTML.includes("A-OLD-GOAL")) {
        throw new Error("A late old-session response overwrote the current goals.");
      }
      if (!element("portfolioSelect").innerHTML.includes("A-NEW-PORTFOLIO") ||
          element("portfolioSelect").innerHTML.includes("A-OLD-PORTFOLIO")) {
        throw new Error("A late old-session response overwrote the current portfolio list.");
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
