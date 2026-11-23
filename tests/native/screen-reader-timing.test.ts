import { expect, test } from 'bun:test'
import { PhraseTiming } from './screen-reader-timing.ts'

test('phrase polling evidence is bounded and returned as independent snapshots', () => {
  const timing = new PhraseTiming(2)
  timing.add(0, 10, 12, 0, 123)
  timing.add(1, 20, 25, 123, 123)
  timing.add(2, 30, 35, 123, 123)
  const captured = timing.snapshot()
  expect(captured).toEqual({
    samples: [
      { index: 0, startMs: 10, endMs: 12, hostPidStart: 0, hostPidEnd: 123 },
      { index: 1, startMs: 20, endMs: 25, hostPidStart: 123, hostPidEnd: 123 },
    ],
    omitted: 1,
  })
  captured.samples[0]!.hostPidStart = 999
  expect(timing.snapshot().samples[0]!.hostPidStart).toBe(0)
})
