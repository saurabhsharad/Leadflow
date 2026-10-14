export { cn } from "cn"

/** Characters as the backend counts them (code points), not UTF-16 units: "😀" is 1, not 2. */
export function charCount(value: string): number {
  return [...value].length
}
