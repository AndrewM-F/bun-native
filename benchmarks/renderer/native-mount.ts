import { strict as assert } from 'node:assert'
import { createApplication, type NativeApplication } from '@bun-native/core'
import { createElement, createRenderRoot, insertNode, setProperty } from '@bun-native/renderer'
const host = process.env['BUN_NATIVE_HOST']!
if (!host || process.env['BUN_NATIVE_EVIDENCE_LOG'])
  throw new Error('Expected host with native evidence disabled')
let app: NativeApplication | undefined
try {
  app = await createApplication({ executable: host, requestTimeoutMs: 10_000 })
  const window = await app.openWindow({
    title: 'Native mount measurement',
    width: 640,
    height: 480,
  })
  const samples: Record<string, number[]> = {}
  for (const rows of [42, 128]) {
    const times: number[] = []
    for (let iteration = 0; iteration < 55; iteration++) {
      const revision = window.revision
      const started = performance.now()
      const root = createRenderRoot(window, ({ container }) => {
        for (let i = 0; i < rows; i++) {
          const box = createElement('box')
          const label = createElement('text')
          setProperty(label, 'text', `Message ${i}`)
          const button = createElement('button')
          setProperty(button, 'text', 'Archive')
          insertNode(box, label)
          insertNode(box, button)
          insertNode(container, box)
        }
      })
      await root.ready
      const elapsed = performance.now() - started
      assert.equal(window.revision, revision + 1)
      assert.equal(root.diagnostics.nodes, rows * 3 + 1)
      if (iteration >= 5) times.push(elapsed)
      await root.dispose()
    }
    samples[`mount-${rows}`] = times
  }
  await window.close()
  await window.closed
  await app.shutdown()
  await app.closed
  assert.equal(app.diagnostics.nodes, 0)
  console.log(JSON.stringify({ status: 'passed', bunRevision: Bun.revision, host, samples }))
} finally {
  if (app) await app.shutdown().catch(() => {})
}
