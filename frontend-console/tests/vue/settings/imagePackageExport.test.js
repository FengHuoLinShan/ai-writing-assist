import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { Unzip } from "fflate"
import {
  MAX_FILENAME_SEGMENT_BYTES,
  MAX_ITEMS_PER_PACKAGE,
  ExportAbortedError,
  browserVerifyImage,
  buildExportFileName,
  buildImagePackages,
  buildPackagePath,
  normalizeFilenameSegment,
  utcPackageTimestamp,
} from "../../../vue/views/settings/logic/imagePackageExport.js"

const NOVEL = "11111111-1111-4111-8111-111111111111"
const MAP_BUCKET = "maps"

// PIL 生成的 10x7 真实 PNG（与 Python 端 PIL 解码兼容）
function pngBytes() {
  return Uint8Array.from([
    137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 10,
    0, 0, 0, 7, 8, 2, 0, 0, 0, 190, 206, 75, 52, 0, 0, 0, 21, 73, 68, 65, 84,
    120, 218, 99, 148, 147, 59, 193, 128, 27, 48, 49, 224, 5, 131, 88, 26, 0,
    224, 122, 1, 18, 160, 56, 209, 96, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96,
    130,
  ])
}

function mapPageItem(overrides = {}) {
  return {
    category: "map_page",
    bucket: MAP_BUCKET,
    key: `map-atlas/${NOVEL}/pages/44444444-4444-4444-8444-000000000001/image.png`,
    content_type: "image/png",
    page_id: "44444444-4444-4444-8444-000000000001",
    title: "封面",
    novel_id: NOVEL,
    ...overrides,
  }
}

function unzipNames(bytes) {
  return new Promise((resolve, reject) => {
    const names = []
    try {
      const unzip = new Unzip((file) => {
        names.push(file.name)
        file.ondata = () => {}
        file.start()
      })
      unzip.push(Uint8Array.from(bytes), true)
      resolve(names)
    } catch (error) {
      reject(error)
    }
  })
}

async function readZipMembers(bytes, expectedCount) {
  const members = new Map()
  await new Promise((resolve, reject) => {
    let pending = expectedCount
    const unzip = new Unzip((file) => {
      const chunks = []
      file.ondata = (error, chunk, final) => {
        if (error) {
          reject(error)
          return
        }
        chunks.push(chunk)
        if (final) {
          members.set(file.name, chunks)
          pending -= 1
          if (pending === 0) resolve()
        }
      }
      file.start()
    })
    unzip.push(Uint8Array.from(bytes), true)
  })
  return members
}

function concat(chunks) {
  const size = chunks.reduce((sum, chunk) => sum + chunk.length, 0)
  const out = new Uint8Array(size)
  let offset = 0
  for (const chunk of chunks) {
    out.set(chunk, offset)
    offset += chunk.length
  }
  return out
}

async function sha256Hex(bytes) {
  const digest = await crypto.subtle.digest("SHA-256", bytes)
  return Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, "0")).join("")
}

const passthroughVerify = async () => {}
const passthroughHash = async bytes => crypto.subtle.digest("SHA-256", bytes)

beforeEach(() => {
  vi.clearAllMocks()
})

describe("文件名段规范化", () => {
  it("NFC 规范化并替换非法字符与控制符", () => {
    expect(normalizeFilenameSegment("café")).toBe("café") // 已是 NFC
    expect(normalizeFilenameSegment("e\u0301")).toBe("e\u0301".normalize("NFC"))
    expect(normalizeFilenameSegment("a/b\\c:d*e?f\"g<h>i|j")).toBe("a_b_c_d_e_f_g_h_i_j")
    expect(normalizeFilenameSegment("a\u0000b\u001f")).toBe("a_b_")
    expect(normalizeFilenameSegment("  多  个 空白  ")).toBe("多 个 空白")
    expect(normalizeFilenameSegment("名字...")).toBe("名字")
  })

  it("空名与全非法名兜底为未命名", () => {
    expect(normalizeFilenameSegment("")).toBe("未命名")
    expect(normalizeFilenameSegment("///")).toBe("___")
    expect(normalizeFilenameSegment(null)).toBe("未命名")
  })

  it("emoji 保留且超长段按 UTF-8 字节截断", () => {
    const emoji = "🗺️".repeat(200)
    const truncated = normalizeFilenameSegment(emoji)
    expect(new TextEncoder().encode(truncated).length).toBeLessThanOrEqual(MAX_FILENAME_SEGMENT_BYTES)
    expect(truncated).toContain("🗺️")
    const long = "字".repeat(200)
    expect(new TextEncoder().encode(normalizeFilenameSegment(long)).length)
      .toBeLessThanOrEqual(MAX_FILENAME_SEGMENT_BYTES)
  })
})

