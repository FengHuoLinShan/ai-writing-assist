import { describe, expect, it } from "vitest"

import { sceneObjectStates } from "../../../vue/views/writing/sceneLensModel.js"

describe("sceneObjectStates", () => {
  it("maps object states with author-facing field labels and belief markers", () => {
    const result = sceneObjectStates([
      {
        subject_id: "entity-1",
        label: "铜钥匙",
        location: "灯塔下",
        fields: [
          { field: "custody_holder", display: "乙", layer: "fact", confidence: "derived", possibly_false: false },
          { field: "custody_owner", display: "甲", layer: "fact", confidence: "confirmed", possibly_false: false },
        ],
        knowledge: [
          { holder: "乙", text: "钥匙已归还甲", possibly_false: true },
        ],
      },
    ])

    expect(result).toHaveLength(1)
    expect(result[0].label).toBe("铜钥匙")
    expect(result[0].location).toBe("灯塔下")
    expect(result[0].fields.map((field) => field.label)).toEqual(["保管人", "所有人"])
    expect(result[0].fields[1].confirmed).toBe(true)
    expect(result[0].knowledge[0]).toMatchObject({ holder: "乙", possiblyFalse: true })
  })

  it("drops empty entries and tolerates missing payloads", () => {
    expect(sceneObjectStates(null)).toEqual([])
    expect(sceneObjectStates([{ subject_id: "x", label: "空对象", fields: [], knowledge: [] }])).toEqual([])
  })
})
