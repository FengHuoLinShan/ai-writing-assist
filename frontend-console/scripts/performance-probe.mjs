/** Manual diagnostic runner. Real Chrome + production build + isolated public-auth API. */
import { chromium } from "@playwright/test"
import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { performance } from "node:perf_hooks"
import path from "node:path"
import assert from "node:assert/strict"
import { createHash } from "node:crypto"
import { execFileSync } from "node:child_process"

const out = fileURLToPath(new URL("../../backend/.test-artifacts/performance/", import.meta.url))
const fixture = JSON.parse(readFileSync(path.join(out, "fixture.json")))
if (["world", "world-checks"].includes(process.argv[2])) Object.assign(fixture.profiles, JSON.parse(readFileSync(path.join(out, "round2/alias-fixture.json"))).profiles)
const storage = JSON.parse(readFileSync(path.join(out, "browser-private.json")))
const base = "http://127.0.0.1:18080"
const mode = process.argv[2] || "smoke"
const tier = process.argv[3] || "S"
const label = process.argv[4] || "repeat"
assert(["before", "after", "repeat"].includes(label))
const profile = fixture.profiles[tier]
assert(profile && ["smoke", "baseline", "soak", "imports", "recovery", "profile", "native-control", "contention", "multi-tab", "world", "clipboard", "clipboard-profile", "ime", "persistence", "world-checks"].includes(mode))
mkdirSync(out, { recursive: true, mode: 0o700 })
const run = `${mode}-${tier}-${label}-${new Date().toISOString().replaceAll(/[:.]/g, "-")}`
const results = path.join(out, `${run}.jsonl`)
const provenance = {
  sha: execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim(),
  trackedDiffSha256: createHash("sha256").update(execFileSync("git", ["diff", "HEAD"])).digest("hex"),
  sourceHashes: Object.fromEntries(["backend/modules/world/repositories.py", "backend/modules/world/services/core/entity_alias_service.py", "frontend-console/scripts/performance-probe.mjs"].map((name) => [name, createHash("sha256").update(readFileSync(fileURLToPath(new URL(`../../${name}`, import.meta.url)))).digest("hex")])),
}
const record = (value) => appendFileSync(results, JSON.stringify({ time: new Date().toISOString(), run, tier, label, sha: provenance.sha, ...value }) + "\n")
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
const csrf = storage.cookies.find((cookie) => cookie.name === "aaw_csrf").value
const browser = await chromium.launch({ channel: "chrome", headless: false })
record({ kind: "environment", ...provenance, fixture: profile, browser: browser.version(), node: process.version, viewport: { width: 1440, height: 900 }, embedding: "unavailable-loopback", auth: "public", externalLLM: "not-configured", probeHash: createHash("sha256").update(readFileSync(fileURLToPath(import.meta.url))).digest("hex") })
let active = "setup"
let lastPage

