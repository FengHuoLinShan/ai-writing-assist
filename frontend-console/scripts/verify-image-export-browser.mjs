// Real Chromium download of the export panel; synthetic inputs only.
import assert from "node:assert/strict"
import { mkdir, readFile, writeFile } from "node:fs/promises"
import { resolve, join } from "node:path"
import { createServer } from "vite"
import { chromium } from "@playwright/test"

const [specPath, targetPath] = process.argv.slice(2)
assert(specPath && targetPath, "Usage: node scripts/verify-image-export-browser.mjs <spec.json> <output-dir>")
const target = resolve(targetPath)
await mkdir(target, { recursive: true, mode: 0o700 })
const spec = JSON.parse(await readFile(specPath, "utf8"))
const items = await Promise.all(spec.items.map(async item => ({
  ...item,
  bytes: (await readFile(item.bytes_file)).toString("base64"),
})))
const fixtureId = "virtual:image-export-verification"
const server = await createServer({
  appType: "custom", server: { host: "127.0.0.1", port: 0 }, logLevel: "error",
  plugins: [{
    name: "image-export-verification",
    resolveId: id => id === fixtureId ? fixtureId : null,
    load: id => id === fixtureId ? `export { createApp } from "vue";
      export { setBridgeOverrides } from "/vue/bridge/index.js";
      export { default as Panel } from "/vue/views/settings/components/ImageExportPanel.vue";` : null,
  }],
})
server.middlewares.use("/__image_export__", (_request, response) => {
  response.setHeader("Content-Type", "text/html; charset=utf-8")
  response.end('<!doctype html><meta name="viewport" content="width=device-width"><link rel="stylesheet" href="/styles.css"><link rel="stylesheet" href="/editorial-theme.css"><div class="project-settings-view"><div id="export-panel"></div></div>')
})
let browser
try {
  await server.listen()
  const address = server.httpServer.address()
  browser = await chromium.launch()
  const page = await browser.newPage({ viewport: { width: 390, height: 844 }, acceptDownloads: true })
  page.on("console", message => { if (message.type() === "error" || message.type() === "warning") console.error(message.text()) })
  page.on("pageerror", error => console.error(error.message))
  const pendingDownloads = []
  const downloads = []
  page.on("download", (download) => {
    const name = `package-${pendingDownloads.length + 1}.zip`
    downloads.push({ name, suggestedFilename: download.suggestedFilename() })
    pendingDownloads.push(download.saveAs(join(target, name)))
  })
  await page.goto(`http://127.0.0.1:${address.port}/__image_export__`)
  await page.evaluate(async ({ items }) => {
    const { createApp, setBridgeOverrides, Panel } = await import("/@id/virtual:image-export-verification")
    const payload = (item) => new Blob([Uint8Array.from(atob(item.bytes), byte => byte.charCodeAt(0))], { type: item.content_type })
    setBridgeOverrides({
      api: { world: {
        imageExportManifest: async () => ({ novel_id: items[0].novel_id, objects: items }),
        fetchMapAtlasImage: async (_novel, pageId) => payload(items.find(item => item.category === "map_page" && item.page_id === pageId)),
        fetchMapAtlasMask: async (_novel, pageId) => payload(items.find(item => item.category === "map_mask" && item.page_id === pageId)),
        fetchEntityImage: async (entityId, _novel, variant) => payload(items.find(item => item.category === `world_${variant}` && item.entity_id === entityId)),
      } },
      confirm: () => true,
    })
    createApp(Panel, { projectId: items[0].novel_id, projectTitle: "浏览器恢复验收" }).mount("#export-panel")
  }, { items })
  await page.getByTestId("image-export-start").click()
  await page.getByTestId("image-export-done").waitFor()
  await Promise.all(pendingDownloads)
  assert.equal(downloads.length, 1)
  assert.match(await page.getByTestId("image-export-done").innerText(), new RegExp(`图片包已生成（${items.length} 张）`))
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
  await page.screenshot({ path: join(target, "browser-390.png"), fullPage: true })
  const summary = {
    browser: await browser.version(), viewport: 390,
    packages: downloads, failures: 0, objects: items.length,
  }
  await writeFile(join(target, "browser-proof.json"), JSON.stringify(summary, null, 2))
  console.log(JSON.stringify(summary))
} finally {
  await browser?.close()
  await server.close()
}
