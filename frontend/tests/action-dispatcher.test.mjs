import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import path from "node:path"
import { test } from "node:test"
import { fileURLToPath } from "node:url"
import vm from "node:vm"
import ts from "typescript"
import { randomUUID } from "node:crypto"

const testDirectory = path.dirname(fileURLToPath(import.meta.url))

// Test the TypeScript modules with browser/API boundaries isolated, without a server.
function load(relativePath, dependencies = {}, globals = {}) {
  const source = readFileSync(path.join(testDirectory, "..", relativePath), "utf8")
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  })
  const exports = {}
  vm.runInNewContext(outputText, {
    exports, require: (name) => dependencies[name], Error, URLSearchParams, ...globals,
  })
  return exports
}

function fixture({ role = "student", acknowledge = true, loggingFails = false } = {}) {
  const reports = [], pushes = [], highlights = [], events = [], requests = [], scrolls = []
  let time = 0
  let mounted = false
  let delayMount = false
  const window = {
    location: { pathname: `/${role}/history`, search: "" },
    setTimeout: (callback, ms) => { time += ms; mounted = true; callback() },
    dispatchEvent: (event) => {
      events.push(event)
      if (acknowledge && (!delayMount || mounted)) event.detail.handled = true
    },
    scrollTo: (options) => scrolls.push(options.top),
  }
  const element = { getClientRects: () => [1], scrollIntoView: () => scrolls.push("element") }
  const document = {
    documentElement: { scrollHeight: 1200 },
    querySelector: (selector) => {
      if (selector === "[") throw new Error("Invalid selector")
      return selector === "#missing" || (delayMount && !mounted) ? null : element
    },
  }
  const navigation = load("lib/assistant-navigation.ts", {
    "@/lib/config": { ADVISOR_FEATURES: true },
    "@/resources/routes.json": { default: JSON.parse(readFileSync(path.join(testDirectory, "../resources/routes.json"), "utf8")) },
    "@/resources/ui_registry.json": { default: JSON.parse(readFileSync(path.join(testDirectory, "../resources/ui_registry.json"), "utf8")) },
    "../../src/services/assistant/resources/routes.json": { default: JSON.parse(readFileSync(path.join(testDirectory, "../resources/routes.json"), "utf8")) },
    "../../src/services/assistant/resources/ui_registry.json": { default: JSON.parse(readFileSync(path.join(testDirectory, "../resources/ui_registry.json"), "utf8")) },
  })
  const { dispatchAgentAction, dispatchUIActions } = load("lib/action-dispatcher.ts", {
    "sonner": { toast: { error() {}, info() {}, success() {} } },
    "@/lib/api": { api: {
      createGapAnalysis: async (body) => { requests.push({ ...body }); return { id: "analysis-1" } },
      getAdvisorStudent: async (id) => { requests.push(id); return { id } },
    } },
    "@/lib/assistant-navigation": navigation,
    "@/lib/assistant-api": { confirmAction: async (id, status) => {
      reports.push([id, status])
      if (loggingFails) throw new Error("Offline")
    } },
  }, {
    window, document, Date: { now: () => time },
    CustomEvent: class { constructor(type, { detail }) { this.type = type; this.detail = detail } },
  })
  const router = { push(url) {
    pushes.push(url)
    const [pathname, search] = url.split("?")
    window.location = { pathname, search: search ? `?${search}` : "" }
    mounted = false
  } }
  return {
    reports, pushes, highlights, events, requests, scrolls, window, router, dispatchAgentAction, dispatchUIActions, navigation,
    delayMount: () => { delayMount = true },
    run: (type, params = {}, options = {}, requires_confirmation = false) => dispatchAgentAction(
      { id: "action-1", action_type: type, params, requires_confirmation, description_vi: "Hướng dẫn" },
      router, (...args) => highlights.push(args), { role, ...options },
    ),
  }
}