async function newPage(viewport = { width: 1440, height: 900 }) {
  const context = await browser.newContext({ storageState: storage, viewport, locale: "zh-CN", timezoneId: "Asia/Shanghai" })
  await context.addInitScript(({ inputTiming }) => {
    const events = []
    window.__perfProbe = events
    for (const type of ["longtask", "event"]) {
      if (!PerformanceObserver.supportedEntryTypes.includes(type)) continue
      new PerformanceObserver((list) => {
        for (const e of list.getEntries()) events.push({ type: e.entryType, name: e.name, start: e.startTime, duration: e.duration, inputDelay: e.processingStart ? e.processingStart - e.startTime : null, processing: e.processingEnd ? e.processingEnd - e.processingStart : null })
      }).observe({ type, buffered: true, ...(type === "event" ? { durationThreshold: 16 } : {}) })
    }
    localStorage.setItem("novel_currentProjectId", "")
    if (inputTiming) {
      let serial = 0
      const metadata = (e) => ({ type: "input-boundary", name: e.type, start: performance.now(), trusted: e.isTrusted, inputType: e.inputType, composing: e.isComposing, length: e.target?.value?.length })
      for (const name of ["paste", "beforeinput", "compositionstart", "compositionupdate", "compositionend"]) {
        document.addEventListener(name, (e) => { events.push(metadata(e)); performance.mark(`diag:${name}`) }, true)
      }
      document.addEventListener("input", (e) => {
        const id = ++serial
        events.push({ ...metadata(e), boundary: "capture", id })
        performance.mark(`diag:input:${id}:capture`)
      }, true)
      document.addEventListener("input", (e) => {
        const id = serial
        events.push({ ...metadata(e), boundary: "handlers-returned", id })
        performance.mark(`diag:input:${id}:handlers-returned`)
        queueMicrotask(() => {
          events.push({ type: "input-boundary", name: "microtask-after-input", id, start: performance.now() })
          performance.mark(`diag:input:${id}:microtask`)
          requestAnimationFrame(() => requestAnimationFrame(() => events.push({ type: "input-boundary", name: "two-frames", id, start: performance.now() })))
        })
      })
      const original = Storage.prototype.setItem
      Storage.prototype.setItem = function(key, value) {
        const start = performance.now()
        try { return original.call(this, key, value) }
        finally { events.push({ type: "storage", start, duration: performance.now() - start, category: String(key).startsWith("draft_backup_") ? "draft-backup" : "other", codeUnits: String(value).length }) }
      }
    }
  }, { inputTiming: ["clipboard", "clipboard-profile", "ime", "persistence"].includes(mode) })
  const page = await context.newPage()
  lastPage = page
  page.setDefaultTimeout(12000)
  page.on("dialog", (dialog) => dialog.type() === "beforeunload" || (dialog.type() === "confirm" && dialog.message().includes("检测到本地暂存")) ? dialog.accept() : dialog.dismiss())
  page.on("pageerror", (error) => record({ kind: "pageerror", scenario: active, error: error.name, message: error.message.slice(0, 250) }))
  const owners = new WeakMap()
  page.on("request", (request) => owners.set(request, active))
  page.on("requestfinished", async (request) => {
    if (!request.url().startsWith(`${base}/api/`)) return
    try {
      const response = await request.response()
      const timing = request.timing()
      const sizes = await request.sizes()
      record({ kind: "request", scenario: owners.get(request), method: request.method(), route: new URL(request.url()).pathname.replace(/[0-9a-f]{8}-[0-9a-f-]{27}/gi, "{id}"), status: response.status(), serverHeaderMs: Number(await response.headerValue("x-request-time-ms")), timing, sizes })
    } catch { /* Page close can race metadata retrieval. */ }
  })
  page.on("requestfailed", (request) => record({ kind: "requestfailed", scenario: active, method: request.method(), error: request.failure()?.errorText }))
  return page
}

const routes = {
  writing: [`#workbench/${profile.project_id}/writing?chapter_index=1`, "#writing-editor"],
  world: [`#workbench/${profile.project_id}/world/objects`, ".world-object-table"],
  rp: [`#interaction/${profile.journey_id}`, ".rp-message"],
  generate: [`#workbench/${profile.project_id}/generate`, ".generate-page"],
}

async function goto(page, name) {
  await page.goto(`${base}/${routes[name][0]}`)
  const target = name === "writing" && page.viewportSize().width < 768
    ? page.getByLabel("移动端速记正文") : page.locator(routes[name][1]).first()
  await target.waitFor({ state: "visible" })
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
}

async function measured(page, name, operation) {
  active = name
  const start = performance.now()
  await page.evaluate(() => window.__perfProbe?.splice(0)).catch(() => {})
  try {
    const detail = await operation()
    await pause(100) // Observer delivery only; excluded from elapsed below.
    record({ kind: "sample", scenario: name, status: "ok", ...detail })
  } catch (error) {
    record({ kind: "sample", scenario: name, status: "failed", elapsedMs: performance.now() - start, error: error.message.slice(0, 400) })
    await page.screenshot({ path: path.join(out, `${run}-failure.png`) }).catch(() => {})
    throw error
  } finally {
    const events = await page.evaluate(() => window.__perfProbe?.splice(0) || []).catch(() => [])
    record({ kind: "browser-events", scenario: name, events })
  }
}

async function readApi(page, route, method = "GET", body) {
  const start = performance.now()
  const response = await page.context().request.fetch(`${base}/api${route}`, {
    method, headers: { Origin: base, "X-CSRF-Token": csrf, "X-Requested-With": "XMLHttpRequest" },
    ...(body === undefined ? {} : { data: body }), timeout: 60000,
  })
  const text = await response.text()
  record({ kind: "api", scenario: active, route: route.split("?")[0].replace(/[0-9a-f]{8}-[0-9a-f-]{27}/gi, "{id}"), method, status: response.status(), elapsedMs: performance.now() - start, bytes: Buffer.byteLength(text), serverHeaderMs: Number(response.headers()["x-request-time-ms"]) })
  return { response, data: text ? JSON.parse(text) : null }
}

async function saveButton(page) {
  if (!await page.locator("#btn-autosave").isVisible()) await page.locator('summary[aria-controls="writing-save-tools"]').click()
  await page.locator("#btn-autosave").click()
}

