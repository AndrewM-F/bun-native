import { expect, test } from 'bun:test'
import { mkdtempSync, existsSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { stopVisibleStream } from '../../benchmarks/electrobun/visible-stream-cleanup'

async function exerciseCleanup(blockStop: boolean) {
  const dir = mkdtempSync(join(tmpdir(), 'visible-stream-cleanup-'))
  const stopPath = join(dir, 'stop')
  if (blockStop) writeFileSync(stopPath, '')
  const child = Bun.spawn(
    [
      process.execPath,
      '-e',
      `
    const { existsSync } = require('node:fs');
    const stop = process.argv[1];
    setInterval(() => { if (existsSync(stop)) process.exit(0) }, 10);
  `,
      stopPath,
    ],
    { stdout: 'ignore', stderr: 'ignore' }
  )
  try {
    const result = await stopVisibleStream(child, stopPath, 2000, 1000)
    expect(existsSync(stopPath)).toBe(true)
    expect(result.exitCode).not.toBeNull()
    if (blockStop) {
      expect(result.forced).toBe(true)
      expect(result.requestError).toBeDefined()
    } else {
      expect(result.forced).toBe(false)
      expect(result.exitCode).toBe(0)
      expect(result.error).toBeUndefined()
    }
  } finally {
    if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL')
    await child.exited
    rmSync(dir, { recursive: true, force: true })
  }
}

test('visible stream cleanup requests a graceful stop', async () => {
  await exerciseCleanup(false)
})

test('visible stream cleanup terminates its child if the stop request fails', async () => {
  await exerciseCleanup(true)
})
