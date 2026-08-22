import { describe, expect, it } from "vitest"

import {
  bindTypeKindControls,
  defaultKindForType,
  detailTypeLabel,
  kindLabel,
  kindOrTypeDefault,
} from "../../../vue/views/world/logic/worldTypeCatalog.js"

const catalog = {
  relation_kinds: [
    { value: "social", label: "社会/组织", description: "社会联系" },
    { value: "spatial", label: "空间", description: "空间位置" },
    { value: "intentional", label: "意图", description: "目标与选择" },
  ],
  relation_types: [
    { value: "friend_of", label: "朋友", default_kind: "social" },
    { value: "located_at", label: "位于", default_kind: "spatial" },
  ],
}

describe("worldTypeCatalog", () => {
  it("详细类型只在分类为空时提供默认，不覆盖作者已选分类", () => {
    expect(defaultKindForType(catalog, "relation", "friend_of")).toBe("social")
    expect(kindOrTypeDefault(catalog, "relation", "", "friend_of")).toBe("social")
    expect(kindOrTypeDefault(catalog, "relation", "intentional", "friend_of")).toBe("intentional")
  })

  it("缺分类显示待分类，未知详细类型保留精确内容", () => {
    expect(kindLabel(catalog, "relation", "")).toBe("待分类")
    expect(detailTypeLabel(catalog, "relation", "friend_of")).toBe("朋友")
    expect(detailTypeLabel(catalog, "relation", "legacy_internal_value")).toBe("legacy_internal_value（自定义）")
    expect(detailTypeLabel(catalog, "relation", "师从")).toBe("师从（自定义）")
  })

  it("详细类型只在作者未选分类时联动 kind", () => {
    document.body.innerHTML = `
      <select id="type"><option value="friend_of" selected>朋友</option><option value="located_at">位于</option></select>
      <select id="kind"><option value=""></option><option value="social">社会</option><option value="spatial">空间</option><option value="intentional">意图</option></select>
    `
    const typeSelect = document.getElementById("type")
    const kindSelect = document.getElementById("kind")
    bindTypeKindControls({ typeSelect, kindSelect, catalog, domain: "relation" })
    expect(kindSelect.value).toBe("social")

    typeSelect.value = "located_at"
    typeSelect.dispatchEvent(new Event("change"))
    expect(kindSelect.value).toBe("spatial")

    kindSelect.value = "intentional"
    kindSelect.dispatchEvent(new Event("change"))
    typeSelect.value = "friend_of"
    typeSelect.dispatchEvent(new Event("change"))
    expect(kindSelect.value).toBe("intentional")
  })
})
