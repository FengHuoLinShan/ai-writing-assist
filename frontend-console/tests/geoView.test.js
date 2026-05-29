/**
 * geoView 测试
 *
 * 覆盖生命周期、5 个子视图、地点树构建、历史时期和关系渲染。
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import geoView from "../views/geoView.js"

beforeEach(() => {
  state.currentProjectId = null
  state.currentSubView = null
  state.rightPanel = null
  geoView._locations = []
  geoView._locationTree = []
  geoView._eras = []
  geoView._edges = []
  geoView._selectedLocation = null
  geoView._apiAvailable = false
  vi.clearAllMocks()
})

// ============================================================
// onEnter
// ============================================================

describe("onEnter", () => {
  it("无项目时设置空状态", async () => {
    await geoView.onEnter()
    expect(geoView._locations).toEqual([])
    expect(geoView._eras).toEqual([])
    expect(geoView._edges).toEqual([])
  })

  it("有项目时并行加载数据", async () => {
    state.currentProjectId = "p1"
    api.geo.listLocations.mockResolvedValue({ items: [{ id: "l1", name: "王都" }] })
    api.geo.listEras.mockResolvedValue({ items: [{ id: "e1", name: "古代" }] })
    api.geo.listEdges.mockResolvedValue({ items: [{ id: "r1", source: "A", target: "B" }] })

    await geoView.onEnter()

    expect(geoView._locations).toHaveLength(1)
    expect(geoView._eras).toHaveLength(1)
    expect(geoView._edges).toHaveLength(1)
    expect(geoView._apiAvailable).toBe(true)
  })

  it("地点 API 失败时使用演示树", async () => {
    state.currentProjectId = "p1"
    api.geo.listLocations.mockRejectedValue(new Error("失败"))
    api.geo.listEras.mockResolvedValue({ items: [] })
    api.geo.listEdges.mockResolvedValue({ items: [] })

    await geoView.onEnter()

    expect(geoView._apiAvailable).toBe(false)
    expect(geoView._locationTree.length).toBeGreaterThan(0)
  })
})

// ============================================================
// render
// ============================================================

describe("render", () => {
  it("渲染子标签导航", async () => {
    const html = await geoView.render()
    expect(html).toContain("地点树")
    expect(html).toContain("地理关系")
    expect(html).toContain("历史时期")
    expect(html).toContain("简易地图")
  })
})

// ============================================================
// 地点树
// ============================================================

describe("地点树", () => {
  describe("_nestedList", () => {
    it("构建嵌套层级结构", () => {
      const items = [
        { id: "root", name: "世界", parent_location_id: undefined },
        { id: "city", name: "王都", parent_location_id: "root" },
        { id: "bld", name: "王宫", parent_location_id: "city" },
      ]
      // root 不带 parent_location_id，调用时传 root.id 为 parentId
      const tree = geoView._nestedList(items, "root")
      expect(tree).toHaveLength(1)
      expect(tree[0].name).toBe("王都")
      expect(tree[0].children).toHaveLength(1)
      expect(tree[0].children[0].name).toBe("王宫")
    })
  })

  describe("_onLocationClick", () => {
    it("选中地点并更新右侧面板", () => {
      geoView._locationTree = [{ id: "l1", name: "王都", level: "city" }]
      geoView._onLocationClick("l1")
      expect(geoView._selectedLocation?.name).toBe("王都")
      expect(state.rightPanel?.title).toBe("王都")
    })
  })
})

// ============================================================
// 历史时期
// ============================================================

describe("_renderEras", () => {
  it("空列表显示空状态", () => {
    const html = geoView._renderEras()
    expect(html).toContain("暂无历史时期")
  })

  it("渲染时期表格", () => {
    geoView._eras = [{ id: "e1", name: "古代", order_index: 1, summary: "过去" }]
    const html = geoView._renderEras()
    expect(html).toContain("古代")
    expect(html).toContain("过去")
  })
})

// ============================================================
// 地理关系
// ============================================================

describe("_renderEdges", () => {
  it("空列表显示空状态", () => {
    const html = geoView._renderEdges()
    expect(html).toContain("暂无地理关系")
  })

  it("渲染关系表格", () => {
    geoView._edges = [{ id: "e1", source: "王都", target: "旧王都", relation_type: "road_to", travel_time: "三日" }]
    const html = geoView._renderEdges()
    expect(html).toContain("王都")
    expect(html).toContain("旧王都")
  })
})

// ============================================================
// 事件绑定
// ============================================================

describe("_bindEvents", () => {
  it("导航子视图", () => {
    document.body.innerHTML = '<div id="workspace-content"><button data-action="nav-tree">地点树</button></div>'
    geoView._bindEvents()
    document.querySelector("button").click()
    expect(router.navigate).toHaveBeenCalledWith("geo", "tree")
  })

  it("地点点击触发 _onLocationClick", () => {
    const spy = vi.spyOn(geoView, "_onLocationClick").mockImplementation(() => {})
    document.body.innerHTML = '<div id="workspace-content"><span data-action="location-click" data-location-id="l1">王都</span></div>'
    geoView._bindEvents()
    document.querySelector("span").click()
    expect(spy).toHaveBeenCalledWith("l1")
    spy.mockRestore()
  })
})
