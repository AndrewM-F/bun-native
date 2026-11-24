import { mkdtempSync, rmSync, writeFileSync, writeSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { windowsFiletimeEvidence } from '../native/windows-filetime.ts'

const dir = mkdtempSync(join(tmpdir(), 'bn-filetime-control-'))
const file = join(dir, 'file with spaces.txt')
const records: object[] = []
try {
  writeFileSync(file, 'fixture')
  for (let index = 0; index < 20; index++) {
    let diagnostic: object = {}
    const value = windowsFiletimeEvidence(file, 'win32', (argv, env) => {
      const started = performance.now()
      const result = Bun.spawnSync(argv, { env, stdout: 'pipe', stderr: 'pipe', timeout: 15_000 })
      diagnostic = {
        elapsedMs: performance.now() - started,
        exitCode: result.exitCode,
        signalCode: result.signalCode,
        success: result.success,
        stderr: Buffer.from(result.stderr).toString().replaceAll(file, '<fixture>').slice(0, 2048),
      }
      return result
    })
    records.push({ index, valid: value !== null, ...diagnostic })
    writeSync(1, `${JSON.stringify(records.at(-1))}\n`)
  }
} finally {
  rmSync(dir, { recursive: true, force: true })
}
if (records.some((record) => !(record as { valid: boolean }).valid)) process.exitCode = 1