describe("包内路径与大小写不敏感去重", () => {
  it("四类对象落到可读目录", () => {
    const used = new Set()
    expect(buildPackagePath(mapPageItem(), used)).toBe("地图/封面.png")
    expect(buildPackagePath(mapPageItem({ category: "map_mask", title: "封面" }), used))
      .toBe("地图蒙版/封面.png")
    expect(buildPackagePath(mapPageItem({ category: "world_full", title: "主角" }), used))
      .toBe("对象图片/主角/完整图.webp")
    expect(buildPackagePath(mapPageItem({ category: "world_thumbnail", title: "主角" }), used))
      .toBe("对象图片/主角/缩略图.webp")
  })

  it("同名按扩展名前 -2、-3 递增", () => {
    const used = new Set()
    expect(buildPackagePath(mapPageItem(), used)).toBe("地图/封面.png")
    expect(buildPackagePath(mapPageItem(), used)).toBe("地图/封面-2.png")
    expect(buildPackagePath(mapPageItem(), used)).toBe("地图/封面-3.png")
  })

  it("大小写冲突视为同名", () => {
    const used = new Set()
    expect(buildPackagePath(mapPageItem({ title: "ABC" }), used)).toBe("地图/ABC.png")
    expect(buildPackagePath(mapPageItem({ title: "abc" }), used)).toBe("地图/abc-2.png")
  })

  it("去重后缀仍满足单段 255 字节", () => {
    const used = new Set()
    const long = "字".repeat(130)
    buildPackagePath(mapPageItem({ title: long }), used)
    const second = buildPackagePath(mapPageItem({ title: long }), used)
    const segment = second.split("/").pop()
    expect(new TextEncoder().encode(segment).length).toBeLessThanOrEqual(MAX_FILENAME_SEGMENT_BYTES)
    expect(segment).toMatch(/-2\.png$/)
  })
})

describe("时间戳与文件名", () => {
  it("UTC 打包时间戳格式", () => {
    expect(utcPackageTimestamp(new Date(Date.UTC(2026, 9, 14, 8, 30, 5))))
      .toBe("20261014T083005Z")
  })

  it("导出文件名标注缺张数", () => {
    expect(buildExportFileName("我的作品", "20261014T083005Z", 0))
      .toBe("我的作品-图片包-20261014T083005Z.zip")
    expect(buildExportFileName("我的作品", "20261014T083005Z", 3))
      .toBe("我的作品-图片包-20261014T083005Z-缺3张.zip")
  })
})