async function typeAndSave(page, duration = 60000, size = 3000) {
  const editor = page.locator("#writing-editor")
  const original = await editor.inputValue()
  const text = original.repeat(Math.ceil(size / original.length)).slice(0, size)
  await editor.fill(text)
  const start = performance.now()
  const samples = []
  while (performance.now() - start < duration) {
    const before = performance.now()
    await editor.press("End")
    await page.keyboard.insertText("行")
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    samples.push(performance.now() - before)
    await pause(200)
  }
  const expected = await editor.inputValue()
  const saveStart = performance.now()
  const responsePromise = page.waitForResponse((response) => response.request().method() === "PUT" && response.url().includes("/writing/drafts/"))
  await saveButton(page)
  const response = await responsePromise
  assert.equal(response.status(), 200)
  const saved = await response.json()
  const saveMs = performance.now() - saveStart
  const { data, response: read } = await readApi(page, `/writing/drafts/${saved.id}?novel_id=${profile.project_id}`)
  assert.equal(read.status(), 200)
  assert.equal(data.content, expected)
  record({ kind: "correctness", scenario: active, independentRead: true, savedCharacters: expected.length })
  // Restore the baseline body through the same public save path.
  await editor.fill(original)
  const restore = page.waitForResponse((r) => r.request().method() === "PUT" && r.url().includes("/writing/drafts/"))
  await saveButton(page)
  assert.equal((await restore).status(), 200)
  return { elapsedMs: performance.now() - start, typingRoundtripMs: samples, saveMs, inputSize: size }
}

async function baseline(page) {
  for (const name of ["writing", "world", "rp"]) {
    for (let i = 0; i < 5; i++) {
      const cold = await newPage()
      const start = performance.now()
      await measured(cold, `${name}-cold-${i}`, async () => { await goto(cold, name); return { elapsedMs: performance.now() - start, cache: "new-context" } })
      await cold.context().close()
    }
  }
  await goto(page, "writing")
  for (const size of [3000, 30000]) await measured(page, `typing-${size}`, () => typeAndSave(page, 60000, size))
  for (let i = 0; i < 30; i++) {
    await measured(page, "writing-switch", async () => {
      const before = performance.now()
      const chapter = i % 2 ? 1 : 2
      const button = page.getByRole("button", { name: new RegExp(`^打开第 ${chapter} 章`) }).first()
      if (!await button.isVisible()) await page.getByLabel("展开章节").click()
      await button.click()
      await page.waitForFunction((n) => document.querySelector("#writing-editor")?.value.startsWith(`第${n}章`), chapter)
      return { elapsedMs: performance.now() - before, batch: Math.floor(i / 10) + 1 }
    })
  }
  for (let i = 0; i < 30; i++) {
    for (const view of ["normal", "hot"]) {
      active = `world-api-${view}`
      const { data, response } = await readApi(page, `/world/entities?novel_id=${profile.project_id}&view_mode=${view}&q=${encodeURIComponent("河港")}&limit=20&skip=${(i%2)*20}`)
      assert.equal(response.status(), 200)
      assert.equal(data.items.length, 20)
      assert.equal(data.total, profile.entities)
    }
  }
  await goto(page, "world")
  for (let i = 0; i < 30; i++) {
    await measured(page, "world-filter", async () => {
      if (!await page.locator("#filter-q").isVisible()) await page.locator('[data-action="toggle-filter-panel"]').click()
      await page.locator("#filter-q").fill(i % 2 ? "河港" : "地点")
      const before = performance.now()
      await page.locator('[data-action="apply-filters"]').click()
      await page.waitForFunction((q) => new URLSearchParams(location.hash.split("?")[1]).get("q") === q, i % 2 ? "河港" : "地点")
      await page.locator(".world-object-table").waitFor()
      await page.waitForFunction(() => !state.loading)
      await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
      return { elapsedMs: performance.now() - before, batch: Math.floor(i/10)+1 }
    })
  }
  await goto(page, "rp")
  for (let i = 0; i < 30; i++) {
    const start = performance.now()
    await page.locator(".rp-story-scroll").evaluate((el, n) => { el.scrollTop = n % 2 ? el.scrollHeight : 0 }, i)
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    record({ kind: "sample", scenario: "rp-scroll", status: "ok", elapsedMs: performance.now() - start, batch: Math.floor(i/10)+1 })
  }
  active = "context-preview"
  await readApi(page, "/evidence/compilation/compile", "POST", { novel_id: profile.project_id, task: "继续河港的航行", scope: "chapter", chapter_index: 1, action: "writing.generate", reveal_mode: "author_safe", budget_tokens: 12000 })
  await page.setViewportSize({ width: 390, height: 844 })
  await goto(page, "writing")
  record({ kind: "narrow", overflow: await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1) })
  await page.screenshot({ path: path.join(out, `${run}-narrow.png`) })
}

