/** Test whether COFF graph lookup needs the native Windows LIB search path. */
import { writeFileSync } from 'node:fs'
import { delimiter, join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const [source, work, output] = process.argv.slice(2)
if (process.platform !== 'win32' || !source || !work || !output) throw new Error('Windows source and evidence paths required')
const { readCoffGraph } = await import(pathToFileURL(join(resolve(source), 'scripts/build/trim/coff-graph.ts')).href)
const base = { executable: join(work, 'control.exe'), chunkMap: join(work, 'control.lldmap'), symbolMap: join(work, 'control.map'), inputs: [join(work, 'control.obj')], alternateNames: [] }
const libraries = (process.env['LIB'] ?? '').split(delimiter).filter(Boolean)
if (libraries.length === 0) throw new Error('MSVC LIB search path unavailable')
const results = []
for (const [name, folders] of [['without', []], ['with', libraries]] as const) {
  const reading = readCoffGraph({ ...base, libraryFolders: folders })
  const failures = reading.failures.map((item: { kind: string; reason?: string; object?: string }) => ({ kind: item.kind, reason: item.reason, object: item.object }))
  results.push({ name, folderCount: folders.length, failures })
}
writeFileSync(output, JSON.stringify(results, null, 2) + '\n', { flag: 'wx' })
const missing = (entry: (typeof results)[number]) => entry.failures.filter((item: { kind: string; reason?: string }) => item.kind === 'UnreadInput' && item.reason === 'NotFound').length
if (missing(results[0]!) === 0 || missing(results[1]!) >= missing(results[0]!)) throw new Error('LIB-path hypothesis was not reproduced')
