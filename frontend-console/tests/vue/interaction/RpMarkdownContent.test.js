import { describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"
import RpMarkdownContent from "../../../vue/views/interaction/RpMarkdownContent.vue"

describe("RP Markdown 正文", () => {
  it("把常用 Markdown 渲染为适合阅读的结构", () => {
    const wrapper = mount(RpMarkdownContent, {
      props: {
        source: [
          "## 雨夜来客",
          "",
          "**克莱恩**放下杯子，*低声*说道：",
          "",
          "- 先观察门外",
          "- 再检查怀表",
          "",
          "> 钟声比往常早了一刻。",
          "",
          "```text",
          "廷根，凌晨三点",
          "```",
          "",
          "[查看线索](https://example.com/clue)",
        ].join("\n"),
      },
    })

    expect(wrapper.get("h2").text()).toBe("雨夜来客")
    expect(wrapper.get("strong").text()).toBe("克莱恩")
    expect(wrapper.get("em").text()).toBe("低声")
    expect(wrapper.findAll("ul li").map((item) => item.text())).toEqual([
      "先观察门外",
      "再检查怀表",
    ])
    expect(wrapper.get("blockquote").text()).toContain("钟声比往常早了一刻")
    expect(wrapper.get("pre code").text()).toBe("廷根，凌晨三点")
    expect(wrapper.get("a").attributes()).toMatchObject({
      href: "https://example.com/clue",
      rel: "noopener noreferrer",
      target: "_blank",
    })
  })

  it("wiki 开启时把 [[名称]] 渲染为可点击引用，关闭时保持纯文本", async () => {
    const onWikiRef = vi.fn()
    const wrapper = mount(RpMarkdownContent, {
      props: {
        source: String.raw`北境见 [[潮门港]]，南方见 \[\[假引用\]\] 与 <img src=x onerror=alert(1)>。`,
        wiki: true,
        onWikiRef,
      },
    })

    const chip = wrapper.get("[data-action='open-wiki-ref']")
    expect(chip.text()).toBe("潮门港")
    expect(chip.attributes("data-wiki-ref")).toBe("潮门港")
    await chip.trigger("click")
    expect(onWikiRef).toHaveBeenCalledWith("潮门港", expect.anything())
    expect(wrapper.text()).toContain("[[假引用]]")
    expect(wrapper.find("img").exists()).toBe(false)

    const plain = mount(RpMarkdownContent, {
      props: { source: "北境见 [[潮门港]]。", wiki: false },
    })
    expect(plain.find("[data-action='open-wiki-ref']").exists()).toBe(false)
    expect(plain.text()).toContain("[[潮门港]]")
  })

  it("不执行模型返回的 HTML、脚本链接或远程图片", () => {
    const wrapper = mount(RpMarkdownContent, {
      props: {
        source: [
          '<img src=x onerror="alert(1)">',
          "",
          "[危险链接](javascript:alert(1))",
          "",
          "![远程图](https://example.com/tracker.png)",
        ].join("\n"),
      },
    })

    expect(wrapper.find("img").exists()).toBe(false)
    expect(wrapper.find("a").exists()).toBe(false)
    expect(wrapper.text()).toContain('<img src=x onerror="alert(1)">')
    expect(wrapper.get(".rp-markdown-link--blocked").text()).toBe("危险链接")
    expect(wrapper.get(".rp-markdown-image-alt").text()).toBe("〔图片：远程图〕")
  })
})