// A small hook harness exercises the provider's state/callback integration. Browser
// layout and portal behavior are covered separately by the highlighter checks.
function hooksFixture({ runEffects = false } = {}) {
  const cells = []
  const effects = []
  let cursor = 0
  const memoize = (factory, deps) => {
    const index = cursor++
    if (!cells[index] || deps.some((value, i) => !Object.is(value, cells[index].deps[i]))) cells[index] = { value: factory(), deps }
    return cells[index].value
  }
  const react = {
    createContext: () => ({ Provider: "context-provider" }),
    useMemo: memoize, useCallback: (callback, deps) => memoize(() => callback, deps),
    useRef: (value) => memoize(() => ({ current: value }), []),
    useEffect(effect, deps) {
      if (!runEffects) return
      const index = cursor++
      if (!cells[index] || deps.some((value, i) => !Object.is(value, cells[index].deps[i]))) {
        cells[index] = { deps }
        effects.push(effect)
      }
    }, useContext() {},
    useSyncExternalStore: (subscribe, snapshot) => snapshot(),
    useState: (initial) => {
      const index = cursor++
      cells[index] ??= { value: typeof initial === "function" ? initial() : initial }
      return [cells[index].value, (value) => { cells[index].value = typeof value === "function" ? value(cells[index].value) : value }]
    },
  }
  const jsx = (type, props) => ({ type, props })
  return { react, jsxRuntime: { jsx, jsxs: jsx }, render: (callback) => {
    cursor = 0
    const tree = callback()
    effects.splice(0).forEach((effect) => effect())
    return tree
  } }
}

function providerFixture(actions, ui_actions = [], options = {}) {
  const f = fixture()
  const hooks = hooksFixture({ runEffects: options.hydrate })
  f.window.localStorage = { getItem: () => options.conversationId ?? null, setItem() {}, removeItem() {} }
  const { AgentActionRunner } = load("lib/agent-action-runner.ts", {}, { AbortController })
  const inputs = []
  const animationFrames = []
  const { AssistantProvider } = load("components/assistant/assistant-provider.tsx", {
    react: hooks.react, "react/jsx-runtime": hooks.jsxRuntime,
    "next/navigation": { usePathname: () => f.window.location.pathname, useRouter: () => f.router },
    "sonner": { toast: { error() {} } },
    "@/lib/agent-action-runner": { AgentActionRunner },
    "@/lib/action-dispatcher": { dispatchAgentAction: f.dispatchAgentAction, dispatchUIActions: f.dispatchUIActions },
    "@/lib/assistant-api": {
      streamMessage: async (input, onEvent, signal) => {
        inputs.push(input)
        if (options.stream) return options.stream(input, onEvent, signal)
        return { conversation_id: "conv-1", turn_id: "turn-1", message: "Saved guide", actions, ui_actions, sources: [] }
      },
      cancelRun: async (id) => { f.requests.push({ cancel: id }); return { id, status: "cancelled" } },
      getConversationHistory: async () => options.history ?? [],
      confirmAction: async (id, status) => { f.reports.push([id, status]) },
    },
    "@/components/assistant/action-confirmation-dialog": { ActionConfirmationDialog: "confirmation-dialog" },
    "@/components/assistant/element-highlighter": { ElementHighlighter: "highlighter" },
  }, { requestAnimationFrame: (callback) => { animationFrames.push(callback); return animationFrames.length }, window: f.window, AbortController, crypto: { randomUUID }, CustomEvent: class { constructor(type, { detail }) { this.type = type; this.detail = detail } } })
  const render = () => hooks.render(() => {
    const session = AssistantProvider({ children: null })
    return session.type(session.props)
  })
  return { ...f, inputs, render, animationFrames, flushFrame: () => { const callbacks = animationFrames.splice(0); callbacks.forEach((callback) => callback()) } }
}

