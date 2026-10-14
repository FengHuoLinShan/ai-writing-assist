/**
 * generate-image-export-fixture.mjs — 用与浏览器完全相同的打包逻辑
 * （vue/views/settings/logic/imagePackageExport.js + fflate 流式 store）
 * 生成真实 ZIP 字节，供 Python 端 deploy/tests 的跨语言验收
 * （object_backup.unpack_package / read_manifest）消费。
 *
 * 用法：
 *   node scripts/generate-image-export-fixture.mjs <target-dir>
 *     固定样例：中文、emoji、同名、超 255 字节段、大小写冲突 + 1 个损坏项。
 *   node scripts/generate-image-export-fixture.mjs --from <spec.json> <target-dir>
 *     外部条目：spec = { items: [...含 bytes_file 的清单行], expect_failures: n }，
 *     用于恢复演练按合成清单生成浏览器产物。
 * 输出：<target-dir>/package-<n>.zip 与 fixture.json（期望行集合与文件名）。
 */

import { mkdir, readFile, writeFile } from "node:fs/promises"
import { join } from "node:path"

import {
  buildImagePackages,
} from "../vue/views/settings/logic/imagePackageExport.js"

const NOVEL = "11111111-1111-4111-8111-111111111111"
const MAP_BUCKET = "maps"
const WORLD_BUCKET = "world"

// PIL 可解码的真实最小图片（Python 端 valid_image 会实际解码）。
const PNG_BYTES = Uint8Array.from([
  137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 10,
  0, 0, 0, 7, 8, 2, 0, 0, 0, 190, 206, 75, 52, 0, 0, 0, 21, 73, 68, 65, 84,
  120, 218, 99, 148, 147, 59, 193, 128, 27, 48, 49, 224, 5, 131, 88, 26, 0,
  224, 122, 1, 18, 160, 56, 209, 96, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96,
  130,
])
const WEBP_BYTES = Uint8Array.from([
  82, 73, 70, 70, 58, 0, 0, 0, 87, 69, 66, 80, 86, 80, 56, 32, 46, 0, 0, 0,
  176, 1, 0, 157, 1, 42, 8, 0, 6, 0, 1, 64, 38, 37, 160, 2, 116, 186, 0, 4,
  48, 0, 0, 254, 241, 220, 143, 248, 13, 215, 197, 180, 203, 255, 189, 130,
  255, 221, 130, 255, 221, 130, 255, 91, 0, 0,
])

function pageId(index) {
  return `44444444-4444-4444-8444-${String(1000 + index).padStart(12, "0")}`
}

function entityId(index) {
  return `22222222-2222-4222-8222-${String(1000 + index).padStart(12, "0")}`
}

function versionId(index) {
  return `33333333-3333-4333-8333-${String(1000 + index).padStart(12, "0")}`
}

function mapPage(index, title, extra = {}) {
  const id = pageId(index)
  return {
    category: "map_page",
    bucket: MAP_BUCKET,
    key: `map-atlas/${NOVEL}/pages/${id}/attempts/token-${index}/image.png`,
    content_type: "image/png",
    sha256: null,
    byte_size: null,
    page_id: id,
    title,
    novel_id: NOVEL,
    ...extra,
  }
}

function mapMask(index, title) {
  const id = pageId(index)
  return {
    category: "map_mask",
    bucket: MAP_BUCKET,
    key: `map-atlas/${NOVEL}/pages/${id}/mask.png`,
    content_type: "image/png",
    sha256: null,
    byte_size: null,
    page_id: id,
    title,
    novel_id: NOVEL,
  }
}

function worldVariant(index, name, variant) {
  const entity = entityId(index)
  const version = versionId(index)
  return {
    category: `world_${variant}`,
    bucket: WORLD_BUCKET,
    key: `world-objects/${NOVEL}/entities/${entity}/images/${version}/${variant}.webp`,
    content_type: "image/webp",
    sha256: null,
    byte_size: null,
    entity_id: entity,
    image_version: version,
    title: name,
    novel_id: NOVEL,
  }
}

const items = [
  mapPage(1, "主世界"),
  mapPage(2, "主世界"), // 同名 → -2
  mapPage(3, "ABC"), // 与下一项大小写冲突
  mapPage(4, "abc"), // → abc-2
  mapPage(5, "🗺️ 精灵领地 🧝"),
  mapPage(6, "字".repeat(120)), // 超 255 字节段（截断 + 去重后缀仍受限）
  mapMask(1, "主世界"),
  worldVariant(1, "主角·林绪", "full"),
  worldVariant(1, "主角·林绪", "thumbnail"),
  worldVariant(2, "龙🐉岛", "full"),
  worldVariant(2, "龙🐉岛", "thumbnail"),
]

// 一张损坏对象：hash 校验失败不入包（模拟部分失败语义；仅固定样例模式使用）。
const broken = mapPage(7, "损坏的页", {
  sha256: "0".repeat(64),
  byte_size: 1,
})

async function main() {
  let spec = null
  let target = process.argv[2]
  if (target === "--from") {
    spec = JSON.parse(await readFile(process.argv[3], "utf8"))
    target = process.argv[4]
  }
  if (!target) {
    console.error(
      "usage: node scripts/generate-image-export-fixture.mjs [--from <spec.json>] <target-dir>",
    )
    process.exit(2)
  }
  await mkdir(target, { recursive: true })
  const outcome = spec
    ? await buildImagePackages({
      items: spec.items,
      fetchBytes: async item => new Uint8Array(await readFile(item.bytes_file)),
      verifyImage: async () => {},
      hash: async bytes => crypto.subtle.digest("SHA-256", bytes),
    })
    : await buildImagePackages({
      items: [...items, broken],
      fetchBytes: async (item) => (item.category.startsWith("world_") ? WEBP_BYTES : PNG_BYTES),
      verifyImage: async () => {},
      hash: async bytes => crypto.subtle.digest("SHA-256", bytes),
    })
  const expectedFailures = spec ? (spec.expect_failures ?? 0) : 1
  if (outcome.failures.length !== expectedFailures) {
    throw new Error(`fixture expected ${expectedFailures} failure(s), got ${outcome.failures.length}`)
  }
  const written = []
  for (const [index, pkg] of outcome.packages.entries()) {
    const name = `package-${index + 1}.zip`
    await writeFile(join(target, name), new Uint8Array(await pkg.blob.arrayBuffer()))
    written.push({ name, timestamp: pkg.timestamp, object_count: pkg.objectCount })
  }
  await writeFile(join(target, "fixture.json"), JSON.stringify({
    novel_id: spec ? spec.items[0]?.novel_id : NOVEL,
    buckets: spec
      ? {
        map: [...new Set(spec.items.filter(i => i.category.startsWith("map_")).map(i => i.bucket))][0],
        world: [...new Set(spec.items.filter(i => i.category.startsWith("world_")).map(i => i.bucket))][0],
      }
      : { map: MAP_BUCKET, world: WORLD_BUCKET },
    packages: written,
    expected_objects: outcome.totalItems - outcome.failures.length,
    expected_failures: outcome.failures.length,
    failure_keys: outcome.failures.map(failure => failure.item.key),
    source_kind: "author_export",
  }, null, 2))
  console.log(JSON.stringify({ packages: written, failures: outcome.failures.length }))
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