async function worldProbe(page) {
  const assertIdleQueue = () => {
    const container = "novelcraft-e448-perf-db"
    assert.equal(execFileSync("docker", ["inspect", "--format", '{{index .Config.Labels "novelcraft.diagnostic"}}', container], { encoding: "utf8" }).trim(), "e448")
    const pending = execFileSync("docker", ["exec", container, "psql", "-U", "perf_test", "-d", "e448_perf_test", "-Atc", "SELECT count(*) FROM async_tasks WHERE status IN ('pending','running')"], { encoding: "utf8" }).trim()
    assert.equal(pending, "0", "World timing requires an idle diagnostic queue")
  }
  assertIdleQueue()
  for (let i = 0; i < 5; i++) {
    const cold = await newPage()
    await measured(cold, "world-cold", async () => {
      const start = performance.now()
      await goto(cold, "world")
      return { elapsedMs: performance.now() - start, iteration: i, cache: "new-context", ready: "locator-and-two-frames-upper-bound" }
    })
    await cold.context().close()
  }
  await goto(page, "world")
  for (const view of ["normal", "hot", "review-aliases"]) {
    const route = view === "review-aliases"
      ? `/world/aliases?novel_id=${profile.project_id}&display_state=review&limit=1&skip=0`
      : `/world/entities?novel_id=${profile.project_id}&view_mode=${view}&q=${encodeURIComponent("河港")}&limit=20`
    active = `warmup-${view}`
    await readApi(page, route)
    for (let i = 0; i < 30; i++) {
      if (i % 10 === 0) await pause(100)
      active = `world-api-${view}-batch-${Math.floor(i / 10) + 1}`
      const { data, response } = await readApi(page, route)
      assert.equal(response.status(), 200)
      assert.equal(data.total, view === "review-aliases" ? profile.review_aliases || 0 : profile.entities)
      record({ kind: "response-check", scenario: active, iteration: i, sha256: createHash("sha256").update(JSON.stringify(data)).digest("hex") })
    }
  }
  for (let i = 0; i < 30; i++) {
    await measured(page, "world-filter", async () => {
      if (!await page.locator("#filter-q").isVisible()) await page.locator('[data-action="toggle-filter-panel"]').click()
      const q = i % 2 ? "河港" : "地点"
      await page.locator("#filter-q").fill(q)
      const start = performance.now()
      await page.locator('[data-action="apply-filters"]').click()
      await page.waitForFunction((value) => new URLSearchParams(location.hash.split("?")[1]).get("q") === value, q)
      await page.waitForFunction(() => !state.loading)
      await page.locator(".world-object-table").waitFor()
      await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
      return { elapsedMs: performance.now() - start, batch: Math.floor(i / 10) + 1 }
    })
  }
  await page.setViewportSize({ width: 390, height: 844 })
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1))
  await page.screenshot({ path: path.join(out, `${run}-narrow.png`) })
  assertIdleQueue()
}

async function soak(page) {
  const cdp = await page.context().newCDPSession(page)
  await cdp.send("Performance.enable")
  for (let i = 0; i < 20; i++) { await goto(page, "writing"); await goto(page, "rp") }
  const start = performance.now()
  // No GC during interactive measurements. Fixed-data samples compare the same view after GC.
  for (let i = 0; performance.now() - start < 30 * 60000; i++) {
    active = "soak-fixed-data"
    await goto(page, "writing")
    await page.locator("#writing-editor").click()
    await page.keyboard.press("ArrowDown")
    await page.keyboard.insertText("暂")
    await page.keyboard.press("Backspace")
    await goto(page, "rp")
    await page.locator(".rp-story-scroll").evaluate((el) => { el.scrollTop = 0 })
    await pause(1000)
    record({ kind: "browser-events", scenario: active, events: await page.evaluate(() => window.__perfProbe?.splice(0) || []) })
    await cdp.send("HeapProfiler.collectGarbage")
    const metrics = Object.fromEntries((await cdp.send("Performance.getMetrics")).metrics.map(({ name, value }) => [name, value]))
    record({ kind: "memory", scenario: "fixed-data-route-cycle", iteration: i, elapsedSeconds: (performance.now() - start)/1000, metrics, postGC: true })
    await pause(30000)
  }
}