test("analysis start button carries the agent target and reports the selection without submitting a job", () => {
  // NewAnalysis and SinglePicker share one module, so each component gets its own hook cells behind one react proxy.
  const page = hooksFixture(), picker = hooksFixture()
  let current = page
  const react = new Proxy({}, { get: (_, key) => current.react[key] })
  let handlers, jobs = 0
  const cvs = [{ id: "cv-1", file_name: "CV.pdf", label: "v1.0", status: "ready", is_active: true }]
  const items = [{ id: "jd-1", title: "Backend Intern", company: "Công ty G" }]
  const api = { listCvVersions: () => cvs, createGapAnalysis: () => { jobs++ } }
  const { NewAnalysis } = load("components/student/analysis/new-analysis.tsx", {
    react, "react/jsx-runtime": page.jsxRuntime,
    "next/navigation": { useRouter: () => ({ push() {}, replace() {} }), useSearchParams: () => new URLSearchParams() },
    "lucide-react": {}, "sonner": { toast: {} },
    "@/lib/api": { api }, "@/lib/use-api": { useApi: (fetch) => ({ data: fetch() }) },
    "@/lib/use-agent-actions": { useAgentActions: (value) => { handlers = value } },
    "@/components/common/bottom-action-bar": { BottomActionBar: "bar" },
    "@/components/common/page-header": { PageHeader: "page-header" },
    "@/components/common/segmented-control": { SegmentedControl: "segmented" },
    "@/components/common/zone": { Zone: "zone" },
    "@/components/student/analysis/compare-picker": { ComparePicker: "compare-picker" },
    "@/components/student/analysis/cv-pick-step": { CvZone: "cv-zone" },
    "@/components/student/analysis/jd-picker-sections": {
      EMPTY_PASTE: { title: "", company: "", text: "", save: false }, SOURCE_OPTIONS: [],
      usePickItems: () => ({ items }), pasteErrors: () => ({ text: "required" }), pasteMissingHint: () => "",
      composeJdText: () => "", JdRadioList: "radio-list", JdPasteForm: "paste-form",
    },
    "@/components/student/library/library-data": { metaLine: (...parts) => parts.filter(Boolean).join(" · ") },
    "@/components/ui/button": { Button: "button" }, "@/components/ui/skeleton": { Skeleton: "skeleton" },
  })
  const find = (tree, match) => {
    if (!tree || typeof tree !== "object") return null
    if (match(tree)) return tree
    const children = Array.isArray(tree) ? tree : tree.props?.children
    return (Array.isArray(children) ? children : [children]).map((child) => find(child, match)).find(Boolean) ?? null
  }
  const singlePicker = find(page.render(() => NewAnalysis({ initialCvId: null, initialJdIds: [] })), (node) => node.type?.name === "SinglePicker")
  current = picker
  const renderPicker = () => picker.render(() => singlePicker.type(singlePicker.props))
  renderPicker() // chọn sẵn vị trí đầu danh sách
  const button = find(renderPicker(), (node) => node.props?.["data-agent-target"] === "btn-start-analysis")
  assert.equal(button.type, "button")
  assert.equal(button.props.disabled, false)
  assert.deepEqual(JSON.parse(JSON.stringify(handlers.getContext())), {
    selected_cv_id: "cv-1",
    page_state: { active_tab: "list", selected_jd_id: "jd-1", selected_cv_name: "CV.pdf · v1.0", selected_jd_title: "Backend Intern · Công ty G" },
  })
  handlers.resetView({ clear_filters: true, close_modals: true })
  assert.equal(jobs, 0)
})

test("v2 provider ignores legacy automatic actions and never starts an analysis", async () => {
  const f = providerFixture([
    { id: "nav", action_type: "NAVIGATE_PAGE", params: { route: "/student/analysis" } },
    { id: "start", action_type: "START_ANALYSIS", params: { cv_id: "cv-1", jd_id: "jd-1" } },
  ])
  await f.render().props.value.sendMessage("Open analysis")
  f.flushFrame()
  assert.equal(f.requests.length, 0)
  assert.equal(f.pushes.length, 0)
  assert.equal(f.reports.length, 0)
  assert.equal(f.render().props.value.activeAction, null)
  assert.equal(f.render().props.children.length, 2)
})

test("confirmation dialog exposes confirm/cancel, fallback description and busy dismissal guards", () => {
  const jsx = (type, props) => ({ type, props })
  const { ActionConfirmationDialog } = load("components/assistant/action-confirmation-dialog.tsx", {
    react: { useMemo: (factory) => factory() },
    "react/jsx-runtime": { jsx, jsxs: jsx }, "lucide-react": { Loader2: "loader" },
    "@/components/ui/button": { Button: "button" },
    "@/components/ui/dialog": Object.fromEntries(["Dialog", "DialogContent", "DialogDescription", "DialogTitle"].map((name) => [name, name])),
  })
  const find = (tree, match, found = []) => {
    if (!tree || typeof tree !== "object") return found
    if (match(tree)) found.push(tree)
    const children = Array.isArray(tree) ? tree : tree.props?.children
    for (const child of Array.isArray(children) ? children : [children]) find(child, match, found)
    return found
  }
  let approved = 0, rejected = 0
  const props = { action: { description_vi: "Phân tích CV" }, busy: false, onConfirm: async () => { approved++ }, onReject: async () => { rejected++ } }
  assert.equal(ActionConfirmationDialog({ ...props, action: null }), null)
  const tree = ActionConfirmationDialog(props)
  assert.equal(find(tree, (node) => node.type === "DialogDescription")[0].props.children, "Phân tích CV")
  const [cancel, confirm] = find(tree, (node) => node.type === "button")
  cancel.props.onClick()
  confirm.props.onClick()
  assert.equal(rejected, 1)
  assert.equal(approved, 1)
  const busy = ActionConfirmationDialog({ ...props, busy: true })
  busy.props.onOpenChange(false)
  assert.equal(rejected, 1)
  assert.ok(find(busy, (node) => node.type === "button").every((button) => button.props.disabled))
})

