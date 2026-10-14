/**
 * imagePackageExport.js — G4b 作者手动导出图片包的浏览器打包逻辑。
 *
 * 包格式与 deploy/scripts/object_backup.py 的 unpack_package/read_manifest 对齐：
 * ZIP 成员恰好是 snapshots/<UTC 时间戳>/manifest.json、manifest.sha256 和
 * objects/<file>；清单 source_kind=author_export 且不携带 DB 快照三字段；
 * 每行 sha256、byte_size>0、status=ok、content_type。文件名只放在
 * objects/<file>，经 NFC、非法字符替换、单段 ≤255 字节与大小写不敏感去重。
 *
 * 依赖注入（fetchBytes/verifyImage/hash）保持本模块可在 Node 测试与浏览器
 * 复用同一份打包实现；Node 侧产物即跨语言验收喂给 Python 端的真实字节。
 */

import { Zip, ZipPassThrough } from "fflate"

export const MANIFEST_SCHEMA = "ai-writing-object-backup/v1"

// 单包上限（默认假设，待实测峰值内存再调）：条数封顶防止海量小对象拖垮
// 清单校验；字节封顶取保守值，超出即顺序分包，每包独立清单可依次恢复。
export const MAX_ITEMS_PER_PACKAGE = 2000
export const MAX_PACKAGE_BYTES = 512 * 1024 * 1024

// Linux 文件系统单个路径段（含扩展名）的字节上限。
export const MAX_FILENAME_SEGMENT_BYTES = 255

const ILLEGAL_FILENAME_CHARS = /[/\\:*?"<>|\u0000-\u001f\u007f]/g

export class ExportAbortedError extends Error {
  constructor() {
    super("导出已取消")
    this.name = "ExportAbortedError"
  }
}

function utf8Bytes(text) {
  return new TextEncoder().encode(text).length
}

function truncateToBytes(text, maxBytes) {
  if (utf8Bytes(text) <= maxBytes) return text
  let out = ""
  let used = 0
  for (const character of text) {
    const size = utf8Bytes(character)
    if (used + size > maxBytes) break
    out += character
    used += size
  }
  return out
}

/** 单段文件名：NFC、去非法字符与控制符、压缩空白、空名兜底、截断到字节上限。 */
export function normalizeFilenameSegment(raw, maxBytes = MAX_FILENAME_SEGMENT_BYTES) {
  const normalized = String(raw ?? "")
    .normalize("NFC")
    .replace(ILLEGAL_FILENAME_CHARS, "_")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/[. ]+$/, "")
  const fallback = normalized ? normalized : "未命名"
  const truncated = truncateToBytes(fallback, maxBytes)
  return truncated || "未命名"
}

function splitExtension(segment) {
  const dot = segment.lastIndexOf(".")
  if (dot <= 0) return { stem: segment, extension: "" }
  return { stem: segment.slice(0, dot), extension: segment.slice(dot) }
}

/**
 * 生成包内相对路径并做大小写不敏感去重（同包内唯一）。
 * usedNames 是包级 Set（存小写路径）；冲突时在最后一段扩展名前加 -2、-3…。
 */
