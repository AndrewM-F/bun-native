/** Check the native linker graph against the captured, machine-neutral ICU object. */
import { writeFileSync } from 'node:fs'
import { delimiter, join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const [source, work, output, expectation] = process.argv.slice(2)
if (
  process.platform !== 'win32' ||
  !source ||
  !work ||
  !output ||
  !['reject', 'accept'].includes(expectation ?? '')
)
  throw new Error('Windows source, evidence paths, and expectation required')
process.chdir(work)
const { readCoffGraph } = await import(
  pathToFileURL(join(resolve(source), 'scripts/build/trim/coff-graph.ts')).href
)
const libraries = (process.env['LIB'] ?? '').split(delimiter).filter(Boolean)
if (!libraries.length) throw new Error('MSVC LIB search path unavailable')
const reading = readCoffGraph({
  executable: join(work, 'control.exe'),
  chunkMap: join(work, 'control.lldmap'),
  symbolMap: join(work, 'control.map'),
  inputs: [join(work, 'control.obj'), join(work, 'icu.obj')],
  alternateNames: [],
  libraryFolders: libraries,
})
const failures = reading.failures.map(
  (item: { kind: string; reason?: string; object?: string }) => ({
    kind: item.kind,
    reason: item.reason,
    object: item.object,
  })
)
writeFileSync(output, JSON.stringify({ expectation, failures }, null, 2) + '\n', { flag: 'wx' })
const neutralFailure = failures.some(
  (item: { kind: string; reason?: string; object?: string }) =>
    item.kind === 'UnreadInput' &&
    item.reason === 'NotAnObject' &&
    item.object?.toLowerCase().endsWith('icu.obj')
)
if (expectation === 'reject' ? !neutralFailure : failures.length !== 0)
  throw new Error(`Unexpected COFF graph failures for ${expectation}: ${JSON.stringify(failures)}`)