test("navigation resolves guide aliases and encodes query values", async () => {
  const f = fixture()
  assert.equal(await f.run("NAVIGATE_PAGE", { route: "/student/analysis", query: { cv: "CV & 1" } }), true)
  assert.deepEqual(f.pushes, ["/student/analysis/new?cv=CV+%26+1"])
  assert.deepEqual(f.reports, [["action-1", "executed"]])
})

test("navigation blocks external, executable and other-role routes", async () => {
  for (const route of ["https://example.com", "javascript:alert(1)", "/advisor/students"]) {
    const f = fixture()
    assert.equal(await f.run("NAVIGATE_PAGE", { route }), false)
    assert.equal(f.pushes.length, 0)
    assert.deepEqual(f.reports, [["action-1", "failed"]])
  }
})

test("highlight waits for the destination DOM and forwards duration", async () => {
  const f = fixture()
  f.delayMount()
  await f.run("NAVIGATE_PAGE", { route: "/student/cv" })
  assert.equal(await f.run("HIGHLIGHT_ELEMENT", { selector: "#upload", tooltip: "Tải CV", duration_ms: 8000 }), true)
  assert.deepEqual(f.highlights.at(-1), ["#upload", "Tải CV", 8000])
})

test("missing or malformed selectors report failure", async () => {
  for (const selector of ["#missing", "["]) {
    const f = fixture()
    assert.equal(await f.run("HIGHLIGHT_ELEMENT", { selector }), false)
    assert.deepEqual(f.reports, [["action-1", "failed"]])
    assert.equal(f.highlights.length, 0)
  }
})

test("page commands wait for listeners and retain their parameters", async () => {
  const f = fixture()
  f.delayMount()
  assert.equal(await f.run("FILL_FILTER", { filter_name: "keyword", value: "Backend" }), true)
  assert.equal(f.events.at(-1).detail.value, "Backend")
  assert.equal(await f.run("OPEN_MODAL", { modal_id: "upload-cv-modal" }), true)
  assert.equal(f.events.at(-1).detail.modal_id, "upload-cv-modal")
  assert.equal(await f.run("RESET_VIEW", { clear_filters: false, close_modals: true }), true)
  assert.equal(f.events.at(-1).detail.clear_filters, false)
  assert.equal(f.events.at(-1).detail.close_modals, true)
})

test("an unhandled page command cannot be reported as executed", async () => {
  const f = fixture({ acknowledge: false })
  assert.equal(await f.run("OPEN_MODAL", { modal_id: "unknown-modal" }), false)
  assert.deepEqual(f.reports, [["action-1", "failed"]])
})

test("analysis requires consent even when the payload omits the confirmation flag", async () => {
  const f = fixture()
  const params = { cv_id: "cv-1", jd_id: "jd-1" }
  assert.equal(await f.run("START_ANALYSIS", params), false)
  assert.equal(f.requests.length, 0)
  assert.equal(f.reports.length, 0)
  assert.equal(await f.run("START_ANALYSIS", params, { confirmed: true }), true)
  assert.deepEqual(f.requests, [{ cv_version_id: "cv-1", jd_id: "jd-1" }])
  assert.deepEqual(f.pushes, ["/student/analysis/analysis-1"])
})

test("student selection is advisor-only and verifies access", async () => {
  const student = fixture()
  assert.equal(await student.run("SELECT_STUDENT", { student_id: "student-1" }), false)
  assert.equal(student.requests.length, 0)
  const advisor = fixture({ role: "advisor" })
  assert.equal(await advisor.run("SELECT_STUDENT", { student_id: "student-1" }), true)
  assert.deepEqual(advisor.requests, ["student-1"])
  assert.deepEqual(advisor.pushes, ["/advisor/students/student-1"])
})

test("scroll supports top, bottom and a DOM target", async () => {
  const f = fixture()
  for (const params of [{ position: "top" }, { position: "bottom" }, { selector: "#target" }]) {
    assert.equal(await f.run("SCROLL_TO", params), true)
  }
  assert.deepEqual(f.scrolls, [0, 1200, "element"])
})

