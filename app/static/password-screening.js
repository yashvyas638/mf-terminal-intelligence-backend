(function(root){
  "use strict";

  async function screenPasswordAgainstBreachCorpus(password, options = {}) {
    if (typeof password !== "string" || password.length === 0) {
      throw new Error("Enter a password before screening it.");
    }

    const cryptoApi = options.crypto || root.crypto;
    const fetchImpl = options.fetch || (root.fetch && root.fetch.bind(root));
    const AbortControllerImpl = root.AbortController || globalThis.AbortController;
    if (!cryptoApi?.subtle || typeof fetchImpl !== "function" || !AbortControllerImpl) {
      throw new Error("Secure password screening is unavailable in this browser. Please use an up-to-date browser over HTTPS.");
    }

    const digest = await cryptoApi.subtle.digest("SHA-1", new TextEncoder().encode(password));
    const hash = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("").toUpperCase();
    const prefix = hash.slice(0, 5);
    const suffix = hash.slice(5);
    const controller = new AbortControllerImpl();
    const timeoutMs = Number.isFinite(options.timeoutMs) ? Math.max(1, options.timeoutMs) : 10000;
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    let body;

    try {
      const response = await fetchImpl("https://api.pwnedpasswords.com/range/" + prefix, {
        method: "GET",
        mode: "cors",
        headers: { "Add-Padding": "true" },
        cache: "no-store",
        credentials: "omit",
        referrerPolicy: "no-referrer",
        redirect: "error",
        signal: controller.signal
      });
      if (!response || !response.ok) {
        throw new Error("The leaked-password screening service is temporarily unavailable. Please retry in a moment.");
      }
      body = await response.text();
      if (typeof body !== "string" || body.length === 0 || body.length > 300000) {
        throw new Error("The password screening response was invalid. Please retry.");
      }
    } catch (error) {
      if (error?.name === "AbortError") {
        throw new Error("Leaked-password screening timed out. Please retry.");
      }
      if (error instanceof TypeError || error?.name === "NetworkError") {
        throw new Error("The leaked-password screening service could not be reached. Please retry.");
      }
      throw error;
    } finally {
      clearTimeout(timeout);
    }

    const lines = body.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
    if (lines.length === 0) {
      throw new Error("The password screening response was empty. Please retry.");
    }

    let compromised = false;
    for (const line of lines) {
      const match = /^([A-F0-9]{35}):([0-9]+)$/i.exec(line);
      if (!match) {
        throw new Error("The password screening response could not be verified. Please retry.");
      }
      const count = Number(match[2]);
      if (!Number.isSafeInteger(count)) {
        throw new Error("The password screening response could not be verified. Please retry.");
      }
      if (match[1].toUpperCase() === suffix && count > 0) compromised = true;
    }

    if (compromised) {
      throw new Error("This password appears in known data breaches. Choose a new, unique password.");
    }
    return { checked: true, compromised: false, source: "Have I Been Pwned Pwned Passwords" };
  }

  root.screenPasswordAgainstBreachCorpus = screenPasswordAgainstBreachCorpus;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = { screenPasswordAgainstBreachCorpus };
  }
})(typeof window !== "undefined" ? window : globalThis);
