import { resolve } from "node:path"

import { verifyProductionOutput, writeAssetInventory } from "./productionAssetContract.mjs"

const outputRoot = resolve(process.cwd(), "dist")

try {
  const verified = await verifyProductionOutput(outputRoot)
  await writeAssetInventory(outputRoot, verified.inventory)
  console.log(
    `Production build verified (${verified.indexReferences.length} local references, `
      + `${verified.javascriptBundleCount} JavaScript bundle(s), `
      + `${verified.inventory.length} published asset path(s)).`,
  )
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error))
  process.exitCode = 1
}
