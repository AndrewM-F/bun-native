import { expect, test } from 'bun:test'
import { wholeUnixMilliseconds } from '../native/mtime-precision.ts'

test('timestamp comparison uses exact whole milliseconds on both sides of the epoch', () => {
  for (const [nanoseconds, expected] of [
    [0n, 0n],
    [999_999n, 0n],
    [1_000_000n, 1n],
    [-1n, -1n],
    [-1_000_000n, -1n],
    [-1_000_001n, -2n],
    [1_700_000_000_000_999_900n, 1_700_000_000_000n],
  ] as const)
    expect(wholeUnixMilliseconds(nanoseconds)).toBe(expected)
})

test('a rounded floating mtime does not hide or invent an integer timestamp mismatch', () => {
  const nanoseconds = 1_700_000_000_000_999_900n
  const nativeMs = 1_700_000_000_000n
  const roundedBunMs = Number(nanoseconds) / 1_000_000
  expect(roundedBunMs - Number(nativeMs)).toBe(1)
  expect(wholeUnixMilliseconds(nanoseconds)).toBe(nativeMs)
  expect(wholeUnixMilliseconds(nanoseconds)).not.toBe(nativeMs + 1n)
})
