/** Stored Scene indices stay zero-based; author-facing numbers start at one. */
export function sceneNumber(index) {
  if (index == null || index === "") return null
  const value = Number(index)
  return Number.isInteger(value) && value >= 0 ? value + 1 : null
}
export function sceneIndex(number) {
  if (number == null || number === "") return null
  const value = Number(number)
  return Number.isInteger(value) && value >= 1 ? value - 1 : null
}