test("logging outages do not change a completed UI action to failed", async () => {
  const f = fixture({ loggingFails: true })
  assert.equal(await f.run("SCROLL_TO", { position: "top" }), true)
  assert.deepEqual(f.reports, [["action-1", "executed"]])
})

test("invalid parameters and unknown actions report failure", async () => {
  for (const [type, params] of [["UNKNOWN", {}], ["FILL_FILTER", { filter_name: "keyword", value: {} }], ["RESET_VIEW", { close_modals: "yes" }]]) {
    const f = fixture()
    assert.equal(await f.run(type, params), false)
    assert.deepEqual(f.reports, [["action-1", "failed"]])
  }
})

test("page bridge updates React state, acknowledges supported commands and cleans up", () => {
  const listeners = new Map()
  const window = { addEventListener: (name, handler) => listeners.set(name, handler), removeEventListener: (name) => listeners.delete(name) }
  let cleanup, query = "", modalOpen = false
  const { useAgentActions } = load("lib/use-agent-actions.ts", { react: { useEffect: (setup) => { cleanup = setup() } } }, { window })
  let prepared = null
  useAgentActions({
    fillFilter: (name, value) => { if (name !== "keyword") return false; query = value; return true },
    openModal: (id) => { if (id !== "upload-cv-modal") return false; modalOpen = true; return true },
    resetView: ({ clear_filters, close_modals }) => { if (clear_filters) query = ""; if (close_modals) modalOpen = false },
    prepareHighlight: (selector) => { prepared = selector },
    getContext: () => ({ selected_cv_id: "cv-1", page_state: { selected_jd_id: "jd-1" } }),
  })
  const send = (name, params) => { const detail = { ...params, handled: false }; listeners.get(name)({ detail }); return detail.handled }
  assert.equal(send("agent:fill_filter", { filter_name: "keyword", value: "Backend" }), true)
  assert.equal(query, "Backend")
  assert.equal(send("agent:fill_filter", { filter_name: "unknown", value: "x" }), false)
  assert.equal(send("agent:open_modal", { modal_id: "upload-cv-modal" }), true)
  send("agent:reset_view", { clear_filters: false, close_modals: true })
  assert.equal(query, "Backend")
  assert.equal(modalOpen, false)
  listeners.get("agent:prepare_highlight")({ detail: { selector: "#start" } })
  assert.equal(prepared, "#start")
  const context = {}
  listeners.get("agent:page_context")({ detail: context })
  assert.equal(context.selected_cv_id, "cv-1")
  assert.equal(context.page_state.selected_jd_id, "jd-1")
  cleanup()
  assert.equal(listeners.size, 0)
})

function runnerFixture({ reportFails = false } = {}) {
  const calls = []
  let pending = null, busy = false
  const { AgentActionRunner } = load("lib/agent-action-runner.ts", {}, { AbortController })
  const runner = new AgentActionRunner({
    execute: async (action, confirmed) => { calls.push(["execute", action.id, confirmed]); return true },
    report: async (id, status) => { calls.push(["report", id, status]); if (reportFails) throw new Error("Offline") },
    onPending: (action) => { pending = action },
    onBusy: (value) => { busy = value },
  })
  const action = (id, type = "HIGHLIGHT_ELEMENT", requires_confirmation = false) => ({ id, action_type: type, params: {}, requires_confirmation, description_vi: id })
  return { runner, calls, action, pending: () => pending, busy: () => busy }
}

test("response actions pause for consent then resume in their original order", async () => {
  const f = runnerFixture()
  await f.runner.enqueue([f.action("navigate", "NAVIGATE_PAGE"), f.action("start", "START_ANALYSIS"), f.action("highlight")])
  assert.equal(f.pending().id, "start")
  assert.equal(f.busy(), false)
  assert.deepEqual(f.calls, [["execute", "navigate", false]])
  await Promise.all([f.runner.confirm(), f.runner.confirm()])
  assert.deepEqual(f.calls, [["execute", "navigate", false], ["report", "start", "confirmed"], ["execute", "start", true], ["execute", "highlight", false]])
  assert.equal(f.pending(), null)
  await f.runner.enqueue([f.action("start", "START_ANALYSIS")], true)
  assert.equal(f.pending(), null)
})

test("cancel reports rejected and discards dependent actions", async () => {
  const f = runnerFixture()
  await f.runner.enqueue([f.action("start", "START_ANALYSIS"), f.action("highlight")])
  await f.runner.reject()
  assert.deepEqual(f.calls, [["report", "start", "rejected"]])
  assert.equal(f.pending(), null)
})

