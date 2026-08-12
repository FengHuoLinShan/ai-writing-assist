import { afterEach, describe, expect, it } from "vitest"
import { mkdir, mkdtemp, readFile, rm, symlink, unlink, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { resolve } from "node:path"

import {
  ROUTE_ISLAND_KEYS,
  MAX_INVENTORY_BYTES,
  MAX_INVENTORY_ENTRIES,
  verifyProductionOutput,
  writeAssetInventory,
} from "../scripts/productionAssetContract.mjs"

const temporaryRoots = []

async function makeOutput({ manifestMutator, extraAsset } = {}) {
  const root = await mkdtemp(resolve(tmpdir(), "ai-writing-assets-"))
  temporaryRoots.push(root)
  await mkdir(resolve(root, "assets"), { recursive: true })
  await mkdir(resolve(root, "shared"), { recursive: true })
  await writeFile(resolve(root, "styles.css"), "body{}")
  await writeFile(resolve(root, "shared/esc.js"), "")
  await writeFile(resolve(root, "index.html"), [
    '<link rel="stylesheet" href="styles.css">',
    '<script src="shared/esc.js"></script>',
    '<script type="module" src="assets/entry.js"></script>',
  ].join("\n"))

  const manifest = {
    "index.html": {
      file: "assets/entry.js",
      src: "index.html",
      isEntry: true,
      dynamicImports: [...ROUTE_ISLAND_KEYS],
    },
  }
  for (const [index, key] of ROUTE_ISLAND_KEYS.entries()) {
    const filename = `assets/route-${index}.js`
    manifest[key] = { file: filename, src: key, isDynamicEntry: true }
    await writeFile(resolve(root, filename), `export default ${index}`)
  }
  await writeFile(resolve(root, "assets/entry.js"), "export default null")
  if (extraAsset) await writeFile(resolve(root, extraAsset), "extra")
  manifestMutator?.(manifest)
  await writeFile(resolve(root, "asset-manifest.json"), JSON.stringify(manifest))
  return root
}

afterEach(async () => {
  await Promise.all(temporaryRoots.splice(0).map((root) => rm(root, { recursive: true })))
})

describe("production asset contract", () => {
  it("requires all route islands and writes a deterministic complete inventory", async () => {
    const root = await makeOutput()

    const verified = await verifyProductionOutput(root)
    await writeAssetInventory(root, verified.inventory)

    const inventory = await readFile(resolve(root, "asset-inventory.txt"), "utf8")
    expect(inventory.split("\n").filter(Boolean)).toEqual([...verified.inventory].sort())
    expect(verified.inventory).toEqual(expect.arrayContaining([
      "/",
      "/asset-manifest.json",
      "/asset-inventory.txt",
      "/assets/entry.js",
      "/shared/esc.js",
    ]))
  })

  it.each([
    ["requires exactly one index entry", (manifest) => { manifest.other = { file: "assets/entry.js", src: "index.html", isEntry: true } }, /exactly one index/],
    ["requires every route island", (manifest) => { delete manifest[ROUTE_ISLAND_KEYS[0]] }, /missing dynamic route/],
    ["rejects unknown manifest references", (manifest) => { manifest["index.html"].imports = ["missing"] }, /unknown entry/],
    ["rejects unsafe manifest paths", (manifest) => { manifest["index.html"].file = "../entry.js" }, /safe relative path|escape/],
    ["rejects unsafe nested manifest paths", (manifest) => { manifest["index.html"].file = "assets/.hidden.js" }, /safe relative path/],
    ["rejects missing manifest files", (manifest) => { manifest["index.html"].file = "assets/missing.js" }, /is missing/],
  ])("%s", async (_name, manifestMutator, expected) => {
    const root = await makeOutput({ manifestMutator })
    await expect(verifyProductionOutput(root)).rejects.toThrow(expected)
  })

  it("rejects generated chunks that are absent from the manifest", async () => {
    const root = await makeOutput({ extraAsset: "assets/undeclared.js" })
    await expect(verifyProductionOutput(root)).rejects.toThrow(/absent from manifest/)
  })

  it("retains the localhost API gate for every generated JavaScript chunk", async () => {
    const root = await makeOutput()
    await writeFile(resolve(root, "assets/entry.js"), "http://localhost:8000/api")
    await expect(verifyProductionOutput(root)).rejects.toThrow(/localhost API defaults/)
  })

  it("rejects external package references", async () => {
    const external = await makeOutput()
    await writeFile(resolve(external, "assets/entry.js"), "https://unpkg.com/package")
    await expect(verifyProductionOutput(external)).rejects.toThrow(/references unpkg\.com/)

    const unrelated = await makeOutput()
    await writeFile(
      resolve(unrelated, "assets/entry.js"),
      "https://notunpkg.com/package https://unpkg.com.evil/package",
    )
    await expect(verifyProductionOutput(unrelated)).resolves.toBeDefined()
  })

  it("rejects unsafe index references and symlinked manifest assets", async () => {
    const unsafeIndex = await makeOutput()
    await writeFile(resolve(unsafeIndex, "index.html"), '<script src="assets/.hidden.js"></script>')
    await expect(verifyProductionOutput(unsafeIndex)).rejects.toThrow(/safe relative path/)

    const symlinkedAsset = await makeOutput()
    const entry = resolve(symlinkedAsset, "assets/entry.js")
    await unlink(entry)
    await symlink("route-0.js", entry)
    await expect(verifyProductionOutput(symlinkedAsset)).rejects.toThrow(/not a regular file/)
  })

  it("enforces exact inventory limits before atomically replacing an existing inventory", async () => {
    const root = await makeOutput()
    const inventoryPath = resolve(root, "asset-inventory.txt")
    const exactEntryLimit = Array.from(
      { length: MAX_INVENTORY_ENTRIES },
      (_, index) => `/asset${index}`,
    )
    await writeAssetInventory(root, exactEntryLimit)
    expect((await readFile(inventoryPath, "utf8")).split("\n").filter(Boolean)).toHaveLength(
      MAX_INVENTORY_ENTRIES,
    )

    await expect(writeAssetInventory(root, [
      ...exactEntryLimit,
      "/one-too-many",
    ])).rejects.toThrow(/exceeds 512 entries/)
    const existing = await readFile(inventoryPath, "utf8")
    expect(existing.split("\n").filter(Boolean)).toHaveLength(MAX_INVENTORY_ENTRIES)

    await writeAssetInventory(root, [`/${"a".repeat(MAX_INVENTORY_BYTES - 2)}`])
    const boundaryInventory = await readFile(inventoryPath, "utf8")
    expect(Buffer.byteLength(boundaryInventory, "utf8")).toBe(MAX_INVENTORY_BYTES)
    await expect(writeAssetInventory(root, [`/${"a".repeat(MAX_INVENTORY_BYTES - 1)}`]))
      .rejects.toThrow(/exceeds 65536 bytes/)
    expect(await readFile(inventoryPath, "utf8")).toBe(boundaryInventory)
    expect(existing).not.toBe(boundaryInventory)
  })
})
