import { expect, it } from "vitest"
import { sceneNumber, sceneIndex } from "../../shared/sceneNumbers.js"
it("首个场景显示1并能无损还原为查询索引0", () => {
  for (const index of [0, 1, 52, 300]) expect(sceneIndex(sceneNumber(index))).toBe(index)
  expect(sceneNumber("0")).toBe(1)
  for (const value of [null, undefined, "", -1, "bad"]) expect(sceneNumber(value)).toBeNull()
  for (const value of [null, undefined, "", 0, -1, 1.5]) expect(sceneIndex(value)).toBeNull()
})