export function buildPackagePath(item, usedNames, index = 1) {
  const title = normalizeFilenameSegment(item.title)
  let directorySegments
  let stem
  let extension
  if (item.category === "map_page") {
    directorySegments = ["地图"]
    stem = title
    extension = ".png"
  } else if (item.category === "map_mask") {
    directorySegments = ["地图蒙版"]
    stem = title
    extension = ".png"
  } else if (item.category === "world_full") {
    directorySegments = ["对象图片", title]
    stem = "完整图"
    extension = ".webp"
  } else if (item.category === "world_thumbnail") {
    directorySegments = ["对象图片", title]
    stem = "缩略图"
    extension = ".webp"
  } else {
    throw new Error(`未知的导出类别：${item.category}`)
  }
  const directory = directorySegments
    .map(segment => normalizeFilenameSegment(segment))
    .join("/")
  // 扩展名必须保留：词干按「段上限 − 扩展名字节数」截断。
  const fileSegment = `${
    normalizeFilenameSegment(stem, MAX_FILENAME_SEGMENT_BYTES - utf8Bytes(extension))
  }${extension}`
  let candidate = `${directory}/${fileSegment}`
  if (usedNames.has(candidate.toLowerCase())) {
    const { stem, extension } = splitExtension(candidate.split("/").pop())
    let suffix = index <= 1 ? 2 : index
    for (;;) {
      const stemWithSuffix = truncateToBytes(stem, MAX_FILENAME_SEGMENT_BYTES - utf8Bytes(`-${suffix}${extension}`))
      const next = `${directory}/${stemWithSuffix}-${suffix}${extension}`
      if (!usedNames.has(next.toLowerCase())) {
        candidate = next
        break
      }
      suffix += 1
      if (suffix > 9999) throw new Error("同名文件去重失败")
    }
  }
  usedNames.add(candidate.toLowerCase())
  return candidate
}

/** Python 端 read_manifest 要求的 %Y%m%dT%H%M%SZ UTC 时间戳。 */
export function utcPackageTimestamp(date = new Date()) {
  const pad = (value, width = 2) => String(value).padStart(width, "0")
  return (
    `${pad(date.getUTCFullYear(), 4)}${pad(date.getUTCMonth() + 1)}${pad(date.getUTCDate())}`
    + `T${pad(date.getUTCHours())}${pad(date.getUTCMinutes())}${pad(date.getUTCSeconds())}Z`
  )
}

/* 分包在同一秒内完成时仍需唯一时间戳：对上一时间戳按 UTC 加一秒进位。 */
function nextTimestamp(previous, now = new Date()) {
  const stamp = utcPackageTimestamp(now)
  if (!previous || stamp > previous) return stamp
  const bumped = new Date(Date.UTC(
    Number(previous.slice(0, 4)),
    Number(previous.slice(4, 6)) - 1,
    Number(previous.slice(6, 8)),
    Number(previous.slice(9, 11)),
    Number(previous.slice(11, 13)),
    Number(previous.slice(13, 15)) + 1,
  ))
  return utcPackageTimestamp(bumped)
}

function manifestRow(item, file, sha256, byteSize) {
  return {
    novel_id: item.novel_id,
    category: item.category,
    bucket: item.bucket,
    key: item.key,
    sha256,
    byte_size: byteSize,
    content_type: item.content_type,
    status: "ok",
    file,
  }
}

function buildManifestPayload(timestamp, rows) {
  const manifest = {
    schema: MANIFEST_SCHEMA,
    source_kind: "author_export",
    timestamp,
    // 打包器只在全部对象成功写入后才生成本清单；状态必须是 complete。
    status: "complete",
    // author_export 清单不得携带 DB 快照声明；三字段显式为 null。
    db_timestamp: null,
    db_sha256: null,
    db_dump: null,
    objects: rows,
  }
  return new TextEncoder().encode(`${JSON.stringify(manifest)}\n`)
}

async function sha256Hex(bytes, hash) {
  const digest = new Uint8Array(await hash(bytes))
  return Array.from(digest, value => value.toString(16).padStart(2, "0")).join("")
}

async function browserSha256(bytes) {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))
}

/** 浏览器解码校验：能被图片解码器接受才算有效（不声称与历史存储对账）。 */
export async function browserVerifyImage(bytes, contentType) {
  const bitmap = await createImageBitmap(new Blob([bytes], { type: contentType }))
  bitmap.close()
}

function zipEntries(entries) {
  return new Promise((resolve, reject) => {
    const chunks = []
    try {
      const zip = new Zip((error, chunk) => {
        if (error) {
          reject(error)
          return
        }
        if (chunk) chunks.push(chunk)
      })
      for (const entry of entries) {
        const member = new ZipPassThrough(entry.name)
        zip.add(member)
        member.push(entry.bytes, true)
      }
      zip.end()
      resolve(chunks)
    } catch (error) {
      reject(error)
    }
  })
}

