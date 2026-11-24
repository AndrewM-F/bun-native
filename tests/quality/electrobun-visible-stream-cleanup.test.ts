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

test('cleanup reports a helper that stops with an error', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'visible-stream-error-'))
  const stop = join(dir, 'stop')
  const child = Bun.spawn(
    [
      process.execPath,
      '-e',
      "const fs=require('node:fs'); setInterval(()=>{if(fs.existsSync(process.argv[1]))process.exit(7)},10)",
      stop,
    ],
    { stdout: 'ignore', stderr: 'ignore' }
  )
  try {
    const result = await stopVisibleStream(child, stop, 2000, 1000)
    expect(result).toMatchObject({
      exitCode: 7,
      forced: false,
      error: 'Stream helper exited 7 during cleanup',
    })
  } finally {
    if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL')
    await child.exited
    rmSync(dir, { recursive: true, force: true })
  }
})

test.skipIf(process.platform === 'win32')(
  'cleanup escalates when a helper ignores stop and SIGTERM',
  async () => {
    const dir = mkdtempSync(join(tmpdir(), 'visible-stream-ignore-'))
    const stop = join(dir, 'stop')
    const ready = join(dir, 'ready')
    const child = Bun.spawn(
      [
        process.execPath,
        '-e',
        "process.on('SIGTERM',()=>{}); require('node:fs').writeFileSync(process.argv[1],''); setInterval(()=>{},1000)",
        ready,
      ],
      { stdout: 'ignore', stderr: 'ignore' }
    )
    try {
      const deadline = Date.now() + 3000
      while (!existsSync(ready) && Date.now() < deadline) await Bun.sleep(10)
      expect(existsSync(ready)).toBe(true)
      const result = await stopVisibleStream(child, stop, 30, 100)
      expect(result.forced).toBe(true)
      expect(child.signalCode).toBe('SIGKILL')
      expect(result.error).toBeUndefined()
    } finally {
      if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL')
      await child.exited
      rmSync(dir, { recursive: true, force: true })
    }
  },
  5000
)

test('cleanup reports a process-control failure', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'visible-stream-signal-error-'))
  try {
    const child = {
      exitCode: null,
      exited: new Promise<number>(() => {}),
      kill: () => {
        throw new Error('signal failed')
      },
    } as unknown as ReturnType<typeof Bun.spawn>
    const result = await stopVisibleStream(child, join(dir, 'stop'), 1, 1)
    expect(result).toMatchObject({ forced: true, exitCode: null, error: 'signal failed' })
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('cleanup reports a helper that does not exit after escalation', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'visible-stream-stuck-'))
  try {
    const signals: string[] = []
    const child = {
      exitCode: null,
      exited: new Promise<number>(() => {}),
      kill: (signal: string) => {
        signals.push(signal)
      },
    } as unknown as ReturnType<typeof Bun.spawn>
    const result = await stopVisibleStream(child, join(dir, 'stop'), 1, 1)
    expect(signals).toEqual(['SIGTERM', 'SIGKILL'])
    expect(result).toMatchObject({
      forced: true,
      exitCode: null,
      error: 'Stream helper did not exit after SIGKILL',
    })
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})
