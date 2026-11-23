import { expect, test } from 'bun:test'
import { parseFiletimeEvidence, windowsFiletimeEvidence } from '../native/windows-filetime.ts'

test('Windows FILETIME evidence accepts only bounded unsigned decimal ticks', () => {
  expect(parseFiletimeEvidence(' 116444736000000000\n')).toBe('116444736000000000')
  expect(parseFiletimeEvidence('18446744073709551615')).toBe('18446744073709551615')
  for (const invalid of ['', '-1', '01', '1.0', '18446744073709551616', '1\n2'])
    expect(parseFiletimeEvidence(invalid)).toBeNull()
  if (process.platform !== 'win32') expect(windowsFiletimeEvidence('ignored')).toBeNull()
})

test.skipIf(process.platform !== 'win32')(
  'reads a real Windows FILETIME without exposing the path',
  () => {
    const { mkdtempSync, rmSync, utimesSync, writeFileSync } =
      require('node:fs') as typeof import('node:fs')
    const { tmpdir } = require('node:os') as typeof import('node:os')
    const { join } = require('node:path') as typeof import('node:path')
    const dir = mkdtempSync(join(tmpdir(), 'bun-native-filetime-'))
    try {
      const path = join(dir, 'file with spaces.txt')
      writeFileSync(path, 'fixture')
      const expectedMs = 1_700_000_000_000
      utimesSync(path, new Date(expectedMs), new Date(expectedMs))
      const ticks = windowsFiletimeEvidence(path)
      expect(ticks).not.toBeNull()
      const actualMs = (BigInt(ticks!) - 116_444_736_000_000_000n) / 10_000n
      expect(actualMs).toBe(BigInt(expectedMs))
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  },
  30_000
)