/**
 * 逐项拉取、校验并打包；失败项不入包（partialFailures），取消抛 ExportAbortedError。
 *
 * items: 清单端点返回的 objects 行（含 title/novel_id 与拉取定位字段）。
 * fetchBytes(item): 返回 Uint8Array。
 * verifyImage(bytes, contentType): 解码校验，失败抛错。
 * hash(bytes): 返回 ArrayBuffer/Uint8Array 摘要。
 * onUpdate({done, total, packages}): 进度回调。
 * isCancelled(): 每项之间轮询的取消标记。
 */
export async function buildImagePackages(options) {
  const {
    items,
    fetchBytes,
    verifyImage = browserVerifyImage,
    hash = browserSha256,
    onUpdate = () => {},
    isCancelled = () => false,
    maxItemsPerPackage = MAX_ITEMS_PER_PACKAGE,
    maxPackageBytes = MAX_PACKAGE_BYTES,
    now = () => new Date(),
  } = options
  if (!items.length) {
    return { packages: [], failures: [], totalItems: 0 }
  }

  const failures = []
  const packages = []
  const usedNames = new Set()
  let rows = []
  let entries = []
  let packageBytes = 0
  let previousTimestamp = null
  let done = 0

  const finalizePackage = async () => {
    if (!rows.length) return
    const timestamp = nextTimestamp(previousTimestamp, now())
    previousTimestamp = timestamp
    const manifestBytes = buildManifestPayload(timestamp, rows)
    const manifestDigest = await sha256Hex(manifestBytes, hash)
    const prefix = `snapshots/${timestamp}`
    const packageEntries = [
      ...entries,
      { name: `${prefix}/manifest.json`, bytes: manifestBytes },
      { name: `${prefix}/manifest.sha256`, bytes: new TextEncoder().encode(`${manifestDigest}\n`) },
    ]
    const chunks = await zipEntries(packageEntries)
    packages.push({
      timestamp,
      blob: new Blob(chunks, { type: "application/zip" }),
      objectCount: rows.length,
      byteSize: packageBytes,
    })
    rows = []
    entries = []
    packageBytes = 0
  }

  for (const item of items) {
    if (isCancelled()) throw new ExportAbortedError()
    let bytes
    try {
      bytes = await fetchBytes(item)
    } catch (error) {
      failures.push({ item, reason: error?.message || "网络请求失败" })
      done += 1
      onUpdate({ done, total: items.length, packages: packages.length })
      continue
    }
    try {
      if (!bytes || bytes.length === 0) throw new Error("图片为空")
      const digest = await sha256Hex(bytes, hash)
      if (item.sha256 && digest !== item.sha256) {
        throw new Error("图片内容与服务端记录不一致")
      }
      if (item.byte_size && bytes.length !== item.byte_size) {
        throw new Error("图片大小与服务端记录不一致")
      }
      await verifyImage(bytes, item.content_type, item)
      const file = buildPackagePath(item, usedNames)
      entries.push({ name: `objects/${file}`, bytes })
      rows.push(manifestRow(item, file, digest, bytes.length))
      packageBytes += bytes.length
    } catch (error) {
      failures.push({ item, reason: error?.message || "图片校验失败" })
    }
    done += 1
    onUpdate({ done, total: items.length, packages: packages.length })
    if (rows.length >= maxItemsPerPackage || packageBytes >= maxPackageBytes) {
      await finalizePackage()
    }
  }
  if (isCancelled()) throw new ExportAbortedError()
  await finalizePackage()
  if (isCancelled()) throw new ExportAbortedError()

  return { packages, failures, totalItems: items.length }
}

/** 导出文件名：项目名 + 图片包 + UTC 时间戳；不完整包在文件名标明缺几张。 */
export function buildExportFileName(projectTitle, timestamp, missingCount = 0) {
  const safeTitle = normalizeFilenameSegment(projectTitle, 120)
  const missing = missingCount > 0 ? `-缺${missingCount}张` : ""
  return `${safeTitle}-图片包-${timestamp}${missing}.zip`
}
