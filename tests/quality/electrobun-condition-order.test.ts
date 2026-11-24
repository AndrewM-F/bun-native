import { expect, test } from 'bun:test'
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

test.skipIf(process.platform !== 'darwin')(
  'Electrobun records launch conditions before each launcher starts',
  () => {
    const root = mkdtempSync(join(tmpdir(), 'electrobun-conditions-'))
    try {
      const commands = join(root, 'commands')
      const executable = join(root, 'mock.app', 'Contents', 'MacOS')
      const trace = join(root, 'events.log')
      const output = join(root, 'output')
      mkdirSync(commands, { recursive: true })
      mkdirSync(executable, { recursive: true })
      const script = (path: string, contents: string) => {
        writeFileSync(path, `#!/bin/sh\n${contents}\n`)
        chmodSync(path, 0o755)
      }
      script(join(commands, 'sysctl'), 'echo load >> "$TRACE_LOG"\necho mock-load')
      script(join(commands, 'pmset'), 'echo power >> "$TRACE_LOG"\necho mock-power')
      script(
        join(executable, 'launcher'),
        `echo launch >> "$TRACE_LOG"
cat > "$EB_OUTPUT" <<'JSON'
{"mainProcessStartEpochMs":1,"mainEntryMs":1,"windowCreatedMs":1,"startup":{"timeOriginEpochMs":1,"viewMountedMs":1},"phases":{"signals":{"synchronousSubmission":{"p50Ms":1},"toNextFrame":{"p50Ms":1}},"keyedRotations":{"synchronousSubmission":{"p50Ms":1},"toNextFrame":{"p50Ms":1}}},"lifecycles":{"p50Ms":1}}
JSON`
      )
      writeFileSync(join(executable, 'bun'), 'mock')
      const child = Bun.spawnSync(
        [
          process.execPath,
          join(import.meta.dir, '../../benchmarks/electrobun/run.ts'),
          '--app',
          join(root, 'mock.app'),
          '--output',
          output,
          '--trials',
          '3',
        ],
        {
          env: { ...process.env, PATH: `${commands}:${process.env['PATH']}`, TRACE_LOG: trace },
          stdout: 'pipe',
          stderr: 'pipe',
          timeout: 30_000,
        }
      )
      expect(child.stderr.toString()).toBe('')
      expect(child.exitCode).toBe(0)
      const events = readFileSync(trace, 'utf8').trim().split('\n')
      expect(events.slice(0, 12)).toEqual(Array(4).fill(['load', 'power', 'launch']).flat())
      const record = JSON.parse(readFileSync(join(output, 'electrobun.json'), 'utf8'))
      expect(record.status).toBe('passed')
      for (const launch of record.launches) {
        expect(launch.loadAverageBeforeLaunch).toBe('mock-load')
        expect(launch.powerBeforeLaunch).toBe('mock-power')
      }
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  }
)