async function imports(page) {
  for (const format of ["txt", "epub"]) {
    active = `import-${format}`
    const { data: project, response } = await readApi(page, "/projects", "POST", { title: `诊断 ${tier} ${format}`, language: "zh" })
    assert.equal(response.status(), 201)
    await page.goto(`${base}/#project`)
    await page.waitForFunction(() => typeof state !== "undefined" && !state.loading)
    // Same project-selection setup used by e2e/helpers/workbench.js.
    await page.evaluate(async (projectData) => {
      localStorage.setItem("novel_currentProjectId", projectData.id)
      localStorage.setItem("novel_currentProject", JSON.stringify(projectData))
      state.currentProjectId = projectData.id
      state.currentProject = projectData
      await window.router.navigate("project")
    }, project)
    if (!await page.locator("#pv-import-file").isVisible()) await page.locator('[data-action="toggle-import"]').click()
    await page.locator("#pv-import-file").setInputFiles(path.join(out, `synthetic-${tier}.${format}`))
    const start = performance.now()
    const [result] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/imports/upload") && r.request().method() === "POST", { timeout: 60000 }),
      page.locator('[data-action="upload-file"]').click(),
    ])
    const data = await result.json()
    record({ kind: "import", format, status: result.status(), uploadMs: performance.now() - start, chapterCount: data.chapter_count, importedCount: data.imported_chapters?.length, projectId: project.id })
    assert.equal(result.status(), 201)
    await page.locator("#writing-tree-container").waitFor()
    record({ kind: "sample", scenario: active, status: "ok", elapsedMs: performance.now()-start, ready: "chapter-navigation" })
    const { data: chapters } = await readApi(page, `/writing/chapters?novel_id=${project.id}`)
    assert.equal(chapters.chapters.length, profile.chapters)
  }
}

async function recovery(page) {
  await goto(page, "writing")
  const editor = page.locator("#writing-editor")
  const original = await editor.inputValue()
  const expected = original + "\n断网恢复验证。"
  active = "offline-save-recovery"
  await page.context().setOffline(true)
  await editor.fill(expected)
  await pause(3800)
  assert.equal(await editor.inputValue(), expected)
  const backups = await page.evaluate(() => Object.keys(localStorage).filter((key) => key.startsWith("draft_backup_") && (localStorage.getItem(key) || "").includes("断网恢复验证")))
  assert(backups.length > 0)
  await page.context().setOffline(false)
  await page.reload()
  await editor.waitFor()
  // Existing recovery may require the author's explicit choice.
  if ((await editor.inputValue()) !== expected) {
    const restore = page.getByRole("button", { name: /恢复.*草稿|恢复本地|恢复备份/ }).first()
    if (await restore.isVisible()) await restore.click()
  }
  record({ kind: "correctness", scenario: active, backupPresent: true, refreshRestored: (await editor.inputValue()) === expected })
  assert.equal(await editor.inputValue(), expected)
  await editor.fill(original + "\n恢复后保存验证。")
  const done = page.waitForResponse((r) => r.url().includes("/writing/drafts/") && r.request().method() === "PUT")
  await saveButton(page)
  assert.equal((await done).status(), 200)
}

async function profilePaste(page, operation) {
  await goto(page, "writing")
  const editor = page.locator("#writing-editor")
  const original = await editor.inputValue()
  const cdp = await page.context().newCDPSession(page)
  await cdp.send("Profiler.enable")
  await cdp.send("Profiler.start")
  await cdp.send("Tracing.start", { categories: "devtools.timeline,v8.execute,blink.user_timing", transferMode: "ReturnAsStream" })
  if (operation) await operation()
  else {
  for (let i = 0; i < 5; i++) {
    for (const size of [3000, 30000]) {
      await measured(page, `paste-${size}`, async () => {
        const before = performance.now()
        await editor.fill(original.repeat(Math.ceil(size / original.length)).slice(0,size))
        await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
        return { elapsedMs: performance.now() - before, instrumented: true, iteration: i }
      })
      await pause(500)
    }
  }
  await editor.fill(original)
  }
  const ended = new Promise((resolve) => cdp.once("Tracing.tracingComplete", resolve))
  await cdp.send("Tracing.end")
  const { stream } = await ended
  let contents = ""
  for (;;) {
    const chunk = await cdp.send("IO.read", { handle: stream })
    contents += chunk.data
    if (chunk.eof) break
  }
  await cdp.send("IO.close", { handle: stream })
  writeFileSync(path.join(out, `${run}-trace.json`), contents)
  const cpu = await cdp.send("Profiler.stop")
  writeFileSync(path.join(out, `${run}.cpuprofile`), JSON.stringify(cpu.profile))
}

