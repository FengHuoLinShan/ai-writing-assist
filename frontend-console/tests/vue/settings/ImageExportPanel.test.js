import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"

const waitFor = (assertion, options = {}) => vi.waitFor(assertion, { timeout: 3500, ...options })
import ImageExportPanel from "../../../vue/views/settings/components/ImageExportPanel.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

const NOVEL = "11111111-1111-4111-8111-111111111111"
const PNG_BYTES = Uint8Array.from([
  137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 10,
  0, 0, 0, 7, 8, 2, 0, 0, 0, 190, 206, 75, 52, 0, 0, 0, 21, 73, 68, 65, 84,
  120, 218, 99, 148, 147, 59, 193, 128, 27, 48, 49, 224, 5, 131, 88, 26, 0,
  224, 122, 1, 18, 160, 56, 209, 96, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96,
  130,
])

function mapPageItem(title, index) {
  const pageId = `44444444-4444-4444-8444-${String(index).padStart(12, "0")}`
  return {
    category: "map_page",
    bucket: "maps",
    key: `map-atlas/${NOVEL}/pages/${pageId}/image.png`,
    content_type: "image/png",
    sha256: null,
    byte_size: null,
    page_id: pageId,
    title,
    novel_id: NOVEL,
  }
}

function pngBlob() {
  return new Blob([PNG_BYTES], { type: "image/png" })
}

function downloadSpy() {
  const downloads = []
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: () => "blob:export" })
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: () => {} })
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function () {
    downloads.push({ download: this.download, href: this.href })
  })
  return downloads
}

let confirmImpl
let api

beforeEach(() => {
  vi.clearAllMocks()
  vi.restoreAllMocks()
  confirmImpl = vi.fn(() => true)
  api = {
    world: {
      imageExportManifest: vi.fn(),
      fetchMapAtlasImage: vi.fn(async () => pngBlob()),
      fetchMapAtlasMask: vi.fn(async () => pngBlob()),
      fetchEntityImage: vi.fn(async () => pngBlob()),
    },
  }
  setBridgeOverrides({ api, confirm: confirmImpl })
  globalThis.createImageBitmap = vi.fn(async () => ({ close: vi.fn() }))
})

afterEach(() => {
  resetBridgeOverrides()
  delete globalThis.createImageBitmap
  vi.restoreAllMocks()
})

function mountPanel(props = {}) {
  return mount(ImageExportPanel, {
    props: { projectId: NOVEL, projectTitle: "测试作品", ...props },
  })
}

function findButton(wrapper, text) {
  return wrapper.findAll("button").find(button => button.text() === text)
}

