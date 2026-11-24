/** @jsxImportSource @bun-native/react */
import { render, type NativeRef } from '@bun-native/react'
import { createRef, useEffect, useState, type Dispatch, type SetStateAction } from 'react'
import { CONTENT_STYLE, LIST_STYLE, ROW_STYLE, runWorkload, type Row } from './workload.ts'

// Share the exact workload, bounds and retention oracle with Solid/direct core.
// The benchmark directory will become framework-neutral when the branches join.
await runWorkload('react', async (window, initial, onClick) => {
  let setText!: Dispatch<SetStateAction<string>>
  let setRows!: Dispatch<SetStateAction<readonly Row[]>>
  let rowsCreated = 0
  let rowsDisposed = 0
  let unexpectedClicks = 0
  const content = createRef<NativeRef>()
  let listener: () => void = () => {
    if (onClick) onClick()
    else unexpectedClicks++
  }

  function RowView({ row }: { row: Row }) {
    useEffect(() => {
      rowsCreated++
      return () => {
        rowsDisposed++
      }
    }, [])
    return <text text={row.text} style={ROW_STYLE} />
  }

  function App() {
    const [text, updateText] = useState('Initial')
    const [rows, updateRows] = useState(initial)
    setText = updateText
    setRows = updateRows
    return (
      <box ref={content} style={CONTENT_STYLE}>
        <text text={text} />
        <button text="Benchmark fixture" onClick={listener} />
        <box style={LIST_STYLE}>
          {rows.map((row) => (
            <RowView key={row.id} row={row} />
          ))}
        </box>
      </box>
    )
  }

  let view = render(<App />, window)
  let disposedMutations: typeof view.diagnostics.mutations | undefined
  let disposal: Promise<void> | undefined
  await view.ready
  if (!content.current) throw new Error('React content ref was not attached at native readiness')
  return {
    update(values) {
      for (const value of values) setText(value)
      return view.flush()
    },
    rotate(rows) {
      setRows(rows)
      return view.flush()
    },
    dispose() {
      if (!disposal)
        disposal = (async () => {
          await view.dispose()
          disposedMutations = { ...view.diagnostics.mutations }
          listener = undefined!
          view = undefined!
        })()
      return disposal
    },
    probes: [new WeakRef(view), new WeakRef(content.current), new WeakRef(listener)],
    inspect: () => ({
      mutations: { ...(disposedMutations ?? view.diagnostics.mutations) },
      rowsCreated,
      rowsDisposed,
      unexpectedClicks,
    }),
  }
})
