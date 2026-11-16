"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { webcrypto } = require("node:crypto");
const { screenPasswordAgainstBreachCorpus } = require("../app/static/password-screening.js");

function screen(password, options = {}) {
  return screenPasswordAgainstBreachCorpus(password, { crypto: webcrypto, ...options });
}

async function sha1(value) {
  const digest = await webcrypto.subtle.digest("SHA-1", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("").toUpperCase();
}

function response(body, ok = true) {
  return { ok, text: async () => body };
}

test("clean password uses k-anonymity prefix request and validates the complete response", async () => {
  const password = "a-new-unique-password-that-is-not-in-the-test-range";
  const hash = await sha1(password);
  let request;
  const result = await screen(password, {
    fetch: async (url, options) => {
      request = { url, options };
      return response("00000000000000000000000000000000000:0\r\nFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF:0\r\n");
    }
  });
  assert.equal(result.checked, true);
  assert.equal(result.compromised, false);
  assert.equal(request.url, "https://api.pwnedpasswords.com/range/" + hash.slice(0, 5));
  assert.equal(request.options.method, "GET");
  assert.equal(request.options.headers["Add-Padding"], "true");
  assert.equal(request.options.credentials, "omit");
  assert.equal(request.options.cache, "no-store");
  assert.equal(request.options.referrerPolicy, "no-referrer");
  assert.equal(request.options.redirect, "error");
});

test("known breached password is rejected", async () => {
  const password = "password";
  const hash = await sha1(password);
  await assert.rejects(
    screen(password, {
      fetch: async () => response(hash.slice(5) + ":42\n")
    }),
    /appears in known data breaches/
  );
});

test("malformed successful response fails closed", async () => {
  await assert.rejects(
    screen("another-password", {
      fetch: async () => response("<html>temporary edge page</html>")
    }),
    /could not be verified/
  );
});

test("empty successful response fails closed", async () => {
  await assert.rejects(
    screen("another-password", {
      fetch: async () => response("")
    }),
    /response was invalid/
  );
});

test("HTTP failure fails closed", async () => {
  await assert.rejects(
    screen("another-password", {
      fetch: async () => response("", false)
    }),
    /temporarily unavailable/
  );
});

test("network failure fails closed", async () => {
  await assert.rejects(
    screen("another-password", {
      fetch: async () => { throw new TypeError("network down"); }
    }),
    /could not be reached/
  );
});

test("timeout aborts the range request and fails closed", async () => {
  await assert.rejects(
    screen("another-password", {
      timeoutMs: 5,
      fetch: async (_url, options) => new Promise((resolve, reject) => {
        options.signal.addEventListener("abort", () => {
          const error = new Error("aborted");
          error.name = "AbortError";
          reject(error);
        }, { once: true });
      })
    }),
    /timed out/
  );
});