test("a failed consent report keeps the dialog pending and never starts analysis", async () => {
  const f = runnerFixture({ reportFails: true })
  await f.runner.enqueue([f.action("start", "START_ANALYSIS")])
  await assert.rejects(f.runner.confirm(), /Offline/)
  assert.equal(f.pending().id, "start")
  assert.equal(f.busy(), false)
  assert.deepEqual(f.calls, [["report", "start", "confirmed"]])
})

test("readonly badges can replay a highlight without replaying a state-changing action", async () => {
  const f = runnerFixture()
  await f.runner.enqueue([f.action("highlight")])
  await f.runner.enqueue([f.action("highlight")], true)
  assert.deepEqual(f.calls, [["execute", "highlight", false], ["execute", "highlight", false]])
})

test("reset during confirmation prevents a delayed acknowledgement from executing stale actions", async () => {
  const f = runnerFixture()
  let finishReport
  const { AgentActionRunner } = load("lib/agent-action-runner.ts", {}, { AbortController })
  const runner = new AgentActionRunner({
    execute: async () => { assert.fail("A cleared action must not execute") },
    report: () => new Promise((resolve) => { finishReport = resolve }),
    onPending() {}, onBusy() {},
  })
  await runner.enqueue([f.action("start", "START_ANALYSIS")])
  const confirming = runner.confirm()
  runner.reset()
  finishReport()
  await confirming
  assert.equal(runner.activeAction, null)
})

function highlighterFixture(initialRect) {
  let rect = initialRect, state = null, setup, timer, frame, dismissed = 0
  const listeners = new Map(), elementListeners = new Map()
  const element = {
    isConnected: true,
    getBoundingClientRect: () => rect,
    scrollIntoView: () => { element.scrolled = true },
    addEventListener: (name, callback) => elementListeners.set(name, callback),
    removeEventListener: (name) => elementListeners.delete(name),
  }
  const window = {
    innerHeight: 1000, innerWidth: 1200, scrollX: 100, scrollY: 900,
    setTimeout: (callback, ms) => { timer = { callback, ms }; return 1 },
    clearTimeout: () => { timer = null },
    addEventListener: (name, callback, capture) => listeners.set(name, { callback, capture }),
    removeEventListener: (name) => listeners.delete(name),
  }
  let observerDisconnected = false
  const jsx = (type, props) => ({ type, props })
  const { ElementHighlighter } = load("components/assistant/element-highlighter.tsx", {
    react: { useState: () => [state, (value) => { state = value }], useEffect: (effect) => { setup ??= effect } },
    "react-dom": { createPortal: (content) => content },
    "react/jsx-runtime": { jsx, jsxs: jsx },
    "lucide-react": { Target() {} },
  }, {
    window, document: { body: {}, querySelector: () => element },
    ResizeObserver: class { observe() {} disconnect() { observerDisconnected = true } },
    requestAnimationFrame: (callback) => { frame = callback; return 1 }, cancelAnimationFrame() {},
  })
  const render = () => ElementHighlighter({ selector: "#target", onDismiss: () => { dismissed++ } })
  render()
  const cleanup = setup()
  frame()
  return { element, listeners, elementListeners, render, cleanup, move: (next) => { rect = next }, flush: () => frame(), timer: () => timer, dismissed: () => dismissed, observerDisconnected: () => observerDisconnected }
}

test("fixed spotlight uses viewport coordinates and follows nested scrolling", () => {
  const f = highlighterFixture({ top: 200, left: 80, bottom: 240, right: 180, width: 100, height: 40 })
  assert.equal(f.element.scrolled, undefined)
  let style = f.render().props.children[0].props.style
  assert.equal(style.top, 194)
  assert.equal(style.left, 74)
  assert.equal(style.width, 112)
  assert.equal(f.listeners.get("scroll").capture, true)
  f.move({ top: 300, left: 80, bottom: 340, right: 180, width: 100, height: 40 })
  f.listeners.get("scroll").callback()
  f.flush()
  style = f.render().props.children[0].props.style
  assert.equal(style.top, 294)
  f.cleanup()
})

