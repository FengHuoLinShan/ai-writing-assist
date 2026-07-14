import { describe, expect, it, vi } from "vitest"
import {
  MAP_PATH_PROFILES,
  drawMapPaths,
  hitTestPath,
  normalizePathState,
  pathNodesFor,
  representativePathPoint,
  samplePathGeometry,
  simplifyPathNodes,
  simplifyPathToLimit,
} from "../views/mapPathRenderer.js"

describe("mapPathRenderer", () => {
  it("兼容 layers/path_nodes 读取形状", () => {
    expect(normalizePathState({ layers: [{ id: "l" }], path_nodes: [{ id: "n" }] })).toMatchObject({
      path_layers: [{ id: "l" }],
      nodes: [{ id: "n" }],
    })
  })

  it("简化手绘节点但保留首尾", () => {
    const points = Array.from({ length: 40 }, (_, index) => ({ q: index / 10, r: Math.sin(index / 10) * 0.01 }))
    const result = simplifyPathNodes(points, 0.08)
    expect(result.length).toBeLessThan(points.length)
    expect(result[0]).toEqual(points[0])
    expect(result.at(-1)).toEqual(points.at(-1))
    expect(simplifyPathToLimit(points, 2).nodes.length).toBeLessThanOrEqual(2)
  })

  it("样条、命中和代表点共用连续轴向几何", () => {
    const path = { id: "p1", path_type: "river" }
    const nodes = [
      { path_id: "p1", q: 0, r: 0, sort_order: 0 },
      { path_id: "p1", q: 2, r: 0, sort_order: 1 },
    ]
    expect(pathNodesFor(path, nodes)).toHaveLength(2)
    expect(samplePathGeometry(pathNodesFor(path, nodes))).toHaveLength(9)
    expect(hitTestPath([path], nodes, 1, 0.05)?.id).toBe("p1")
    expect(representativePathPoint(path, nodes)).toEqual({ q: 1, r: 0 })
    expect(MAP_PATH_PROFILES.river.category).toBe("water")
  })

  it("样条分段精确经过每个控制节点", () => {
    const nodes = [
      { q: 0, r: 0, tension: 0.5 },
      { q: 1, r: 2, tension: 0.5 },
      { q: 3, r: 1, tension: 0.5 },
    ]
    const samples = samplePathGeometry(nodes, 4)

    expect(samples[0]).toMatchObject({ q: 0, r: 0 })
    expect(samples[4].q).toBeCloseTo(1)
    expect(samples[4].r).toBeCloseTo(2)
    expect(samples.at(-1)).toMatchObject({ q: 3, r: 1 })
  })

  it("画布绘制返回经过视口裁剪的队列", () => {
    const ctx = {
      globalAlpha: 1,
      save: vi.fn(), restore: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(),
      stroke: vi.fn(), setLineDash: vi.fn(), arc: vi.fn(), fill: vi.fn(),
    }
    const paths = [{ id: "p1", path_type: "street", opacity: 1 }]
    const nodes = [{ path_id: "p1", q: 0, r: 0 }, { path_id: "p1", q: 2, r: 0 }]
    expect(drawMapPaths(ctx, paths, nodes, { viewport: { minQ: -1, maxQ: 3, minR: -1, maxR: 1 } })).toHaveLength(1)
    expect(drawMapPaths(ctx, paths, nodes, { viewport: { minQ: 10, maxQ: 12, minR: 10, maxR: 12 } })).toHaveLength(0)
  })
})
