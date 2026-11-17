const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

// Exercise the shipped event handlers without a browser or network. The small
// DOM double models select defaults, which caused the manager status regression.
function app(fetchHandler) {
  const elements = new Map();
  class Element {
    constructor() {
      this.children = [];
      this.handlers = {};
      this.value = "";
      this.textContent = "";
      const classes = new Set();
      this.classList = {
        add: (name) => classes.add(name), remove: (name) => classes.delete(name),
        contains: (name) => classes.has(name),
        toggle(name, force) {
          const on = force === undefined ? !classes.has(name) : force;
          on ? classes.add(name) : classes.delete(name);
          return on;
        },
      };
    }
    set innerHTML(value) {
      this.html = value;
      this.children = [];
      for (const match of value.matchAll(/<select data-status="([^"]+)" data-current-status="([^"]*)">([\s\S]*?)<\/select>/g)) {
        const select = new Element();
        select.dataset = { currentStatus: match[2] };
        select.options = [...match[3].matchAll(/<option([^>]*)>([^<]*)<\/option>/g)].map((option) => ({
          value: /value="([^"]*)"/.exec(option[1])?.[1] ?? option[2],
          selected: /\bselected\b/.test(option[1]), disabled: /\bdisabled\b/.test(option[1]),
        }));
        select.value = (select.options.find((option) => option.selected) || select.options.find((option) => !option.disabled))?.value;
        elements.set(`[data-status='${match[1]}']`, select);
      }
      for (const match of value.matchAll(/<input data-assignee="([^"]+)" value="([^"]*)"/g)) {
        const input = new Element();
        input.value = match[2];
        elements.set(`[data-assignee='${match[1]}']`, input);
      }
    }
    get innerHTML() { return this.html || ""; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; this.html = ""; this.textContent = ""; }
    addEventListener(name, handler) { this.handlers[name] = handler; }
    remove() {}
    close() {}
    showModal() {}
  }
  function element(selector) {
    if (selector === "#typing") return null;
    if (!elements.has(selector)) elements.set(selector, new Element());
    return elements.get(selector);
  }
  function storage() {
    const values = new Map();
    return {
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, String(value)),
      removeItem: (key) => values.delete(key), clear: () => values.clear(),
    };
  }
  const localStorage = storage(), sessionStorage = storage();
  const context = vm.createContext({
    document: { querySelector: element, querySelectorAll: () => [], createElement: () => new Element(), createTextNode: (text) => ({ textContent: text }) },
    localStorage, sessionStorage,
    fetch: async (url, options = {}) => ({ ok: true, json: async () => fetchHandler(url, options) }),
    crypto: { randomUUID: () => "test-id" },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../frontend/app.js"), "utf8"), context);
  return { element, localStorage, sessionStorage, run: (source) => vm.runInContext(source, context) };
}

for (const status of ["saved", "confirmed"]) {
  test(`saving the assignee preserves ${status} in the actual PATCH payload`, async () => {
    let payload;
    const ui = app((url, options) => {
      if (options.method === "PATCH") { payload = JSON.parse(options.body); return { status: payload.status }; }
      if (url === "/api/requests") return { items: [{ id: "request-1", kind: "test_drive", status }] };
      if (url === "/api/actions") return { items: [] };
      return { conversations: 0, requests: 1, escalations: 0 };
    });
    await ui.run("loadManager()");
    const select = ui.element("[data-status='request-1']");
    assert.equal(select.value, status);
    if (status === "saved") assert.equal(select.options.find((option) => option.value === "confirmed").disabled, true);
    ui.element("[data-assignee='request-1']").value = "Manager";
    await ui.element("#requestsBody").handlers.click({ target: { closest: () => ({ dataset: { save: "request-1" } }) } });
    assert.deepEqual(payload, { assigned_to: "Manager" });
  });
}

test("an assignee edit does not undo a confirmation received after rendering", async () => {
  let status = "saved";
  const ui = app((url, options) => {
    if (options.method === "PATCH") {
      const body = JSON.parse(options.body);
      if (body.status) status = body.status;
      return { status };
    }
    if (url === "/api/requests") return { items: [{ id: "request-1", kind: "test_drive", status }] };
    if (url === "/api/actions") return { items: [] };
    return { conversations: 0, requests: 1, escalations: 0 };
  });
  await ui.run("loadManager()");
  status = "confirmed"; // A signed callback wins while the manager edits.
  ui.element("[data-assignee='request-1']").value = "Manager";
  await ui.element("#requestsBody").handlers.click({ target: { closest: () => ({ dataset: { save: "request-1" } }) } });
  assert.equal(status, "confirmed");
  assert.equal(ui.element("[data-status='request-1']").value, "confirmed");
});

test("an intentional manager status change still reaches the API", async () => {
  let payload;
  const ui = app((url, options) => {
    if (options.method === "PATCH") { payload = JSON.parse(options.body); return payload; }
    if (url === "/api/requests") return { items: [{ id: "request-1", kind: "lead", status: "new" }] };
    if (url === "/api/actions") return { items: [] };
    return { conversations: 0, requests: 1, escalations: 0 };
  });
  await ui.run("loadManager()");
  ui.element("[data-status='request-1']").value = "assigned";
  await ui.element("#requestsBody").handlers.click({ target: { closest: () => ({ dataset: { save: "request-1" } }) } });
  assert.equal(payload.status, "assigned");
});

test("sign-in starts a fresh staff conversation and retains the staff credential", async () => {
  const ui = app((url) => url === "/api/auth/token"
    ? { access_token: "staff-token", role: "employee" }
    : { session_id: "guest-session", session_token: "guest-secret", reply: "Public answer", rag_ids: [] });
  await ui.run("sendMessage('Автомобиль')");
  assert.equal(ui.localStorage.getItem("autosfera_session"), "guest-session");
  await ui.element("#loginForm").handlers.submit({ preventDefault() {} });
  assert.equal(ui.run("sessionId"), null);
  assert.equal(ui.localStorage.getItem("autosfera_session_token"), null);
  assert.equal(ui.sessionStorage.getItem("autosfera_token"), "staff-token");
});

test("a staff reply arriving after logout cannot repopulate the guest chat", async () => {
  let deliver;
  const pending = new Promise((resolve) => { deliver = resolve; });
  const ui = app((url) => url === "/api/auth/token"
    ? { access_token: "staff-token", role: "employee" } : pending);
  await ui.element("#loginForm").handlers.submit({ preventDefault() {} });
  const request = ui.run("sendMessage('Внутренний регламент')");
  ui.element("#logoutBtn").handlers.click();
  deliver({ session_id: "staff-session", reply: "INTERNAL-ONLY", rag_ids: [] });
  await request;
  assert.equal(ui.run("role"), "guest");
  assert.equal(ui.run("sessionId"), null);
  assert.equal(ui.localStorage.getItem("autosfera_session"), null);
  assert.equal(JSON.stringify(ui.element("#messages").children).includes("INTERNAL-ONLY"), false);
});
