import { describe, expect, it } from "vitest"

import {
  defaultKindForType,
  detailTypeLabel,
  kindLabel,
  kindOrTypeDefault,
} from "../../../vue/views/world/logic/worldTypeCatalog.js"

const catalog = {
  relation_kinds: [
    { value: "social", label: "社会/组织", description: "社会联系" },
    { value: "intentional", label: "意图", description: "目标与选择" },
  ],
  relation_types: [{ value: "friend_of", label: "朋友", default_kind: "social" }],
}

describe("worldTypeCatalog", () => {
  it("详细类型只在分类为空时提供默认，不覆盖作者已选分类", () => {
    expect(defaultKindForType(catalog, "relation", "friend_of")).toBe("social")
    expect(kindOrTypeDefault(catalog, "relation", "", "friend_of")).toBe("social")
    expect(kindOrTypeDefault(catalog, "relation", "intentional", "friend_of")).toBe("intentional")
  })

  it("缺分类统一显示待分类，未知英文详细类型不暴露内部枚举", () => {
    expect(kindLabel(catalog, "relation", "")).toBe("待分类")
    expect(detailTypeLabel(catalog, "relation", "friend_of")).toBe("朋友")
    expect(detailTypeLabel(catalog, "relation", "legacy_internal_value")).toBe("自定义详细类型")
    expect(detailTypeLabel(catalog, "relation", "师从")).toBe("师从")
  })
})
