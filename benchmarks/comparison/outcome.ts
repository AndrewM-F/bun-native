/** Mark measured-launch failures without preventing the final report from being written. */
export function setComparisonOutcome(report: Record<string, unknown>, failed: string[]): void {
  report['failedLaunches'] = failed
  report['status'] = failed.length ? 'completed-with-failures' : 'passed'
  if (failed.length) process.exitCode = 1
}
