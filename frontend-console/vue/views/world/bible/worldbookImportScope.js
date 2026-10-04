// 世界书导入的浏览器本地范围扫描（M2）。
//
// 职责：在作者已选择的目录内做纯本地解析——剥根、受限 frontmatter、
// Wiki 引用提取与四态解析——供导入面板在预览前圈定资料范围；
// 不发任何请求，服务端预览才是站内写入的唯一权威。
//
// 口径对齐 backend/modules/world/services/worldbuilding/worldbook_import_service.py：
// - stripRoot 与服务端 _strip_root 的冻结规则一致（≥2 段去首段，单段整段）；
// - 标题口径与 _map_file 一致（frontmatter title/name 或文件名 stem）；
// - 引用四态与 m1-contract 第 4 条一致（resolved/unselected/ambiguous/unresolved），
//   显式路径优先、唯一标题次之、同名多候选不猜身份；aliases 不参与标题匹配。

export const DEFAULT_ENTRY_HINT = "理法之环"

const MARKDOWN_SUFFIX = /\.(md)$/i

// 剥除所选根目录名：≥2 段去首段，单段整段即 rel_path（m1-contract 第 2 条冻结规则）。
export function stripRoot(path) {
  const parts = String(path || "").split("/")
  if (parts.length < 2) return String(path || "")
  return parts.slice(1).join("/")
}

// 匹配键：NFC + 折叠大小写 + 去结尾 .md 后缀（忽略后缀差异，m1-contract 第 4 条）。
//与服务端 NFC + casefold 归一化同语义，JavaScript 侧用 toLowerCase 折叠。
export function normalizeMatchKey(value) {
  const normalized = String(value || "").normalize("NFC").trim().toLowerCase()
  return normalized.replace(/\.md$/i, "")
}

