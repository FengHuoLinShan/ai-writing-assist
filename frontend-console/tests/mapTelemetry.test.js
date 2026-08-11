import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import {
  beginMapNavigation,
  cancelMapTelemetry,
  endMapTelemetryStage,
  markMapTelemetryCondition,
  percentileNearestRank,
  queueMapNavigationStart,
  recordMapFrame,
  recordMapInput,
  setMapTelemetryMetadata,
  startMapTelemetryStage,
} from "../views/mapTelemetry.js"

describe("mapTelemetry", () => {
  beforeEach(() => {
    cancelMapTelemetry()
    queueMapNavigationStart({ mapId: null })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it("emits one frozen interactive snapshot after every readiness condition", () => {
    const listener = vi.fn()
    window.addEventListener("map:interactive", listener, { once: true })
    beginMapNavigation({ mapId: "map-1", startedAt: performance.now() })
    setMapTelemetryMetadata({ grid: "24x18", payloadBytes: 1234 })
    startMapTelemetryStage("api_and_parse")
    endMapTelemetryStage("api_and_parse", { durationMs: 12 })

    for (const name of ["state_ready", "leaflet_ready", "canvas_frame", "labels_ready"]) {
      markMapTelemetryCondition(name)
    }
    expect(listener).not.toHaveBeenCalled()
    markMapTelemetryCondition("handlers_ready")
    markMapTelemetryCondition("handlers_ready")

    expect(listener).toHaveBeenCalledTimes(1)
    const detail = listener.mock.calls[0][0].detail
    expect(detail).toMatchObject({
      map_id: "map-1",
      grid: "24x18",
      payload_bytes: 1234,
      stages: { api_and_parse: 12 },
    })
    expect(Object.isFrozen(detail)).toBe(true)
    expect(Object.isFrozen(detail.conditions)).toBe(true)
  })

  it.each([null, undefined, ""]) (
    "uses the current monotonic time when startedAt is %s",
    (startedAt) => {
      const listener = vi.fn()
      const nowSpy = vi.spyOn(performance, "now").mockReturnValue(42)
      window.addEventListener("map:interactive", listener, { once: true })

      beginMapNavigation({ mapId: "map-current-time", startedAt })
      for (const name of [
        "state_ready",
        "leaflet_ready",
        "canvas_frame",
        "labels_ready",
        "handlers_ready",
      ]) {
        markMapTelemetryCondition(name)
      }

      const detail = listener.mock.calls[0][0].detail
      expect(detail.navigation_started_at_ms).toBe(42)
      expect(detail.interactive_ms).toBe(0)
      nowSpy.mockRestore()
    },
  )

  it("accepts an explicit finite numeric navigation start", () => {
    const listener = vi.fn()
    window.addEventListener("map:interactive", listener, { once: true })
    beginMapNavigation({ mapId: "map-explicit-time", startedAt: 12.5 })
    for (const name of [
      "state_ready",
      "leaflet_ready",
      "canvas_frame",
      "labels_ready",
      "handlers_ready",
    ]) {
      markMapTelemetryCondition(name)
    }

    expect(listener.mock.calls[0][0].detail.navigation_started_at_ms).toBe(12.5)
  })

  it("uses cryptographic bytes when randomUUID is unavailable", () => {
    const getRandomValues = vi.fn((bytes) => {
      bytes.set([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15])
      return bytes
    })
    const random = vi.spyOn(Math, "random").mockImplementation(() => {
      throw new Error("Math.random must not generate telemetry identifiers")
    })
    vi.stubGlobal("crypto", { getRandomValues })

    expect(() => beginMapNavigation({ mapId: "map-crypto-fallback" })).not.toThrow()
    expect(getRandomValues).toHaveBeenCalledTimes(1)
    expect(random).not.toHaveBeenCalled()

  })

  it("consumes the matching route-level navigation start", () => {
    const listener = vi.fn()
    window.addEventListener("map:interactive", listener, { once: true })
    queueMapNavigationStart({
      mapId: "map-route-start",
      route: "#workbench/novel-1/map?map_id=map-route-start&mode=live",
      startedAt: 9.5,
    })
    beginMapNavigation({ mapId: "map-route-start" })
    for (const name of [
      "state_ready",
      "leaflet_ready",
      "canvas_frame",
      "labels_ready",
      "handlers_ready",
    ]) {
      markMapTelemetryCondition(name)
    }

    expect(listener.mock.calls[0][0].detail).toMatchObject({
      navigation_started_at_ms: 9.5,
      route: "#workbench/novel-1/map?map_id=map-route-start&mode=live",
    })
  })

  it("removes non-map query parameters from the public route snapshot", () => {
    const listener = vi.fn()
    window.addEventListener("map:interactive", listener, { once: true })
    beginMapNavigation({
      mapId: "map-safe-route",
      route: "#workbench/novel-1/map?map_id=map-safe-route&mode=live&token=secret&prompt=hidden",
    })
    for (const name of [
      "state_ready",
      "leaflet_ready",
      "canvas_frame",
      "labels_ready",
      "handlers_ready",
    ]) {
      markMapTelemetryCondition(name)
    }

    expect(listener.mock.calls[0][0].detail.route).toBe(
      "#workbench/novel-1/map?map_id=map-safe-route&mode=live",
    )
  })

  it("measures a stage when no explicit duration is supplied", () => {
    const listener = vi.fn()
    const nowSpy = vi.spyOn(performance, "now")
      .mockReturnValueOnce(10)
      .mockReturnValue(25)
    window.addEventListener("map:interactive", listener, { once: true })
    beginMapNavigation({ mapId: "map-measured-stage", startedAt: 0 })
    startMapTelemetryStage("state_assembly")
    endMapTelemetryStage("state_assembly")
    for (const name of [
      "state_ready",
      "leaflet_ready",
      "canvas_frame",
      "labels_ready",
      "handlers_ready",
    ]) {
      markMapTelemetryCondition(name)
    }

    expect(listener.mock.calls[0][0].detail.stages.state_assembly).toBe(15)
    nowSpy.mockRestore()
  })

  it("does not attribute buffered long tasks from before navigation", () => {
    const observers = []
    class FakePerformanceObserver {
      constructor(callback) {
        this.callback = callback
        observers.push(this)
      }

      observe() {}
      disconnect() {}
    }
    vi.stubGlobal("PerformanceObserver", FakePerformanceObserver)
    const listener = vi.fn()
    window.addEventListener("map:interactive", listener, { once: true })
    beginMapNavigation({ mapId: "map-long-task", startedAt: 100 })
    observers[0].callback({
      getEntries: () => [
        { startTime: 75, duration: 80 },
        { startTime: 125, duration: 55 },
      ],
    })
    for (const name of [
      "state_ready",
      "leaflet_ready",
      "canvas_frame",
      "labels_ready",
      "handlers_ready",
    ]) {
      markMapTelemetryCondition(name)
    }

    expect(listener.mock.calls[0][0].detail.long_tasks).toEqual([
      { start_ms: 125, duration_ms: 55 },
    ])
    vi.unstubAllGlobals()
  })

  it("publishes a real-input performance sample after warmup plus 100 frames", () => {
    const listener = vi.fn()
    window.addEventListener("map:performance-sample", listener, { once: true })
    beginMapNavigation({ mapId: "map-2" })
    for (let index = 0; index < 120; index += 1) {
      recordMapInput(index === 0 ? "click" : "pointermove", { clickedHex: index === 0 })
      recordMapFrame(index + 1)
    }

    expect(listener).toHaveBeenCalledTimes(1)
    expect(listener.mock.calls[0][0].detail).toMatchObject({
      frames: { total: 120, sampled: 100 },
      input: { sampled: 100, clicked_hex: true },
    })
    const detail = listener.mock.calls[0][0].detail
    expect(detail.frames.raw_redraw_cpu_ms).toHaveLength(100)
    expect(detail.input.raw_to_paint_ms).toHaveLength(100)
    expect(percentileNearestRank(detail.frames.raw_redraw_cpu_ms, 0.95)).toBe(
      detail.frames.p95_redraw_cpu_ms,
    )
    expect(percentileNearestRank(detail.input.raw_to_paint_ms, 0.95)).toBe(
      detail.input.p95_to_paint_ms,
    )
  })

  it("uses nearest-rank percentiles", () => {
    expect(percentileNearestRank([4, 1, 2, 3], 0.95)).toBe(4)
    expect(percentileNearestRank([1, 2, 3, 4, 5], 0.5)).toBe(3)
    expect(percentileNearestRank([], 0.95)).toBeNull()
  })
})