describe("打包器 buildImagePackages", () => {
  it("产出可通过结构校验的真实 ZIP（含中文名）", async () => {
    const item = mapPageItem()
    const { packages, failures } = await buildImagePackages({
      items: [item],
      fetchBytes: async () => pngBytes(),
      verifyImage: passthroughVerify,
      hash: passthroughHash,
    })
    expect(failures).toEqual([])
    expect(packages).toHaveLength(1)
    const blob = packages[0].blob
    const bytes = new Uint8Array(await blob.arrayBuffer())
    const members = await readZipMembers(bytes, 3)
    const names = [...members.keys()]
    expect(names).toContain(`snapshots/${packages[0].timestamp}/manifest.json`)
    expect(names).toContain(`snapshots/${packages[0].timestamp}/manifest.sha256`)
    expect(names).toContain("objects/地图/封面.png")
    const manifest = JSON.parse(new TextDecoder().decode(concat(members.get(`snapshots/${packages[0].timestamp}/manifest.json`))))
    expect(manifest.schema).toBe("ai-writing-object-backup/v1")
    expect(manifest.source_kind).toBe("author_export")
    expect(manifest.status).toBe("complete")
    expect(manifest.db_timestamp).toBeNull()
    expect(manifest.db_sha256).toBeNull()
    expect(manifest.db_dump).toBeNull()
    expect(manifest.objects).toHaveLength(1)
    const row = manifest.objects[0]
    expect(row).toMatchObject({
      novel_id: NOVEL,
      category: "map_page",
      bucket: MAP_BUCKET,
      key: item.key,
      content_type: "image/png",
      status: "ok",
      file: "地图/封面.png",
      byte_size: pngBytes().length,
    })
    expect(row.sha256).toBe(await sha256Hex(pngBytes()))
    const digestFile = new TextDecoder().decode(concat(members.get(`snapshots/${packages[0].timestamp}/manifest.sha256`))).trim()
    expect(digestFile).toBe(await sha256Hex(concat(members.get(`snapshots/${packages[0].timestamp}/manifest.json`))))
  })

  it("地图页与 DB 摘要/大小不一致时判失败且不入包", async () => {
    const item = mapPageItem({ sha256: "0".repeat(64), byte_size: 999 })
    const { packages, failures } = await buildImagePackages({
      items: [item],
      fetchBytes: async () => pngBytes(),
      verifyImage: passthroughVerify,
      hash: passthroughHash,
    })
    expect(packages).toHaveLength(0)
    expect(failures).toHaveLength(1)
    expect(failures[0].reason).toContain("不一致")
  })

  it("零字节与解码失败不入包，清单只含成功行", async () => {
    const items = [
      mapPageItem({ title: "好图", page_id: "44444444-4444-4444-8444-00000000000a", key: `map-atlas/${NOVEL}/pages/44444444-4444-4444-8444-00000000000a/image.png` }),
      mapPageItem({ title: "空图", page_id: "44444444-4444-4444-8444-00000000000b", key: `map-atlas/${NOVEL}/pages/44444444-4444-4444-8444-00000000000b/image.png` }),
      mapPageItem({ title: "坏图", page_id: "44444444-4444-4444-8444-00000000000c", key: `map-atlas/${NOVEL}/pages/44444444-4444-4444-8444-00000000000c/image.png` }),
    ]
    const { packages, failures } = await buildImagePackages({
      items,
      fetchBytes: async (current) => (current.title === "空图" ? new Uint8Array(0) : pngBytes()),
      verifyImage: async (bytes, contentType, currentItem) => {
        if (currentItem?.title === "坏图") throw new Error("无法解码")
      },
      hash: passthroughHash,
    })
    expect(failures.map(failure => failure.item.title)).toEqual(["空图", "坏图"])
    expect(packages).toHaveLength(1)
    const blob = packages[0].blob
    const names = await unzipNames(new Uint8Array(await blob.arrayBuffer()))
    const members = await readZipMembers(new Uint8Array(await blob.arrayBuffer()), names.length)
    const manifestName = names.find(name => name.endsWith("manifest.json"))
    const manifest = JSON.parse(new TextDecoder().decode(concat(members.get(manifestName))))
    expect(manifest.objects.map(row => row.file)).toEqual(["地图/好图.png"])
  })

  it("网络失败按失败处理并继续后续项", async () => {
    const items = [
      mapPageItem({ title: "断网", page_id: "44444444-4444-4444-8444-00000000000d", key: `map-atlas/${NOVEL}/pages/44444444-4444-4444-8444-00000000000d/image.png` }),
      mapPageItem({ title: "正常", page_id: "44444444-4444-4444-8444-00000000000e", key: `map-atlas/${NOVEL}/pages/44444444-4444-4444-8444-00000000000e/image.png` }),
    ]
    const { packages, failures } = await buildImagePackages({
      items,
      fetchBytes: async (item) => {
        if (item.title === "断网") throw new Error("请求已取消")
        return pngBytes()
      },
      verifyImage: passthroughVerify,
      hash: passthroughHash,
    })
    expect(failures).toHaveLength(1)
    expect(packages[0].objectCount).toBe(1)
  })

  it("超过单包条数上限时顺序分包，各包独立清单", async () => {
    const items = Array.from({ length: MAX_ITEMS_PER_PACKAGE + 2 }, (_, index) => (
      mapPageItem({
        title: `页${index}`,
        page_id: `44444444-4444-4444-8444-${String(index).padStart(12, "0")}`,
        key: `map-atlas/${NOVEL}/pages/44444444-4444-4444-8444-${String(index).padStart(12, "0")}/image.png`,
      })
    ))
    const { packages } = await buildImagePackages({
      items,
      fetchBytes: async () => pngBytes(),
      verifyImage: passthroughVerify,
      hash: passthroughHash,
    })
    expect(packages.map(pkg => pkg.objectCount)).toEqual([MAX_ITEMS_PER_PACKAGE, 2])
    const stamps = packages.map(pkg => pkg.timestamp)
    expect(new Set(stamps).size).toBe(stamps.length)
    for (const pkg of packages) {
      const members = await readZipMembers(
        new Uint8Array(await pkg.blob.arrayBuffer()),
        pkg.objectCount + 2,
      )
      const manifestName = `snapshots/${pkg.timestamp}/manifest.json`
      const manifest = JSON.parse(new TextDecoder().decode(concat(members.get(manifestName))))
      expect(manifest.objects).toHaveLength(pkg.objectCount)
      expect(manifest.timestamp).toBe(pkg.timestamp)
      const allowed = new Set([
        manifestName,
        manifestName.replace("manifest.json", "manifest.sha256"),
        ...manifest.objects.map(row => `objects/${row.file}`),
      ])
      expect(new Set([...members.keys()])).toEqual(allowed)
    }
  })

  it("取消抛出 ExportAbortedError 且不产出任何包", async () => {
    let fetched = 0
    const promise = buildImagePackages({
      items: [mapPageItem(), mapPageItem({ title: "第二张" })],
      fetchBytes: async () => {
        fetched += 1
        return pngBytes()
      },
      verifyImage: passthroughVerify,
      hash: passthroughHash,
      isCancelled: () => fetched >= 1,
    })
    await expect(promise).rejects.toBeInstanceOf(ExportAbortedError)
  })

  it("最后清单摘要等待期间取消，不返回可下载的包", async () => {
    let cancelled = false
    let releaseManifestHash
    let hashCalls = 0
    const outcome = buildImagePackages({
      items: [mapPageItem()],
      fetchBytes: async () => pngBytes(),
      verifyImage: passthroughVerify,
      hash: async (bytes) => {
        hashCalls += 1
        if (hashCalls === 2) {
          await new Promise((resolve) => { releaseManifestHash = resolve })
        }
        return passthroughHash(bytes)
      },
      isCancelled: () => cancelled,
    })
    const rejection = expect(outcome).rejects.toBeInstanceOf(ExportAbortedError)
    await vi.waitFor(() => expect(releaseManifestHash).toBeTypeOf("function"))
    cancelled = true
    releaseManifestHash()
    await rejection
  })

  it("空清单返回空结果", async () => {
    const outcome = await buildImagePackages({
      items: [],
      fetchBytes: async () => pngBytes(),
      verifyImage: passthroughVerify,
      hash: passthroughHash,
    })
    expect(outcome).toEqual({ packages: [], failures: [], totalItems: 0 })
  })
})

describe("browserVerifyImage", () => {
  afterEach(() => {
    delete globalThis.createImageBitmap
  })

  it("经 createImageBitmap 解码并关闭", async () => {
    const close = vi.fn()
    globalThis.createImageBitmap = vi.fn(async () => ({ close }))
    await browserVerifyImage(pngBytes(), "image/png")
    expect(globalThis.createImageBitmap).toHaveBeenCalledOnce()
    expect(close).toHaveBeenCalled()
  })

  it("解码失败向上抛错", async () => {
    globalThis.createImageBitmap = vi.fn(async () => {
      throw new Error("decode failed")
    })
    await expect(browserVerifyImage(pngBytes(), "image/png")).rejects.toThrow("decode failed")
  })
})