// 与服务端 _map_file 同口径的受限 frontmatter 解析：---\n 开头、下一个 \n--- 结束，
// 顶层 key: value 与 key: 下的 "- item" 列表。只用于本地扫描提示，不承载校验。
export function parseFrontmatter(content) {
  const text = String(content || "")
  if (!text.startsWith("---\n")) return null
  const end = text.indexOf("\n---", 4)
  if (end === -1) return null
  const frontmatter = {}
  let currentList = null
  for (const line of text.slice(4, end).split(/\r?\n/)) {
    if (/^\s+-\s+/.test(line) && currentList) {
      currentList.push(line.replace(/^\s+-\s+/, "").trim().replace(/^["']+|["']+$/g, ""))
      continue
    }
    const match = /^([A-Za-z_][\w-]*):\s*(.*)$/.exec(line)
    if (!match) {
      currentList = null
      continue
    }
    const value = match[2].trim()
    if (value === "") {
      currentList = []
      frontmatter[match[1]] = currentList
    } else {
      currentList = null
      frontmatter[match[1]] = value.replace(/^["']|["']$/, "")
    }
  }
  return { frontmatter, body: text.slice(end + 4).replace(/^[\r\n]+/, "") }
}

// 页面标题：frontmatter title/name 或文件名 stem（服务端 _map_file 同口径）。
export function pageTitle(relPath, frontmatter) {
  const stem = stripRoot(relPath).replace(MARKDOWN_SUFFIX, "").split("/").pop() || relPath
  const declared = frontmatter?.title || frontmatter?.name
  const title = String(declared || stem).trim()
  return title.slice(0, 255) || "未命名资料"
}

// 从一段文本提取 [[目标]]、[[目标|显示文本]]、[[路径#段落]] 引用。
export function extractWikilinks(text) {
  const links = []
  for (const match of String(text || "").matchAll(/\[\[([^\][]+?)\]\]/g)) {
    const inner = match[1]
    const pipeIndex = inner.indexOf("|")
    const targetPart = (pipeIndex === -1 ? inner : inner.slice(0, pipeIndex)).trim()
    const alias = pipeIndex === -1 ? "" : inner.slice(pipeIndex + 1).trim()
    const hashIndex = targetPart.indexOf("#")
    const target = (hashIndex === -1 ? targetPart : targetPart.slice(0, hashIndex)).trim()
    const anchor = hashIndex === -1 ? "" : targetPart.slice(hashIndex + 1).trim()
    if (target) links.push({ raw: match[0], target, alias, anchor })
  }
  return links
}

// 展开 frontmatter related：字符串或列表，值可含 [[…]] 或纯名称，逐项拆分。
export function extractRelated(frontmatter) {
  const value = frontmatter?.related
  if (value === undefined || value === null || value === "") return []
  const items = Array.isArray(value) ? value : [value]
  const links = []
  for (const item of items) {
    const text = String(item ?? "")
    let found = false
    for (const match of text.matchAll(/\[\[([^\][]+?)\]\]/g)) {
      found = true
      const pipeIndex = match[1].indexOf("|")
      const targetPart = (pipeIndex === -1 ? match[1] : match[1].slice(0, pipeIndex)).trim()
      const hashIndex = targetPart.indexOf("#")
      links.push({
        raw: match[0],
        target: (hashIndex === -1 ? targetPart : targetPart.slice(0, hashIndex)).trim(),
        alias: "",
        anchor: hashIndex === -1 ? "" : targetPart.slice(hashIndex + 1).trim(),
      })
    }
    const plain = text.trim()
    if (!found && plain) {
      const hashIndex = plain.indexOf("#")
      links.push({
        raw: plain,
        target: (hashIndex === -1 ? plain : plain.slice(0, hashIndex)).trim(),
        alias: "",
        anchor: hashIndex === -1 ? "" : plain.slice(hashIndex + 1).trim(),
      })
    }
  }
  return links.filter((link) => link.target)
}

// 目录清单：entries 为 [{ path, size, file }]（path 为原始提交路径，含所选根名）。
// titleIndex 初始只含文件名 stem（零读取）；页面被读取后再按 frontmatter 标题补录。
export function buildCatalog(entries) {
  const items = []
  const byRelPath = new Map()
  const byRelKey = new Map()
  const titleIndex = new Map()
  for (const entry of entries) {
    const relPath = stripRoot(String(entry.path || ""))
    if (!relPath) continue
    const item = {
      relPath,
      originalPath: String(entry.path),
      size: Number(entry.size) || 0,
      file: entry.file || null,
      isMarkdown: MARKDOWN_SUFFIX.test(relPath),
      stem: stripRoot(relPath).replace(MARKDOWN_SUFFIX, "").split("/").pop() || relPath,
    }
    items.push(item)
    byRelPath.set(relPath, item)
    const relKey = normalizeMatchKey(relPath)
    if (!byRelKey.has(relKey)) byRelKey.set(relKey, relPath)
    addTitleIndex(titleIndex, item.stem, relPath)
  }
  return { items, byRelPath, byRelKey, titleIndex }
}

function addTitleIndex(titleIndex, title, relPath) {
  const key = normalizeMatchKey(title)
  if (!key) return
  const hits = titleIndex.get(key) || []
  if (!hits.includes(relPath)) hits.push(relPath)
  titleIndex.set(key, hits)
}

// 页面被读取后补录 frontmatter 标题（stem 与标题不同才追加，避免重复计数）。
export function registerPageTitle(catalog, relPath, frontmatter) {
  if (!catalog || !frontmatter) return
  const title = String(frontmatter.title || frontmatter.name || "").trim()
  const stem = stripRoot(relPath).replace(MARKDOWN_SUFFIX, "").split("/").pop() || relPath
  if (title && normalizeMatchKey(title) !== normalizeMatchKey(stem)) {
    addTitleIndex(catalog.titleIndex, title, relPath)
  }
}

// 引用四态解析：显式路径优先命中 rel_path；其次唯一标题命中；
// 同名多候选 ambiguous（不按名称猜身份）；无命中 unresolved；
// 唯一命中但目标未纳入本次范围 unselected（m1-contract 第 4 条）。
export function resolveLinkTarget(target, catalog, selectedRelPaths) {
  const key = normalizeMatchKey(target)
  if (!key) return { state: "unresolved", relPath: "" }
  let relPath = ""
  if (key.includes("/")) {
    relPath = catalog.byRelKey.get(key) || ""
  } else {
    const hits = catalog.titleIndex.get(key) || []
    if (hits.length > 1) return { state: "ambiguous", relPath: "" }
    relPath = hits[0] || ""
  }
  if (!relPath) return { state: "unresolved", relPath: "" }
  if (selectedRelPaths.includes(relPath)) return { state: "resolved", relPath }
  return { state: "unselected", relPath }
}

// 扫描单页：正文 wikilink + frontmatter related，返回 frontmatter 与带四态的引用清单。
export function scanPage(relPath, content, catalog, selectedRelPaths) {
  const parsed = parseFrontmatter(content)
  const frontmatter = parsed ? parsed.frontmatter : {}
  const body = parsed ? parsed.body : String(content || "")
  const links = [
    ...extractWikilinks(body).map((link) => ({ ...link, fromRelated: false })),
    ...extractRelated(frontmatter).map((link) => ({ ...link, fromRelated: true })),
  ]
  const resolved = links.map((link) => {
    const hit = resolveLinkTarget(link.target, catalog, selectedRelPaths)
    return { ...link, state: hit.state, targetRelPath: hit.relPath }
  })
  return { frontmatter, links: resolved }
}

// 入口检测：rel_path 含提示名（默认「理法之环」）的 Markdown，取最短路径优先。
export function detectEntry(catalog, hint = DEFAULT_ENTRY_HINT) {
  if (!catalog) return null
  const needle = String(hint || "").trim()
  if (!needle) return null
  const hits = catalog.items.filter(
    (item) => item.isMarkdown && item.relPath.includes(needle),
  )
  hits.sort(
    (a, b) => a.relPath.length - b.relPath.length || a.relPath.localeCompare(b.relPath),
  )
  return hits[0] || null
}
