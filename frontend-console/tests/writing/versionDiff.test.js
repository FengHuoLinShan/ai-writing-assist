import { describe, expect, it } from "vitest"

import { buildVersionDiff, renderVersionDiff } from "../../views/writing/versionDiff.js"

describe("versionDiff", () => {
  it("先对齐段落，再标记中文字符级替换", () => {
    const diff = buildVersionDiff(
      "第一段保持不变\n林澈走进北港。",
      "第一段保持不变\n林澈跑进旧港。",
    )

    expect(diff.stats).toMatchObject({
      unchangedParagraphs: 1,
      changedParagraphs: 1,
      addedParagraphs: 0,
      removedParagraphs: 0,
    })
    const changed = diff.rows.find((row) => row.type === "replace")
    expect(changed.leftSegments).toEqual(expect.arrayContaining([
      expect.objectContaining({ type: "delete", text: expect.stringContaining("走") }),
    ]))
    expect(changed.rightSegments).toEqual(expect.arrayContaining([
      expect.objectContaining({ type: "insert", text: expect.stringContaining("跑") }),
    ]))
  })

  it("分别统计新增、删除和字数差", () => {
    const diff = buildVersionDiff("保留\n删除段", "保留\n新增甲\n新增乙")

    expect(diff.stats.deltaChars).toBe(4)
    expect(diff.stats.changedParagraphs).toBe(1)
    expect(diff.stats.addedParagraphs).toBe(1)
    expect(diff.stats.removedParagraphs).toBe(0)
  })

  it("折叠长段未变化上下文，但允许作者展开", () => {
    const text = Array.from({ length: 9 }, (_, index) => `段落 ${index + 1}`).join("\n")
    const html = renderVersionDiff(buildVersionDiff(text, text), { esc: globalThis.esc })

    expect(html).toContain("两个版本正文完全一致")
    expect(html).toContain("writing-version-diff__collapsed")
    expect(html).toContain("折叠 5 个未变化段落")
  })

  it("超过复杂度上限时安全降级并保留首尾锚点", () => {
    const diff = buildVersionDiff("相同开头\n旧一\n旧二\n相同结尾", "相同开头\n新一\n新二\n相同结尾", {
      paragraphLcsLimit: 0,
      tokenLcsLimit: 0,
    })

    expect(diff.fallbackUsed).toBe(true)
    expect(diff.rows[0]).toMatchObject({ type: "equal", leftText: "相同开头" })
    expect(diff.rows.at(-1)).toMatchObject({ type: "equal", rightText: "相同结尾" })
    expect(diff.rows.some((row) => row.type === "replace")).toBe(true)
  })

  it("用完全一致的段落 hash 标记稳定可识别的移动", () => {
    const diff = buildVersionDiff("甲段\n乙段\n丙段", "乙段\n甲段\n丙段")
    const html = renderVersionDiff(diff, { esc: globalThis.esc })

    expect(diff.stats.movedParagraphs).toBe(1)
    expect(diff.stats.addedParagraphs).toBe(0)
    expect(diff.stats.removedParagraphs).toBe(0)
    expect(diff.rows).toEqual(expect.arrayContaining([
      expect.objectContaining({ type: "move-from", leftText: "甲段" }),
      expect.objectContaining({ type: "move-to", rightText: "甲段" }),
    ]))
    expect(html).toContain("移动 1 · 移出")
    expect(html).toContain("移动 1 · 移入")
    expect(html).toContain('data-move-id="move-1"')
    expect(html).not.toContain('<mark class="writing-version-diff__removed">甲段</mark>')
    expect(html).not.toContain('<mark class="writing-version-diff__added">甲段</mark>')
  })

  it("重复段落重排时按出现顺序配对，不误报新增或删除", () => {
    const diff = buildVersionDiff("甲段\n乙段\n甲段\n丙段", "甲段\n甲段\n乙段\n丙段")

    expect(diff.stats).toMatchObject({
      movedParagraphs: 1,
      addedParagraphs: 0,
      removedParagraphs: 0,
    })
    expect(diff.rows.filter((row) => row.type === "move-from")).toHaveLength(1)
    expect(diff.rows.filter((row) => row.type === "move-to")).toHaveLength(1)
  })

  it("显示空段落差异，并保留行内空白变化", () => {
    const diff = buildVersionDiff("甲 乙\n结尾", "甲  乙\n\n结尾")
    const html = renderVersionDiff(diff, { esc: globalThis.esc })

    expect(diff.stats.changedParagraphs).toBe(1)
    expect(diff.stats.addedParagraphs).toBe(1)
    expect(html).toContain("空段落")
    expect(html).toContain("writing-version-diff__removed")
    expect(html).toContain("writing-version-diff__added")
  })

  it("空段落与有内容段落互换时不误写成缺少对应段落", () => {
    for (const [left, right, emptySide] of [
      ["\n结尾", "新增\n结尾", 0],
      ["原文\n结尾", "\n结尾", 1],
    ]) {
      const html = renderVersionDiff(buildVersionDiff(left, right), { esc: globalThis.esc })
      const container = document.createElement("div")
      container.innerHTML = html
      const changedCells = container.querySelectorAll(".writing-version-diff__cell--replace")

      expect(changedCells[emptySide].textContent).toBe("空段落")
      expect(changedCells[emptySide].textContent).not.toContain("此侧无对应段落")
    }
  })

  it("极端长短不对称输入无需创建高对象开销的 LCS 行矩阵", () => {
    const left = Array.from({ length: 5_000 }, (_, index) => `旧段 ${index}`).join("\n")
    const diff = buildVersionDiff(left, "唯一新段", {
      paragraphLcsLimit: 10_000,
    })

    expect(diff.fallbackUsed).toBe(false)
    expect(diff.stats.changedParagraphs).toBe(1)
    expect(diff.stats.removedParagraphs).toBe(4_999)
    expect(diff.stats.addedParagraphs).toBe(0)
  })

  it("pre-wrap 单元格不引入模板缩进或外围换行", () => {
    const html = renderVersionDiff(buildVersionDiff("正文", "正文"), { esc: globalThis.esc })
    const container = document.createElement("div")
    container.innerHTML = html
    const cells = container.querySelectorAll(".writing-version-diff__cell")

    expect(cells[0].textContent).toBe("正文")
    expect(cells[1].textContent).toBe("正文")
  })

  it("转义正文和版本标签后再写入 Diff HTML", () => {
    const diff = buildVersionDiff("<script>alert(1)</script>", '<img src=x onerror="alert(2)">')
    const html = renderVersionDiff(diff, {
      esc: globalThis.esc,
      leftLabel: "<左侧>",
      rightLabel: '<img src="x">',
    })

    const container = document.createElement("div")
    container.innerHTML = html
    expect(container.textContent).toContain("<script>alert(1)</script>")
    expect(container.textContent).toContain('<img src=x onerror="alert(2)">')
    expect(container.querySelector("script")).toBeNull()
    expect(container.querySelector("img")).toBeNull()
    expect(html).toContain("&lt;左侧&gt;")
    expect(html).not.toContain("<script>alert(1)</script>")
    expect(html).not.toContain('<img src="x">')
  })

  it("两个空版本显示中性空态", () => {
    const html = renderVersionDiff(buildVersionDiff("", ""), { esc: globalThis.esc })
    expect(html).toContain("两个版本均无正文")
  })
})