async function nativeControl(page) {
  await goto(page, "writing")
  const editor = page.locator("#writing-editor")
  const original = await editor.inputValue()
  const style = await editor.evaluate((el) => {
    const computed = getComputedStyle(el)
    return Object.fromEntries(["width","height","font","lineHeight","padding","boxSizing","letterSpacing"].map((key) => [key, computed[key]]))
  })
  for (let i=0; i<5; i++) {
    for (const size of [3000, 30000]) {
      await measured(page, `app-control-paste-${size}`, async () => {
        const start=performance.now()
        await editor.fill(original.repeat(Math.ceil(size/original.length)).slice(0,size))
        await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
        return {elapsedMs:performance.now()-start,iteration:i,heavyProfiler:false}
      })
      await pause(500)
    }
  }
  await editor.fill(original)
  const control = await newPage()
  await control.setContent('<textarea aria-label="native control"></textarea>')
  await control.locator("textarea").evaluate((el, values) => Object.assign(el.style, values), style)
  for (let i=0; i<5; i++) {
    for (const size of [3000, 30000]) {
      await measured(control, `native-paste-${size}`, async () => {
        const start=performance.now()
        await control.locator("textarea").fill(original.repeat(Math.ceil(size/original.length)).slice(0,size))
        await control.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
        return { elapsedMs:performance.now()-start,iteration:i,style }
      })
      await pause(500)
    }
  }
}


async function saveAndVerify(page, expected) {
  active = "writing-save-and-verify"
  const existing = await readApi(page, `/writing/drafts/${profile.first_draft_id}?novel_id=${profile.project_id}`)
  if (existing.data.content === expected) {
    record({ kind: "correctness", scenario: active, independentRead: true, alreadyPersisted: true, length: expected.length })
    return
  }
  const done = page.waitForResponse((r) => r.url().includes("/writing/drafts/") && r.request().method() === "PUT")
  await saveButton(page)
  const response = await done
  assert.equal(response.status(), 200)
  const saved = await response.json()
  const { data } = await readApi(page, `/writing/drafts/${saved.id}?novel_id=${profile.project_id}`)
  assert.equal(data.content, expected)
  record({ kind: "correctness", scenario: active, independentRead: true, length: expected.length })
}

async function persistenceProbe(page) {
  await goto(page, "writing")
  const editor = page.locator("#writing-editor")
  const original = await editor.inputValue()
  for (const size of [3000, 30000]) {
    const body = original.repeat(Math.ceil(size / original.length)).slice(0, size)
    await editor.fill(body)
    await saveAndVerify(page, body)
    await editor.evaluate((el) => { el.focus(); el.setSelectionRange(el.value.length, el.value.length) })
    await measured(page, `persistence-${size}`, async () => {
      const done = page.waitForResponse((r) => r.url().includes("/writing/drafts/") && r.request().method() === "PUT")
      const start = performance.now()
      await editor.press("x")
      const response = await done
      const elapsedMs = performance.now() - start
      assert.equal(response.status(), 200)
      const saved = await response.json()
      const { data } = await readApi(page, `/writing/drafts/${saved.id}?novel_id=${profile.project_id}`)
      assert.equal(data.content, body + "x")
      await pause(300)
      return { elapsedMs, autoSaveIncludesDebounce: true, independentRead: true }
    })
  }
  await editor.fill(original)
  await saveAndVerify(page, original)
  for (const chapter of [2, 1]) {
    const button = page.getByRole("button", { name: new RegExp(`^打开第 ${chapter} 章`) }).first()
    if (!await button.isVisible()) await page.getByLabel("展开章节").click()
    await button.click()
    await page.waitForFunction((n) => document.querySelector("#writing-editor")?.value.startsWith(`第${n}章`), chapter)
  }
  assert.equal(await editor.inputValue(), original)
  record({ kind: "correctness", scenario: "writing-chapter-return", exactContent: true })
}

async function worldChecks(page) {
  await goto(page, "world")
  if (!await page.locator("#filter-q").isVisible()) await page.locator('[data-action="toggle-filter-panel"]').click()
  await page.locator("#filter-q").fill("河港")
  await page.locator('[data-action="apply-filters"]').click()
  await page.waitForFunction(() => !state.loading)
  await page.locator(".world-view-options > summary").click()
  await page.locator('[data-action="set-object-view"][data-view-mode="card"]').click()
  const trigger = page.locator('[data-action="open-entity-detail"]').first()
  await trigger.click()
  await page.locator(".world-entity-editor").waitFor()
  await page.locator("#modal-close").click()
  assert.equal(await page.locator("#filter-q").inputValue(), "河港")
  record({ kind: "correctness", scenario: "world-detail-return", filterPreserved: true })
  await page.setViewportSize({ width: 390, height: 844 })
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1))
  active = "world-injected-load-failure"
  const pattern = "**/api/world/entities?*"
  await page.route(pattern, (route) => route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "合成诊断：列表暂不可用" }) }))
  await page.reload()
  await page.locator('.empty-state[role="alert"]').filter({ hasText: "世界对象加载失败" }).waitFor()
  await page.screenshot({ path: path.join(out, `${run}-failure-feedback.png`) })
  await page.unroute(pattern)
  await page.locator('[data-action="retry-objects-load"]').click()
  await page.locator('[data-action="open-entity-detail"]').first().waitFor()
  record({ kind: "correctness", scenario: active, expectedFailure: true, retryRecovered: true, narrowViewport: true })
}

