import { describe, expect, it } from "vitest"

import {
  buildCatalog,
  detectEntry,
  extractRelated,
  extractWikilinks,
  normalizeMatchKey,
  parseFrontmatter,
  pageTitle,
  registerPageTitle,
  resolveLinkTarget,
  scanPage,
  stripRoot,
} from "../../../../vue/views/world/bible/worldbookImportScope.js"

function catalogOf(entries) {
  return buildCatalog(entries.map(([path, size]) => ({ path, size: size || 10, file: null })))
}

describe("stripRoot 剥根规则（m1-contract 第 2 条冻结）", () => {
  it("≥2 段去首段，单段整段保留", () => {
    expect(stripRoot("理法之环/concepts/真名回响/理法之环.md")).toBe("concepts/真名回响/理法之环.md")
    expect(stripRoot("ring/concepts/x.md")).toBe("concepts/x.md")
    expect(stripRoot("单文件.md")).toBe("单文件.md")
  })
})

describe("frontmatter 与标题口径（与后端 _map_file 一致）", () => {
  it("解析受限 frontmatter，标题取 title/name 或文件名 stem", () => {
    const parsed = parseFrontmatter("---\ntitle: 理法之环\npage_type: concept\nrelated:\n  - \"[[星锻环]]\"\n  - 魔法 API\n---\n正文 [[双月节点阵列]]。")
    expect(parsed.frontmatter).toEqual({ title: "理法之环", page_type: "concept", related: ["[[星锻环]]", "魔法 API"] })
    expect(parsed.body).toBe("正文 [[双月节点阵列]]。")
    expect(pageTitle("concepts/理法之环.md", parsed.frontmatter)).toBe("理法之环")
    expect(pageTitle("concepts/潮汐城.md", {})).toBe("潮汐城")
  })

  it("非 frontmatter 内容原样作为正文", () => {
    expect(parseFrontmatter("正文开头")).toBeNull()
    expect(parseFrontmatter("---\n没有结束标记")).toBeNull()
  })

  it("读取后按 frontmatter 标题补录索引，aliases 不参与（契约第 4 条）", () => {
    const catalog = catalogOf([["vault/concepts/x.md"]])
    registerPageTitle(catalog, "concepts/x.md", { title: "潮汐之城", aliases: ["潮汐城"] })
    // frontmatter 标题命中
    expect(resolveLinkTarget("潮汐之城", catalog, [])).toEqual({ state: "unselected", relPath: "concepts/x.md" })
    // aliases 不是标题，不参与匹配
    expect(resolveLinkTarget("潮汐城", catalog, []).state).toBe("unresolved")
  })
})

describe("wikilink 与 related 提取（m1-contract 第 4 条）", () => {
  it("支持 [[名称]]、[[名称|显示文本]]、[[路径#段落]]", () => {
    const links = extractWikilinks("见 [[星锻环]]、[[真名回响/理法之环|本体]] 与 [[concepts/双月节点阵列.md#阵列结构]]。")
    expect(links).toEqual([
      { raw: "[[星锻环]]", target: "星锻环", alias: "", anchor: "" },
      { raw: "[[真名回响/理法之环|本体]]", target: "真名回响/理法之环", alias: "本体", anchor: "" },
      { raw: "[[concepts/双月节点阵列.md#阵列结构]]", target: "concepts/双月节点阵列.md", alias: "", anchor: "阵列结构" },
    ])
  })

  it("related 字符串与列表逐项拆分，可含 [[…]] 或纯名称", () => {
    expect(extractRelated({ related: "[[星锻环]]" })).toEqual([
      { raw: "[[星锻环]]", target: "星锻环", alias: "", anchor: "" },
    ])
    expect(extractRelated({ related: ["[[a|别名]]", "b#c", " 纯名称 "]})).toEqual([
      { raw: "[[a|别名]]", target: "a", alias: "", anchor: "" },
      { raw: "b#c", target: "b", anchor: "c", alias: "" },
      { raw: "纯名称", target: "纯名称", alias: "", anchor: "" },
    ])
    expect(extractRelated({})).toEqual([])
  })
})

describe("四态解析：路径优先、唯一标题次之、同名不猜身份", () => {
  const catalog = catalogOf([
    ["理法之环/concepts/理法之环.md"],
    ["理法之环/concepts/星锻环.md"],
    ["理法之环/places/星锻环.md"],
    ["理法之环/concepts/双月节点阵列.md"],
  ])

  it("显式路径优先命中 rel_path（忽略 .md 后缀与大小写）", () => {
    const selected = ["concepts/理法之环.md"]
    expect(resolveLinkTarget("concepts/理法之环.md", catalog, selected)).toEqual({ state: "resolved", relPath: "concepts/理法之环.md" })
    expect(resolveLinkTarget("Concepts/理法之环", catalog, selected)).toEqual({ state: "resolved", relPath: "concepts/理法之环.md" })
    expect(resolveLinkTarget("concepts/星锻环.md", catalog, selected)).toEqual({ state: "unselected", relPath: "concepts/星锻环.md" })
  })

  it("同名多候选 ambiguous；唯一标题命中未纳入时 unselected；无命中 unresolved", () => {
    expect(resolveLinkTarget("星锻环", catalog, []).state).toBe("ambiguous")
    expect(resolveLinkTarget("双月节点阵列", catalog, [])).toEqual({ state: "unselected", relPath: "concepts/双月节点阵列.md" })
    expect(resolveLinkTarget("不存在", catalog, []).state).toBe("unresolved")
    expect(normalizeMatchKey("  Concepts/双月节点阵列.MD ")).toBe("concepts/双月节点阵列")
  })
})

describe("scanPage 与入口检测", () => {
  const catalog = buildCatalog([
    { path: "理法之环/concepts/真名回响/理法之环.md", size: 100, file: null },
    { path: "理法之环/concepts/真名回响/本体定位.md", size: 50, file: null },
    { path: "理法之环/concepts/星锻环.md", size: 50, file: null },
    { path: "理法之环/assets/diagram.png", size: 9, file: null },
  ])

  it("扫描正文与 related，返回四态引用", () => {
    const content = "---\ntitle: 理法之环\nrelated:\n  - \"[[本体定位]]\"\n---\n参见 [[本体定位]]、[[星锻环]]、[[魔法 API]]。"
    const { links } = scanPage("concepts/真名回响/理法之环.md", content, catalog, ["concepts/真名回响/理法之环.md"])
    const byTarget = Object.fromEntries(links.map((link) => [link.target, link]))
    expect(byTarget["本体定位"].state).toBe("unselected")
    expect(byTarget["星锻环"].state).toBe("unselected")
    expect(byTarget["魔法 API"].state).toBe("unresolved")
    // related 与正文双链并存：related 来源标记 fromRelated，正文双链不标
    expect(links.filter((link) => link.target === "本体定位").map((link) => link.fromRelated)).toEqual([false, true])
  })

  it("入口检测：rel_path 含「理法之环」的 Markdown，最短路径优先，忽略非 Markdown", () => {
    const entry = detectEntry(catalog)
    expect(entry.relPath).toBe("concepts/真名回响/理法之环.md")
    expect(detectEntry(catalog, "不存在的名字")).toBeNull()
  })
})
