/**
 * Alternating keyed swaps and rotations through a real native window.
 * Times staging through acknowledgement, not OS input or display presentation.
 * Supply an absolute BUN_NATIVE_HOST path to a source-matched release host.
 */
import { strict as assert } from 'node:assert'
import { isAbsolute } from 'node:path'
import { createApplication, type NativeApplication } from '@bun-native/core'
import {
  createElement,
  createRenderRoot,
  insertNode,
  setProperty,
  type Node,
} from '@bun-native/renderer'

const host = process.env['BUN_NATIVE_HOST']
if (!host || !isAbsolute(host)) throw new Error('Expected an absolute BUN_NATIVE_HOST')
if (process.env['BUN_NATIVE_EVIDENCE_LOG']) throw new Error('Native evidence must be disabled')
let app: NativeApplication | undefined
try {
  app = await createApplication({ executable: host, requestTimeoutMs: 10_000 })
  const window = await app.openWindow({ title: 'Renderer swap benchmark', width: 640, height: 480 })
  const samples: Record<string, number[]> = {}
  for (const width of [100, 500]) {
    const rows: Node[] = []
    let container!: Node
    const root = createRenderRoot(window, (context) => {
      container = context.container
      for (let index = 0; index < width; index += 1) {
        const row = createElement('button')
        setProperty(row, 'text', `row ${index}`)
        insertNode(container, row)
        rows.push(row)
      }
    })
    await root.ready
    assert.equal(root.diagnostics.nodes, width + 1)
    samples[`swap-${width}`] = []
    samples[`rotate-${width}`] = []
    for (let iteration = 0; iteration < 110; iteration += 1) {
      for (const scenario of ['swap', 'rotate'] as const) {
        const before = window.revision
        const started = performance.now()
        if (scenario === 'swap') {
          const first = rows[1]!
          const last = rows[width - 2]!
          insertNode(container, last, first)
          insertNode(container, first, rows[width - 1]!)
          rows[1] = last
          rows[width - 2] = first
        } else {
          const last = rows.pop()!
          insertNode(container, last, rows[0]!)
          rows.unshift(last)
        }
        await root.flush()
        const elapsed = performance.now() - started
        assert.equal(window.revision, before + 1)
        assert.equal(root.diagnostics.nodes, width + 1)
        assert(container.children.every((child, index) => child === rows[index]))
        if (iteration >= 10) samples[`${scenario}-${width}`]!.push(elapsed)
      }
    }
    await root.dispose()
  }
  await window.close()
  await window.closed
  await app.shutdown()
  await app.closed
  assert.equal(app.diagnostics.nodes, 0)
  console.log(
    JSON.stringify({
      status: 'passed',
      bunRevision: Bun.revision,
      host,
      samples,
      scope: 'renderer staging through native acknowledgement; not display presentation',
    })
  )
} finally {
  if (app) await app.shutdown().catch(() => {})
}