async function clipboardProbe(page) {
  await goto(page, "writing")
  const editor = page.locator("#writing-editor")
  const original = await editor.inputValue()
  const style = await editor.evaluate((el) => {
    const computed = getComputedStyle(el)
    return Object.fromEntries(["width", "height", "font", "lineHeight", "padding", "boxSizing", "letterSpacing"].map((key) => [key, computed[key]]))
  })
  const control = await newPage()
  await control.route(`${base}/__performance-native`, (route) => route.fulfill({ contentType: "text/html", body: '<html lang="zh"><head><title>Native textarea diagnostic</title></head><body><textarea aria-label="native control"></textarea></body></html>' }))
  await control.goto(`${base}/__performance-native`)
  await control.locator("textarea").evaluate((el, values) => Object.assign(el.style, values), style)
  // Keep the existing text clipboard in memory only; never put it in evidence.
  const previousClipboard = execFileSync("pbpaste")
  const frames = (target) => target.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  try {
    for (let i = 0; i < 5; i++) {
      for (const size of [3000, 30000]) {
        const text = original.repeat(Math.ceil(size / original.length)).slice(0, size)
        const replacement = "改写航行记录。".repeat(Math.ceil(size / 8)).slice(0, size / 2)
        for (const [name, target, field] of [["app", page, editor], ["native", control, control.locator("textarea")]]) {
          await target.bringToFront()
          await field.fill("")
          await pause(400)
          execFileSync("pbcopy", { input: text })
          await measured(target, `${name}-clipboard-${size}`, async () => {
            const start = performance.now()
            await field.press("Meta+V")
            await frames(target)
            return { elapsedMs: performance.now() - start, iteration: i, inputTiming: true, heavyProfiler: mode === "clipboard-profile" }
          })
          assert.equal(await field.inputValue(), text)
          execFileSync("pbcopy", { input: "改" + text.slice(1) })
          await measured(target, `${name}-select-all-paste-${size}`, async () => {
            const start = performance.now()
            await field.press("Meta+A")
            await field.press("Meta+V")
            await frames(target)
            return { elapsedMs: performance.now() - start, iteration: i }
          })
          assert.equal(await field.inputValue(), "改" + text.slice(1))
          await field.press("Meta+Z")
          assert.equal(await field.inputValue(), text)
          await field.evaluate((el, length) => { el.focus(); el.setSelectionRange(length / 4, length * 3 / 4) }, size)
          execFileSync("pbcopy", { input: replacement })
          await measured(target, `${name}-replace-selection-${size}`, async () => {
            const start = performance.now()
            await field.press("Meta+V")
            await frames(target)
            return { elapsedMs: performance.now() - start, iteration: i }
          })
          assert.equal(await field.inputValue(), text.slice(0, size / 4) + replacement + text.slice(size * 3 / 4))
          await measured(target, `${name}-undo-${size}`, async () => {
            const start = performance.now()
            await field.press("Meta+Z")
            await frames(target)
            return { elapsedMs: performance.now() - start, iteration: i }
          })
          assert.equal(await field.inputValue(), text)
          await field.evaluate((el) => { el.focus(); el.setSelectionRange(el.value.length, el.value.length) })
          await measured(target, `${name}-continue-${size}`, async () => {
            const start = performance.now()
            await field.press("x")
            await frames(target)
            return { elapsedMs: performance.now() - start, iteration: i }
          })
          assert.equal(await field.inputValue(), text + "x")
          if (name === "app") await saveAndVerify(page, text + "x")
        }
      }
    }
  } finally {
    execFileSync("pbcopy", { input: previousClipboard })
  }
  await editor.fill(original)
  await saveAndVerify(page, original)
}

