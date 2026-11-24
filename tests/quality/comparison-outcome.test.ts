import { expect, test } from 'bun:test'

test('comparison outcomes retain the report and fail the process for any failed launch', async () => {
  for (const failed of [[], ['react-aot-2']]) {
    const script = `
      import { setComparisonOutcome } from './benchmarks/comparison/outcome.ts'
      const report = {}
      try { setComparisonOutcome(report, ${JSON.stringify(failed)}) }
      finally { console.log(JSON.stringify(report)) }
    `
    const child = Bun.spawn([process.execPath, '-e', script], { stdout: 'pipe', stderr: 'pipe' })
    const [exit, stdout, stderr] = await Promise.all([
      child.exited,
      new Response(child.stdout).text(),
      new Response(child.stderr).text(),
    ])
    expect(stderr).toBe('')
    expect(exit).toBe(failed.length ? 1 : 0)
    expect(JSON.parse(stdout)).toEqual({
      failedLaunches: failed,
      status: failed.length ? 'completed-with-failures' : 'passed',
    })
  }
})
