import { describe, expect, it, vi } from "vitest"

import {
  createRetryableLeafletLoader,
  loadLeafletForMapView,
} from "../views/leafletLoader.js"

const leafletApi = Object.freeze({
  CRS: { Simple: {} },
  map() {},
})

describe("Leaflet on-demand loader", () => {
  it("loads the exact pinned package without retaining browser globals", async () => {
    const leaflet = await loadLeafletForMapView()

    expect(leaflet.version).toBe("1.9.4")
    expect(globalThis.L).toBeUndefined()
    expect(globalThis.leaflet).toBeUndefined()
  })

  it("shares one in-flight and successful import", async () => {
    let resolveImport
    const importer = vi.fn(() => new Promise((resolve) => {
      resolveImport = resolve
    }))
    const load = createRetryableLeafletLoader(importer)

    const first = load()
    const second = load()
    expect(first).toBe(second)
    await Promise.resolve()
    expect(importer).toHaveBeenCalledTimes(1)

    resolveImport(leafletApi)
    await expect(first).resolves.toBe(leafletApi)
    await expect(load()).resolves.toBe(leafletApi)
    expect(importer).toHaveBeenCalledTimes(1)
  })

  it("clears a failed attempt so the author can retry in place", async () => {
    const importer = vi.fn()
      .mockRejectedValueOnce(new Error("chunk unavailable"))
      .mockResolvedValueOnce(leafletApi)
    const load = createRetryableLeafletLoader(importer)

    await expect(load()).rejects.toThrow("chunk unavailable")
    await expect(load()).resolves.toBe(leafletApi)
    expect(importer).toHaveBeenCalledTimes(2)
  })

  it("rejects an invalid module and keeps retry available", async () => {
    const importer = vi.fn()
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce(leafletApi)
    const load = createRetryableLeafletLoader(importer)

    await expect(load()).rejects.toThrow("expected viewport API")
    await expect(load()).resolves.toBe(leafletApi)
  })
})