describe("ImageExportPanel", () => {
  it("展示可导出数量并区分文字导出与图片包语义", async () => {
    api.world.imageExportManifest.mockResolvedValue({
      novel_id: NOVEL,
      objects: [
        mapPageItem("封面", 1),
        { ...mapPageItem("主角", 2), category: "world_full", title: "主角", entity_id: "e1", image_version: "v1" },
        { ...mapPageItem("主角", 3), category: "world_thumbnail", title: "主角", entity_id: "e1", image_version: "v1" },
      ],
    })
    const wrapper = mountPanel()
    await flushPromises()
    expect(api.world.imageExportManifest).toHaveBeenCalledWith(NOVEL)
    const text = wrapper.text()
    expect(text).toContain("导出图片包")
    expect(text).toContain("由浏览器在本机打包")
    expect(text).toContain("「导出作品」导出的是文字，由服务端生成")
    expect(text).toContain("可导出 3 个图片文件")
    expect(text).toContain("地图页 1 张")
    expect(text).toContain("世界对象图 2 张")
  })

  it("空项目显示空态且禁用导出", async () => {
    api.world.imageExportManifest.mockResolvedValue({ novel_id: NOVEL, objects: [] })
    const wrapper = mountPanel()
    await flushPromises()
    expect(wrapper.text()).toContain("还没有可导出的图片")
    expect(wrapper.find('[data-testid="image-export-start"]').attributes("disabled")).toBeDefined()
  })

  it("刷新清单重新请求并更新可导出数量", async () => {
    api.world.imageExportManifest.mockResolvedValueOnce({
      novel_id: NOVEL,
      objects: [mapPageItem("封面", 1)],
    })
    const wrapper = mountPanel()
    await flushPromises()
    expect(wrapper.text()).toContain("可导出 1 个图片文件")
    api.world.imageExportManifest.mockResolvedValueOnce({
      novel_id: NOVEL,
      objects: [mapPageItem("封面", 1), mapPageItem("内页", 2)],
    })
    await wrapper.find('[data-testid="image-export-refresh"]').trigger("click")
    await flushPromises()
    expect(api.world.imageExportManifest).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain("可导出 2 个图片文件")
  })

  it("非安全上下文（缺 crypto.subtle）给出降级提示并禁用", async () => {
    const ownSubtle = Object.getOwnPropertyDescriptor(globalThis.crypto, "subtle")
    Object.defineProperty(globalThis.crypto, "subtle", { value: undefined, configurable: true })
    try {
      api.world.imageExportManifest.mockResolvedValue({
        novel_id: NOVEL,
        objects: [mapPageItem("封面", 1)],
      })
      const wrapper = mountPanel()
      await flushPromises()
      expect(wrapper.text()).toContain("无法计算图片校验值")
      expect(wrapper.find('[data-testid="image-export-start"]').attributes("disabled")).toBeDefined()
    } finally {
      if (ownSubtle) Object.defineProperty(globalThis.crypto, "subtle", ownSubtle)
      else delete globalThis.crypto.subtle
    }
  })

  it("全部成功：下载 ZIP，文案只说图片包已生成（N 张）", async () => {
    api.world.imageExportManifest.mockResolvedValue({
      novel_id: NOVEL,
      objects: [mapPageItem("封面", 1)],
    })
    const downloads = downloadSpy()
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.find('[data-testid="image-export-start"]').trigger("click")
    await waitFor(() => expect(downloads).toHaveLength(1))
    expect(api.world.fetchMapAtlasImage).toHaveBeenCalled()
    expect(downloads[0].download).toMatch(/^测试作品-图片包-\d{8}T\d{6}Z\.zip$/)
    const done = wrapper.find('[data-testid="image-export-done"]')
    expect(done.text()).toContain("图片包已生成（1 张）")
    expect(done.text()).toContain("这不等于已备份，请把文件妥善保存到本机")
  })

  it("部分失败：失败项列出，重试成功后合并下载", async () => {
    api.world.imageExportManifest.mockResolvedValue({
      novel_id: NOVEL,
      objects: [mapPageItem("好图", 1), mapPageItem("坏图", 2)],
    })
    api.world.fetchMapAtlasImage.mockImplementation(async (_novelId, pageId) => {
      if (pageId.endsWith("000000000002")) throw new Error("请求已取消")
      return pngBlob()
    })
    const downloads = downloadSpy()
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.find('[data-testid="image-export-start"]').trigger("click")
    await waitFor(() => expect(wrapper.find('[data-testid="image-export-failures"]').exists()).toBe(true))
    const failures = wrapper.find('[data-testid="image-export-failures"]')
    expect(failures.text()).toContain("坏图")
    expect(failures.text()).toContain("未写入图片包")
    expect(downloads).toHaveLength(0)

    api.world.fetchMapAtlasImage.mockResolvedValue(pngBlob())
    await findButton(wrapper, "重试失败项").trigger("click")
    await waitFor(() => expect(downloads).toHaveLength(2))
    expect(downloads.every(entry => !/缺/.test(entry.download))).toBe(true)
    expect(wrapper.find('[data-testid="image-export-done"]').text()).toContain("图片包已生成（2 张）")
  })

  it("仍失败时确认生成不完整包并在文件名标明缺几张", async () => {
    api.world.imageExportManifest.mockResolvedValue({
      novel_id: NOVEL,
      objects: [mapPageItem("好图", 1), mapPageItem("坏图", 2)],
    })
    api.world.fetchMapAtlasImage.mockImplementation(async (_novelId, pageId) => {
      if (pageId.endsWith("000000000002")) throw new Error("请求已取消")
      return pngBlob()
    })
    const downloads = downloadSpy()
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.find('[data-testid="image-export-start"]').trigger("click")
    await waitFor(() => expect(wrapper.find('[data-testid="image-export-failures"]').exists()).toBe(true))
    confirmImpl.mockReturnValue(true)
    await wrapper.findAll("button").find(button => button.text().includes("仍要生成")).trigger("click")
    await waitFor(() => expect(downloads).toHaveLength(1))
    expect(confirmImpl).toHaveBeenCalledWith(expect.stringContaining("1 张图片导出失败"))
    expect(downloads[0].download).toMatch(/缺1张\.zip$/)
    const done = wrapper.find('[data-testid="image-export-done"]')
    expect(done.text()).toContain("缺少 1 张")
  })

  it("确认弹窗取消时不下载", async () => {
    api.world.imageExportManifest.mockResolvedValue({
      novel_id: NOVEL,
      objects: [mapPageItem("好图", 1), mapPageItem("坏图", 2)],
    })
    api.world.fetchMapAtlasImage.mockImplementation(async (_novelId, pageId) => {
      if (pageId.endsWith("000000000002")) throw new Error("请求已取消")
      return pngBlob()
    })
    const downloads = downloadSpy()
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.find('[data-testid="image-export-start"]').trigger("click")
    await waitFor(() => expect(wrapper.find('[data-testid="image-export-failures"]').exists()).toBe(true))
    confirmImpl.mockReturnValue(false)
    await wrapper.findAll("button").find(button => button.text().includes("仍要生成")).trigger("click")
    await flushPromises()
    await new Promise(resolve => setTimeout(resolve, 30))
    expect(downloads).toHaveLength(0)
    expect(wrapper.find('[data-testid="image-export-failures"]').exists()).toBe(true)
  })

  it("取消导出：中止请求且不下载任何文件", async () => {
    api.world.imageExportManifest.mockResolvedValue({
      novel_id: NOVEL,
      objects: [mapPageItem("慢图", 1)],
    })
    let releaseFetch
    api.world.fetchMapAtlasImage.mockImplementation(() => new Promise((resolve, reject) => {
      releaseFetch = { resolve, reject }
    }))
    const downloads = downloadSpy()
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.find('[data-testid="image-export-start"]').trigger("click")
    await waitFor(() => expect(wrapper.find('[data-testid="image-export-progress"]').exists()).toBe(true))
    await wrapper.find('[data-testid="image-export-cancel"]').trigger("click")
    releaseFetch.reject(new Error("请求已取消"))
    await waitFor(() => expect(wrapper.text()).toContain("已取消导出，未下载任何文件"))
    expect(downloads).toHaveLength(0)
  })
})
