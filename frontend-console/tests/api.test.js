import { describe, expect, it, vi } from "vitest"
import { readFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import vm from "node:vm"

const projectRoot = dirname(dirname(fileURLToPath(import.meta.url)))

function loadRealApi(fetchMock) {
  const source = readFileSync(join(projectRoot, "api.js"), "utf8")
  const window = { errorLog: {}, location: { hash: "" }, history: { pushState: vi.fn() } }
  const context = {
    window,
    console,
    fetch: fetchMock,
    setTimeout,
    clearTimeout,
    AbortController,
    FormData: class FormData {},
  }
  vm.runInNewContext(source, context)
  return window.api
}

describe("api.js", () => {
  it("把 FastAPI 422 detail 数组格式化成可读错误", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({
        detail: [
          { loc: ["body", "result"], msg: "Field required", type: "missing" },
        ],
      }),
    })
    const realApi = loadRealApi(fetchMock)

    await expect(realApi.outline.createArc({ title: "第一卷" }, "p1"))
      .rejects.toThrow("数据格式校验失败：body.result: Field required")
  })

  it("创建世界对象别名时把 novel_id 放在 query 中", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "a1" }),
    })
    const realApi = loadRealApi(fetchMock)

    await realApi.world.createAlias({
      entity_id: "e1",
      alias: "岚姐",
      alias_type: "name",
    }, "p1")

    expect(fetchMock.mock.calls[0][0]).toContain("/world/aliases?novel_id=p1")
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      entity_id: "e1",
      alias: "岚姐",
      alias_type: "name",
    })
  })
})
