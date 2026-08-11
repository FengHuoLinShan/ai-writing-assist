import { lstat, mkdir, readFile, readdir, rename, unlink, writeFile } from "node:fs/promises"
import { randomUUID } from "node:crypto"
import { dirname, relative, resolve } from "node:path"

export const ROUTE_ISLAND_KEYS = Object.freeze([
  "vue/interactionIsland.js",
  "vue/settingsIslands.js",
  "vue/projectIsland.js",
  "vue/ragIsland.js",
  "vue/worldIsland.js",
  "vue/outlineIsland.js",
  "vue/generateIsland.js",
  "vue/writingIsland.js",
  "vue/mapIsland.js",
])

const EXTERNAL_REFERENCE = /^(?:https?:|data:|#)/i
const SAFE_RELATIVE_PATH = /^[A-Za-z0-9][A-Za-z0-9._-]*(?:\/[A-Za-z0-9][A-Za-z0-9._-]*)*$/

export const MAX_INVENTORY_BYTES = 65536
export const MAX_INVENTORY_ENTRIES = 512
export const LEAFLET_LICENSE_PATH = "licenses/leaflet-BSD-2-Clause.txt"
export const LEAFLET_MANIFEST_KEY = "node_modules/leaflet/dist/leaflet-src.js"

function isPlainObject(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false
  const prototype = Object.getPrototypeOf(value)
  return prototype === Object.prototype || prototype === null
}

export function safeRelativePath(value, label = "asset path") {
  if (typeof value !== "string" || !SAFE_RELATIVE_PATH.test(value)) {
    throw new Error(`${label} must be a non-empty safe relative path`)
  }
  if (
    value.includes("\\")
    || value.includes("?")
    || value.includes("#")
    || /\s/.test(value)
    || value.includes("//")
    || value.startsWith("/")
    || value.split("/").some((part) => part === "." || part === "..")
  ) {
    throw new Error(`${label} must not escape the production output root`)
  }
  return value
}

async function regularFileAt(outputRoot, relativePath, label) {
  const candidate = resolve(outputRoot, relativePath)
  const outputRelative = relative(outputRoot, candidate)
  if (
    outputRelative === ""
    || outputRelative.startsWith("..")
    || outputRelative.includes("../")
  ) {
    throw new Error(`${label} escapes the production output root`)
  }
  let stats
  try {
    stats = await lstat(candidate)
  } catch {
    throw new Error(`${label} is missing: ${relativePath}`)
  }
  if (!stats.isFile() || stats.isSymbolicLink()) {
    throw new Error(`${label} is not a regular file: ${relativePath}`)
  }
}

export function localIndexReferences(indexHtml) {
  const references = [...indexHtml.matchAll(/\b(?:src|href)="([^"]+)"/g)]
    .map((match) => match[1])
    .filter((value) => !EXTERNAL_REFERENCE.test(value))

  return references.map((reference) => {
    if (reference.startsWith("//")) {
      throw new Error("index asset reference must not use a protocol-relative URL")
    }
    return safeRelativePath(
      reference.startsWith("/") ? reference.slice(1) : reference,
      "index asset reference",
    )
  })
}

function assetPaths(record, key) {
  if (!isPlainObject(record)) {
    throw new Error(`manifest record must be an object: ${key}`)
  }
  if (typeof record.file !== "string") {
    throw new Error(`manifest record is missing file: ${key}`)
  }
  const paths = [safeRelativePath(record.file, `manifest file for ${key}`)]
  for (const field of ["css", "assets"]) {
    if (record[field] === undefined) continue
    if (!Array.isArray(record[field])) {
      throw new Error(`manifest ${field} must be an array: ${key}`)
    }
    for (const path of record[field]) {
      paths.push(safeRelativePath(path, `manifest ${field} for ${key}`))
    }
  }
  return paths
}

function referencesAreKnown(manifest, key, record) {
  for (const field of ["imports", "dynamicImports"]) {
    if (record[field] === undefined) continue
    if (!Array.isArray(record[field])) {
      throw new Error(`manifest ${field} must be an array: ${key}`)
    }
    for (const target of record[field]) {
      if (typeof target !== "string" || !Object.hasOwn(manifest, target)) {
        throw new Error(`manifest ${field} references an unknown entry: ${key}`)
      }
    }
  }
}

export async function collectManifestAssetPaths(manifest, outputRoot) {
  if (!isPlainObject(manifest)) throw new Error("asset manifest must be a plain object")

  const entries = Object.entries(manifest)
  const indexEntries = entries.filter(([, record]) => record?.isEntry && record?.src === "index.html")
  if (indexEntries.length !== 1) {
    throw new Error("asset manifest must contain exactly one index.html entry")
  }

  for (const routeKey of ROUTE_ISLAND_KEYS) {
    const routeRecord = manifest[routeKey]
    if (!isPlainObject(routeRecord) || routeRecord.isDynamicEntry !== true) {
      throw new Error(`asset manifest is missing dynamic route entry: ${routeKey}`)
    }
  }

  const declared = new Set()
  for (const [key, record] of entries) {
    referencesAreKnown(manifest, key, record)
    for (const path of assetPaths(record, key)) {
      await regularFileAt(outputRoot, path, `manifest asset for ${key}`)
      declared.add(path)
    }
  }
  return declared
}

async function recursiveFiles(root, prefix = "") {
  const entries = await readdir(resolve(root, prefix), { withFileTypes: true })
  const paths = []
  for (const entry of entries) {
    const path = prefix ? `${prefix}/${entry.name}` : entry.name
    if (entry.isDirectory()) {
      paths.push(...await recursiveFiles(root, path))
    } else if (entry.isFile()) {
      paths.push(path)
    } else {
      throw new Error(`production assets must be regular files: ${path}`)
    }
  }
  return paths
}

export async function verifyProductionOutput(outputRoot) {
  const indexPath = resolve(outputRoot, "index.html")
  const manifestPath = resolve(outputRoot, "asset-manifest.json")
  await regularFileAt(outputRoot, "index.html", "production index")
  await regularFileAt(outputRoot, "asset-manifest.json", "production manifest")

  const [indexHtml, manifestText] = await Promise.all([
    readFile(indexPath, "utf8"),
    readFile(manifestPath, "utf8"),
  ])
  let manifest
  try {
    manifest = JSON.parse(manifestText)
  } catch {
    throw new Error("asset manifest is not valid JSON")
  }

  const indexReferences = localIndexReferences(indexHtml)
  for (const reference of indexReferences) {
    await regularFileAt(outputRoot, reference, "index asset")
  }
  const leafletManifestRecord = manifest[LEAFLET_MANIFEST_KEY]
  if (!isPlainObject(leafletManifestRecord) || leafletManifestRecord.isDynamicEntry !== true) {
    throw new Error("production manifest does not contain the dynamic Leaflet entry")
  }
  const leafletImportOwners = Object.entries(manifest)
    .filter(([, record]) => (
      Array.isArray(record?.dynamicImports)
      && record.dynamicImports.includes(LEAFLET_MANIFEST_KEY)
    ))
    .map(([key]) => key)
  if (
    leafletImportOwners.length !== 1
    || leafletImportOwners[0] !== "vue/mapIsland.js"
  ) {
    throw new Error("Leaflet must be dynamically imported only by the map route island")
  }
  const manifestPaths = await collectManifestAssetPaths(manifest, outputRoot)
  await regularFileAt(outputRoot, LEAFLET_LICENSE_PATH, "Leaflet production license")
  const leafletLicense = await readFile(resolve(outputRoot, LEAFLET_LICENSE_PATH), "utf8")
  if (
    !leafletLicense.includes("BSD 2-Clause License")
    || !leafletLicense.includes("Volodymyr Agafonkin")
  ) {
    throw new Error("Leaflet production license is incomplete")
  }

  const assetsRoot = resolve(outputRoot, "assets")
  let generatedAssets
  try {
    generatedAssets = await recursiveFiles(assetsRoot, "")
  } catch (error) {
    if (error?.code === "ENOENT") throw new Error("production build does not contain assets directory")
    throw error
  }
  for (const asset of generatedAssets) {
    const declaredPath = `assets/${asset}`
    if (!manifestPaths.has(declaredPath)) {
      throw new Error(`generated production asset is absent from manifest: ${declaredPath}`)
    }
  }

  const publishedFiles = await recursiveFiles(outputRoot, "")
  const externalLeafletReferences = []
  for (const path of publishedFiles.filter((value) => /\.(?:html|js|css|json)$/.test(value))) {
    const contents = await readFile(resolve(outputRoot, path), "utf8")
    if (contents.includes("unpkg.com")) externalLeafletReferences.push(path)
  }
  if (externalLeafletReferences.length) {
    throw new Error(
      `production output still references unpkg.com: ${externalLeafletReferences.join(", ")}`,
    )
  }

  const leafletStyleFlags = await Promise.all(
    generatedAssets
      .filter((path) => path.endsWith(".css"))
      .map(async (path) => (
        await readFile(resolve(assetsRoot, path), "utf8")
      ).includes(".leaflet-container")),
  )
  if (!leafletStyleFlags.some(Boolean)) {
    throw new Error("production build does not contain Leaflet CSS")
  }

  const localhostApiBundles = []
  for (const asset of generatedAssets.filter((path) => path.endsWith(".js"))) {
    const contents = await readFile(resolve(assetsRoot, asset), "utf8")
    if (contents.includes("http://localhost:8000/api")) localhostApiBundles.push(asset)
  }
  if (localhostApiBundles.length) {
    throw new Error(
      `production bundles still contain localhost API defaults: ${localhostApiBundles.join(", ")}`,
    )
  }

  const inventory = new Set([
    "/",
    "/index.html",
    "/asset-manifest.json",
    "/asset-inventory.txt",
    `/${LEAFLET_LICENSE_PATH}`,
    ...indexReferences.map((path) => `/${path}`),
    ...[...manifestPaths].map((path) => `/${path}`),
  ])
  return {
    indexReferences,
    javascriptBundleCount: generatedAssets.filter((path) => path.endsWith(".js")).length,
    inventory: [...inventory].sort(),
  }
}

export async function writeAssetInventory(outputRoot, inventory) {
  const outputPath = resolve(outputRoot, "asset-inventory.txt")
  const normalized = [...new Set(inventory)].sort()
  if (normalized.length > MAX_INVENTORY_ENTRIES) {
    throw new Error(`asset inventory exceeds ${MAX_INVENTORY_ENTRIES} entries`)
  }
  for (const publicPath of normalized) {
    if (!publicPath.startsWith("/")) {
      throw new Error("asset inventory entries must be safe public absolute paths")
    }
    if (publicPath !== "/") {
      safeRelativePath(publicPath.slice(1), "asset inventory path")
    }
  }
  const content = `${normalized.join("\n")}\n`
  if (Buffer.byteLength(content, "utf8") > MAX_INVENTORY_BYTES) {
    throw new Error(`asset inventory exceeds ${MAX_INVENTORY_BYTES} bytes`)
  }
  await mkdir(dirname(outputPath), { recursive: true })
  const temporaryPath = `${outputPath}.tmp-${process.pid}-${randomUUID()}`
  try {
    await writeFile(temporaryPath, content, { encoding: "utf8", mode: 0o644 })
    await rename(temporaryPath, outputPath)
  } catch (error) {
    await unlink(temporaryPath).catch(() => {})
    throw error
  }
}
