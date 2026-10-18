/** Remove only a suffix/prefix repeated across audio windows that actually overlap. */
export function mergeTranscript(previous: string, next: string, overlaps: boolean): string {
  const left = previous.trim()
  const right = next.trim()
  if (!left || !right) return left || right
  if (!overlaps) return `${left} ${right}`
  const a = left.split(/\s+/)
  const b = right.split(/\s+/)
  const normalize = (word: string) => word.toLocaleLowerCase("vi").replace(/[^\p{L}\p{N}]/gu, "")
  for (let count = Math.min(a.length, b.length, 12); count >= 1; count--) {
    if (a.slice(-count).map(normalize).join(" ") === b.slice(0, count).map(normalize).join(" ")) {
      return [...a, ...b.slice(count)].join(" ")
    }
  }
  return `${left} ${right}`
}

export function cleanSpeech(text: string): string {
  const normalized = text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/đ/g, "d").replace(/[^a-z0-9 ]/g, "").trim()
  return /^(cam on cac ban da (theo doi|xem video)|hen gap lai cac ban trong nhung video tiep theo|thanks for watching)$/.test(normalized) ? "" : text.trim()
}
