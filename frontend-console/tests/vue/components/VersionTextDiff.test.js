import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import VersionTextDiff from "../../../vue/components/VersionTextDiff.vue"
import { buildVersionDiff } from "../../../shared/versionDiff.js"

const componentSource = readFileSync(resolve(process.cwd(), "vue/components/VersionTextDiff.vue"), "utf8")

function fieldDiff(oldText, newText) {
  return buildVersionDiff(String(oldText || ""), String(newText || ""))
}

describe("VersionTextDiff 安全渲染", () => {
  it("组件源码不使用 v-html（仅 {{ }} 按片段转义）", () => {
    expect(componentSource).not.toContain("v-html")
    expect(componentSource).not.toContain("innerHTML")
  })

  it("按片段渲染差异文本，危险字符不以元素出现", () => {
    const diff = fieldDiff("林澈走进北港。<img src=x onerror=alert(1)>", "林澈跑进旧港。")
    const wrapper = mount(VersionTextDiff, {
      props: { diff, leftLabel: "这次改动前", rightLabel: "现在" },
    })
    expect(wrapper.text()).toContain("这次改动前")
    expect(wrapper.text()).toContain("现在")
    expect(wrapper.find("img").exists()).toBe(false)
    expect(wrapper.find("script").exists()).toBe(false)
    expect(wrapper.text()).toContain("走进")
    expect(wrapper.text()).toContain("跑进")
    const marks = wrapper.findAll("mark")
    expect(marks.length).toBeGreaterThan(0)
    wrapper.unmount()
  })

  it("完全一致的文本显示一致提示", () => {
    const diff = fieldDiff("同一段文字", "同一段文字")
    const wrapper = mount(VersionTextDiff, { props: { diff } })
    expect(wrapper.text()).toContain("两个版本正文完全一致")
    wrapper.unmount()
  })

  it("单侧为空时显示占位说明", () => {
    const diff = fieldDiff("", "新增的一段")
    const wrapper = mount(VersionTextDiff, { props: { diff } })
    expect(wrapper.text()).toContain("此侧无对应段落")
    expect(wrapper.text()).toContain("新增的一段")
    wrapper.unmount()
  })

  it("缺失 stats/rows 时安全降级不抛错", () => {
    const wrapper = mount(VersionTextDiff, { props: { diff: {} } })
    expect(wrapper.text()).toContain("0 字")
    wrapper.unmount()
  })
})
