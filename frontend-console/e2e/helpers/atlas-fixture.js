export const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2nWQAAAAASUVORK5CYII=",
  "base64",
)

export function atlasPage(id, overrides = {}) {
  return {
    id,
    node_id: "node-harbor",
    run_id: "run-1",
    title: "沉钟港",
    generation_status: "review_ready",
    review_status: "candidate",
    updated_at: "2026-08-12T00:00:00Z",
    created_at: "2026-08-12T00:00:00Z",
    evidence: { supported: ["正式设定中的港口"], visual_fill: ["码头间距"], conflicts: [] },
    source_manifest: [],
    annotations: [],
    image_url: `/api/world/map-atlas/project/pages/${id}/image`,
    width: 2048,
    height: 1152,
    ...overrides,
  }
}

export function atlasTree(pages, mode) {
  return {
    mode,
    total_pages: pages.length,
    nodes: pages.length ? [{
      id: "node-harbor",
      title: "沉海湾",
      level: "city",
      pages,
      children: [],
    }] : [],
  }
}

export async function mockAtlas(page, {
  candidate,
  adopted = [],
  history = [],
  failFirstImage = false,
  holdStop = false,
  reviewTree = null,
  runOverrides = {},
}) {
  const run = {
    id: "run-1",
    status: "review_ready",
    stop_requested: false,
    planned_page_count: 1,
    completed_page_count: 1,
    ...runOverrides,
  }
  let imageAttempts = 0
  let reviewRequests = []
  let resumeRequests = []
  let retryRequests = []
  let savedPages = [...adopted]
  let releaseStop = () => {}
  const stopGate = holdStop ? new Promise(resolve => { releaseStop = resolve }) : Promise.resolve()

  await page.route("**/api/world/map-atlas/**", async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const method = request.method()
    if (method === "GET" && path.endsWith("/capabilities")) return route.fulfill({ json: { upload: { available: true }, image_generation: { available: true } } })
    if (method === "GET" && path.endsWith("/atlas")) {
      return route.fulfill({ json: atlasTree(savedPages, "atlas") })
    }
    if (method === "GET" && path.endsWith("/pages/history")) {
      return route.fulfill({ json: history })
    }
    if (method === "GET" && path.endsWith("/runs/latest")) {
      return route.fulfill({ json: run })
    }
    if (method === "GET" && path.endsWith("/runs/run-1/results")) {
      return route.fulfill({ json: { ...(reviewTree || atlasTree(candidate ? [candidate] : [], "review")), run } })
    }
    if (method === "GET" && path.endsWith("/runs/run-1")) {
      return route.fulfill({ json: run })
    }
    if (method === "GET" && path.endsWith("/image")) {
      imageAttempts += 1
      if (failFirstImage && imageAttempts === 1) {
        return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "temporary image read failure" }) })
      }
      return route.fulfill({ status: 200, contentType: "image/png", body: PNG })
    }
    if (method === "POST" && path.endsWith("/adopt")) {
      reviewRequests.push(request.postDataJSON())
      candidate.review_status = "adopted"
      if (!savedPages.some(item => item.id === candidate.id)) savedPages = [...savedPages, candidate]
      return route.fulfill({ json: candidate })
    }
    if (method === "POST" && path.endsWith("/runs/run-1/stop")) {
      await stopGate
      Object.assign(run, { status: "paused", stop_requested: true })
      return route.fulfill({ json: run })
    }
    if (method === "POST" && path.endsWith("/runs/run-1/resume")) {
      resumeRequests.push(request.postDataJSON())
      Object.assign(run, { status: "generating", stop_requested: false })
      return route.fulfill({ json: run })
    }
    if (method === "POST" && path.endsWith(`/${candidate?.id}/retry`)) {
      retryRequests.push(request.postDataJSON())
      Object.assign(candidate, { generation_status: "prepared", error_message: null })
      Object.assign(run, { status: "generating", stop_requested: false, error_code: null })
      return route.fulfill({ json: candidate })
    }
    return route.fulfill({ status: 404, json: { detail: "unexpected atlas test request" } })
  })

  return {
    imageAttempts: () => imageAttempts,
    reviewRequests: () => reviewRequests,
    releaseStop,
    resumeRequests: () => resumeRequests,
    retryRequests: () => retryRequests,
    savedPageIds: () => savedPages.map(item => item.id),
  }
}
