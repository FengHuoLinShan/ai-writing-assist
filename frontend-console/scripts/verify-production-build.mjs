import { access, readFile, readdir } from "node:fs/promises"
import { resolve } from "node:path"

const outputRoot = resolve(process.cwd(), "dist")
const indexPath = resolve(outputRoot, "index.html")
const indexHtml = await readFile(indexPath, "utf8")
const localReferences = [
  ...indexHtml.matchAll(/\b(?:src|href)="([^"]+)"/g),
]
  .map((match) => match[1])
  .filter((value) => !/^(?:https?:|data:|#)/.test(value))

const missing = []
for (const reference of localReferences) {
  const normalized = reference.replace(/^\/+/, "")
  try {
    await access(resolve(outputRoot, normalized))
  } catch {
    missing.push(reference)
  }
}

const assetFiles = await readdir(resolve(outputRoot, "assets"))
const javascriptFiles = assetFiles.filter((name) => name.endsWith(".js"))
const localhostApiBundles = []
for (const filename of javascriptFiles) {
  const contents = await readFile(resolve(outputRoot, "assets", filename), "utf8")
  if (contents.includes("http://localhost:8000/api")) {
    localhostApiBundles.push(filename)
  }
}

if (missing.length || localhostApiBundles.length) {
  if (missing.length) {
    console.error(`Missing production assets: ${missing.join(", ")}`)
  }
  if (localhostApiBundles.length) {
    console.error(
      `Production bundles still contain localhost API defaults: ${localhostApiBundles.join(", ")}`,
    )
  }
  process.exitCode = 1
} else {
  console.log(
    `Production build verified (${localReferences.length} local references, `
      + `${javascriptFiles.length} JavaScript bundle(s)).`,
  )
}
