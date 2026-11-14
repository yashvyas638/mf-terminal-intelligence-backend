import subprocess
import textwrap


def test_research_account_switch_discards_late_a_b_a_responses():
    """Run the real Research client against delayed, identity-tagged API responses."""
    script = r"""
    const fs = require("node:fs");
    const vm = require("node:vm");
    const source = fs.readFileSync("app/static/research.js", "utf8");
    const elements = new Map();

    function element(id) {
      if (!elements.has(id)) {
        const value = {
          id, value: "", innerHTML: "", textContent: "", hidden: false,
          disabled: false, options: [], dataset: {}, style: {},
          classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
          addEventListener() {}, setAttribute() {}, appendChild() {},
          add(option) { this.options.push(option); },
          scrollIntoView() {},
        };
        elements.set(id, value);
      }
      return elements.get(id);
    }

    const document = {
      getElementById: element,
      querySelectorAll() { return []; },
      createElement() { return element("created-" + Math.random()); },
    };
    const pendingA1 = [];

    function payload(url, token) {
      const identity = token === "Bearer token-a-new"
        ? "A-NEW"
        : token === "Bearer token-b"
          ? "B"
          : "A-OLD";
      if (url.includes("/v1/nav/facets")) {
        return {
          categories: [identity + "-CATEGORY"],
          sub_categories: [], asset_classes: [], plan_types: [], option_types: [],
        };
      }
      if (url.includes("/v1/watchlist")) {
        return {
          items: [{
            scheme_code: identity === "A-NEW" ? 71003 : identity === "B" ? 71002 : 71001,
            scheme_name: identity + "-PRIVATE-FUND",
            plan_type: "Direct Plan", option_type: "Growth Option",
            latest_nav: "100", nav_date: "2026-11-13", added_at: "2026-11-14",
          }],
        };
      }
      if (url.includes("/v1/analytics/screener")) {
        return {
          items: [], total_matching: 0, refreshed_at: "2026-11-14T10:00:00Z",
          days_requested: 30, sort_by: "monthly_return",
        };
      }
      if (url.includes("/v1/analytics/monthly-leaderboard")) {
        return { items: [], count: 0, plan_type: "Direct", option_type: "Growth" };
      }
      return {};
    }

    function response(data) {
      return { ok: true, status: 200, json: async () => data };
    }

    const fetch = (url, options = {}) => {
      const token = options.headers?.Authorization || "";
      if (token === "Bearer token-a-old") {
        return new Promise(resolve => pendingA1.push({ url, token, resolve }));
      }
      return Promise.resolve(response(payload(url, token)));
    };

    const authClient = {
      auth: {
        getSession: () => new Promise(() => {}),
        onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
      },
    };
    const context = {
      document,
      window: {
        supabase: { createClient: () => authClient },
        location: { origin: "https://example.test" },
        renderFundDetail: async () => ({}),
      },
      fetch, URL, URLSearchParams, AbortController, setTimeout, clearTimeout,
      Option: function Option(label, value) { this.label = label; this.value = value; },
      console, Date, Map, Promise, Number, String, Math, JSON, Object, Array, Error,
      __sessions: {
        a1: { access_token: "token-a-old", user: { id: "user-a" } },
        b: { access_token: "token-b", user: { id: "user-b" } },
        a2: { access_token: "token-a-new", user: { id: "user-a" } },
      },
    };

    vm.runInNewContext(source, context, { filename: "research.js" });

    (async () => {
      const a1 = vm.runInNewContext("updateAuthState(__sessions.a1)", context);
      if (pendingA1.length !== 2) throw new Error("Expected the first account's facets and watchlist requests.");

      const b = vm.runInNewContext("updateAuthState(__sessions.b)", context);
      const a2 = vm.runInNewContext("updateAuthState(__sessions.a2)", context);
      await Promise.all([b, a2]);

      if (!element("watchlistRows").innerHTML.includes("A-NEW-PRIVATE-FUND")) {
        throw new Error("The latest user-A watchlist was not rendered.");
      }
      if (!element("category").innerHTML.includes("A-NEW-CATEGORY")) {
        throw new Error("The latest user-A facets were not rendered.");
      }

      for (const request of pendingA1) {
        request.resolve(response(payload(request.url, request.token)));
      }
      await a1;

      const watchlist = element("watchlistRows").innerHTML;
      const facets = element("category").innerHTML;
      if (!watchlist.includes("A-NEW-PRIVATE-FUND") || watchlist.includes("A-OLD-PRIVATE-FUND")) {
        throw new Error("A late response from the first user-A session overwrote the current watchlist.");
      }
      if (!facets.includes("A-NEW-CATEGORY") || facets.includes("A-OLD-CATEGORY")) {
        throw new Error("A late response from the first user-A session overwrote the current facets.");
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