test("spotlight scrolls offscreen targets, dismisses on click/5s, and releases resources", () => {
  const f = highlighterFixture({ top: 1100, left: 80, bottom: 1140, right: 180, width: 100, height: 40 })
  assert.equal(f.element.scrolled, true)
  assert.equal(f.timer().ms, 5000)
  f.elementListeners.get("click")()
  assert.equal(f.dismissed(), 1)
  f.timer().callback()
  assert.equal(f.dismissed(), 2)
  f.cleanup()
  assert.equal(f.timer(), null)
  assert.equal(f.listeners.size, 0)
  assert.equal(f.elementListeners.size, 0)
  assert.equal(f.observerDisconnected(), true)
})


test("v2 provider navigates then highlights a registered target without acknowledgement", async () => {
  const f = providerFixture([], [
    { type: "navigate", route_id: "analysis_new", params: {} },
    { type: "highlight", element_id: "btn-start-analysis" },
  ])
  f.delayMount()
  await f.render().props.value.sendMessage("Nút bắt đầu phân tích ở đâu?")
  assert.equal(f.window.location.pathname, "/student/analysis/new")
  assert.equal(f.render().props.children[1].props.selector, '[data-assistant-id="btn-start-analysis"]')
  assert.equal(f.reports.length, 0)
  assert.equal(f.requests.length, 0)
})

test("v2 rejects unknown IDs, bad params, and targets outside the role without acknowledgements", async () => {
  for (const action of [
    { type: "highlight", element_id: "unknown" },
    { type: "highlight", element_id: "advisor-student-search" },
    { type: "navigate", route_id: "advisor_students", params: {} },
    { type: "navigate", route_id: "cv_list", params: { url: "https://evil.test" } },
    { type: "navigate", route_id: "cv_detail", params: { cv_id: "../other" } },
    { type: "navigate", route_id: "__proto__", params: {} },
  ]) {
    const f = fixture()
    assert.equal(await f.dispatchAgentAction(action, f.router, (...args) => f.highlights.push(args), { role: "student" }), false)
    assert.equal(f.reports.length, 0)
    assert.equal(f.pushes.length, 0)
    assert.equal(f.highlights.length, 0)
  }
})

test("v2 stops before highlight when navigation fails and honours cancellation", async () => {
  const f = fixture()
  const actions = [{ type: "navigate", route_id: "advisor_students", params: {} }, { type: "highlight", element_id: "btn-upload-cv" }]
  assert.equal(await f.dispatchUIActions(actions, f.router, (...args) => f.highlights.push(args), { role: "student" }), false)
  assert.equal(f.highlights.length, 0)
  const controller = new AbortController()
  controller.abort()
  assert.equal(await f.dispatchUIActions([{ type: "navigate", route_id: "cv_list", params: {} }], f.router, () => {}, { role: "student", signal: controller.signal }), false)
  assert.equal(f.pushes.length, 0)
  assert.equal(f.reports.length, 0)
})


test("v2 navigation card retains a manual link on the destination page", () => {
  const f = fixture()
  const jsx = (type, props) => ({ type, props })
  const { ActionBadges } = load("components/assistant/action-badges.tsx", {
    "react/jsx-runtime": { jsx, jsxs: jsx },
    "lucide-react": {},
    "@/components/assistant/assistant-provider": { useAssistant: () => ({ userRole: "student", pathname: "/student/cv" }) },
    "@/components/shell/nav-config": { shellOf: () => "student", getBreadcrumb: () => [{ label: "CV" }] },
    "@/lib/assistant-navigation": f.navigation,
    "@/lib/utils": { cn: () => "" },
  })
  const tree = ActionBadges({ actions: [], uiActions: [{ type: "navigate", route_id: "cv_list", params: {} }] })
  const link = tree.props.children[0][0]
  assert.equal(link.type, "a")
  assert.equal(link.props.href, "/student/cv")
})


test("streamed tokens batch per animation frame and final uses the saved turn", async () => {
  let finish
  const gate = new Promise((resolve) => { finish = resolve })
  const f = providerFixture([], [], { stream: async (_, onEvent) => {
    for (let i = 0; i < 500; i++) onEvent({ event: "token", data: { run_id: "run", conversation_id: "conv-1", text: "x" } })
    await gate
    return { run_id: "run", conversation_id: "conv-1", turn_id: "saved-turn", message: "x".repeat(500), actions: [], sources: [] }
  } })
  const sending = f.render().props.value.sendMessage("How to upload?")
  assert.equal(f.animationFrames.length, 1)
  assert.equal(f.render().props.value.messages.at(-1).content, "")
  f.flushFrame()
  assert.equal(f.render().props.value.messages.at(-1).content, "x".repeat(500))
  assert.equal(f.render().props.value.messages.at(-1).is_streaming, true)
  finish()
  await sending
  assert.equal(f.animationFrames.length, 1)
  f.flushFrame()
  assert.equal(f.render().props.value.messages.at(-1).id, "saved-turn")
  assert.equal(f.render().props.value.messages.at(-1).is_streaming, false)
  assert.ok(f.inputs[0].client_request_id)
})