async function imeProbe(page) {
  await goto(page, "writing")
  const original = await page.locator("#writing-editor").inputValue()
  await page.evaluate(() => { document.title = "NovelCraft IME diagnostic"; window.__perfProbe.splice(0) })
  await page.locator("#writing-editor").focus()
  console.log(JSON.stringify({ status: "ime-ready", result: results, durationSeconds: 180 }))
  // Physical keys are supplied through the native CUA app, never insertText().
  await page.waitForFunction(() => window.__perfProbe.some((event) => event.name === "compositionstart"), undefined, { timeout: 90000 })
  for (let round = 0; round < 3; round++) {
    active = `native-ime-round-${round + 1}`
    const start = Date.now()
    await pause(60000)
    record({ kind: "ime-window", scenario: active, elapsedMs: Date.now() - start, timeOrigin: await page.evaluate(() => performance.timeOrigin), events: await page.evaluate(() => window.__perfProbe.splice(0)) })
    console.log(JSON.stringify({ status: "ime-round-done", round: round + 1 }))
  }
  console.log(JSON.stringify({ status: "ime-observation-complete", finishFile: `${results}.finish` }))
  const deadline = Date.now() + 120000
  while (!existsSync(`${results}.finish`) && Date.now() < deadline) await pause(250)
  assert(existsSync(`${results}.finish`), "Native input controller did not finish")
  const text = await page.locator("#writing-editor").inputValue()
  await saveAndVerify(page, text)
  await page.locator("#writing-editor").fill(original)
  await saveAndVerify(page, original)
}

async function contention(page) {
  active = "index-backlog-and-edit"
  const { data: project, response } = await readApi(page, "/projects", "POST", { title: "并发索引诊断", language: "zh" })
  assert.equal(response.status(), 201)
  const upload = await page.context().request.post(`${base}/api/imports/upload`, {
    headers: { Origin:base, "X-CSRF-Token":csrf, "X-Requested-With":"XMLHttpRequest" },
    multipart: { novel_id:project.id, file:{ name:"contention.txt",mimeType:"text/plain",buffer:readFileSync(path.join(out,"synthetic-L.txt")) } },
  })
  assert.equal(upload.status(),201)
  record({ kind:"contention", importedProjectId:project.id, chapters:300, scope:"index backlog with unavailable embedding; not an LLM workload" })
  await goto(page,"writing")
  await measured(page,active,()=>typeAndSave(page,60000,3000))
}

async function multiTab(page) {
  active="same-chapter-two-tabs"
  await goto(page,"writing")
  const second=await newPage()
  await goto(second,"writing")
  const original=await page.locator("#writing-editor").inputValue()
  assert.equal(await second.locator("#writing-editor").inputValue(),original)
  await page.locator("#writing-editor").fill(original+"\n第一标签页。")
  await second.locator("#writing-editor").fill(original+"\n第二标签页。")
  const [firstResult] = await Promise.all([
    page.waitForResponse((r)=>r.url().includes("/writing/drafts/")&&r.request().method()==="PUT"),
    saveButton(page),
  ])
  assert.equal(firstResult.status(),200)
  const [secondResult]=await Promise.all([
    second.waitForResponse((r)=>r.url().includes("/writing/drafts/")&&r.request().method()==="PUT"),
    saveButton(second),
  ])
  assert.equal(secondResult.status(),409)
  assert.equal(await second.locator("#writing-editor").inputValue(),original+"\n第二标签页。")
  const saved=await firstResult.json()
  const {data}=await readApi(page,`/writing/drafts/${saved.id}?novel_id=${profile.project_id}`)
  assert.equal(data.content,original+"\n第一标签页。")
  record({kind:"correctness",scenario:active,firstStatus:200,secondStatus:409,losingDraftPreserved:true,independentRead:true})
}

try {
  const page = await newPage()
  if (mode === "soak") await soak(page)
  else if (mode === "world") await worldProbe(page)
  else if (mode === "clipboard") await clipboardProbe(page)
  else if (mode === "clipboard-profile") await profilePaste(page, () => clipboardProbe(page))
  else if (mode === "ime") await imeProbe(page)
  else if (mode === "persistence") await persistenceProbe(page)
  else if (mode === "world-checks") await worldChecks(page)
  else if (mode === "baseline") await baseline(page)
  else if (mode === "imports") await imports(page)
  else if (mode === "recovery") await recovery(page)
  else if (mode === "profile") await profilePaste(page)
  else if (mode === "native-control") await nativeControl(page)
  else if (mode === "contention") await contention(page)
  else if (mode === "multi-tab") await multiTab(page)
  else {
    for (const name of ["writing", "world", "rp"]) {
      active = name
      await goto(page, name)
      record({ kind: "smoke", scenario: name, title: await page.title(), visible: await page.locator(routes[name][1]).count() })
      await page.screenshot({ path: path.join(out, `${run}-${name}.png`) })
    }
  }
  record({ kind: "complete", status: "ok" })
  console.log(JSON.stringify({ result: results, status: "ok" }))
} catch (error) {
  await lastPage?.screenshot({ path: path.join(out, `${run}-failure.png`) }).catch(() => {})
  record({ kind: "complete", status: "failed", error: error.message.slice(0, 400) })
  console.error(JSON.stringify({ result: results, status: "failed", error: error.message.slice(0, 400) }))
  process.exitCode = 1
} finally {
  await browser.close()
}