test("Stop cancels the known run and keeps partial text", async () => {
  const f = providerFixture([], [], { stream: async (_, onEvent, signal) => {
    onEvent({ event: "token", data: { run_id: "run", conversation_id: "conv-1", text: "partial" } })
    await new Promise((_, reject) => signal.addEventListener("abort", () => reject(new Error("Aborted")), { once: true }))
  } })
  const sending = f.render().props.value.sendMessage("How to upload?")
  f.render().props.value.stop()
  await sending
  f.flushFrame()
  assert.equal(f.requests[0].cancel, "run")
  assert.equal(f.render().props.value.messages.at(-1).content, "partial")
  assert.equal(f.render().props.value.messages.at(-1).interrupted, true)
  assert.equal(f.render().props.value.isThinking, false)
})

test("cards use role-checked registry links and chips retain structured payloads", () => {
  const hooks = hooksFixture()
  const { AssistantCards, AssistantChips } = load("components/assistant/assistant-cards.tsx", {
    "react/jsx-runtime": hooks.jsxRuntime,
    "next/link": { default: "link" },
    "lucide-react": { ArrowUpRight: "arrow" },
    "@/lib/assistant-navigation": fixture().navigation,
  })
  const cards = AssistantCards({ role: "student", cards: [
    { ref: "cv", label: "CV", route_id: "cv_list", params: {} },
    { ref: "forbidden", label: "Advisor", route_id: "advisor_home", params: {} },
    { ref: "invalid", label: "Unknown", route_id: "javascript:alert(1)", params: {} },
  ] }).props.children.filter(Boolean)
  assert.equal(cards.length, 1)
  assert.equal(cards[0].props.href, "/student/cv")
  const chip = { label: "CV", route: "navigate", slots: { target: "cv" } }
  let selected
  const chips = AssistantChips({ chips: [chip], disabled: false, onSelect: (value) => { selected = value } })
  chips.props.children[0].props.onClick()
  assert.equal(selected, chip)
  assert.equal(AssistantChips({ chips: [chip], disabled: true }).props.children[0].props.disabled, true)
})

test("restoring a conversation loads saved messages without replaying UI actions", async () => {
  const f = providerFixture([], [], { hydrate: true, conversationId: "saved-conversation", history: [
    { id: "turn:user", sender: "user", content: "Previous question" },
    { id: "turn:assistant", turn_id: "turn", sender: "assistant", content: "Saved partial", interrupted: true,
      ui_actions: [{ type: "navigate", route_id: "cv_list", params: {} }] },
  ] })
  f.render()
  await new Promise(setImmediate)
  const value = f.render().props.value
  assert.equal(value.conversationId, "saved-conversation")
  assert.equal(value.messages.length, 2)
  assert.equal(value.messages[1].content, "Saved partial")
  assert.equal(value.messages[1].id, "turn")
  assert.equal(value.messages[1].interrupted, true)
  assert.equal(f.pushes.length, 0)
  assert.equal(f.requests.length, 0)
})

test("assistant cannot open advisor pages while advisor features are hidden", () => {
  const registries = {
    "@/resources/routes.json": { default: JSON.parse(readFileSync(path.join(testDirectory, "../resources/routes.json"), "utf8")) },
    "@/resources/ui_registry.json": { default: JSON.parse(readFileSync(path.join(testDirectory, "../resources/ui_registry.json"), "utf8")) },
  }
  const hidden = load("lib/assistant-navigation.ts", { ...registries, "@/lib/config": { ADVISOR_FEATURES: false } })
  const shown = load("lib/assistant-navigation.ts", { ...registries, "@/lib/config": { ADVISOR_FEATURES: true } })
  assert.equal(hidden.resolveAssistantRoute("/student/share", "student"), null)
  assert.equal(hidden.resolveAssistantRoute("/advisor/students", "advisor"), null)
  assert.equal(shown.resolveAssistantRoute("/student/share", "student"), "/student/share")
  assert.equal(hidden.resolveAssistantRoute("/student/history", "student"), "/student/history")
})
