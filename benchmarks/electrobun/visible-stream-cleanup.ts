import { writeFileSync } from 'node:fs'

type StreamProcess = ReturnType<typeof Bun.spawn>

/** Stop only the caller-owned helper; retain bounded forced-cleanup evidence. */
export async function stopVisibleStream(
  child: StreamProcess,
  stopPath: string,
  graceMs = 3000,
  signalMs = 2000
): Promise<{ exitCode: number | null; forced: boolean; requestError?: string; error?: string }> {
  let requestError: string | undefined
  try {
    writeFileSync(stopPath, '', { flag: 'wx' })
  } catch (error) {
    requestError = error instanceof Error ? error.message : String(error)
  }
  try {
    const stopped = requestError
      ? null
      : await Promise.race([child.exited, Bun.sleep(graceMs).then(() => null)])
    if (stopped !== null)
      return {
        exitCode: stopped,
        forced: false,
        ...(stopped === 0 ? {} : { error: `Stream helper exited ${stopped} during cleanup` }),
      }
    child.kill('SIGTERM')
    let exited = await Promise.race([child.exited, Bun.sleep(signalMs).then(() => null)])
    if (exited === null) {
      child.kill('SIGKILL')
      exited = await Promise.race([child.exited, Bun.sleep(signalMs).then(() => null)])
    }
    return {
      exitCode: exited,
      forced: true,
      ...(requestError ? { requestError } : {}),
      ...(exited === null ? { error: 'Stream helper did not exit after SIGKILL' } : {}),
    }
  } catch (error) {
    return {
      exitCode: child.exitCode,
      forced: true,
      ...(requestError ? { requestError } : {}),
      error: error instanceof Error ? error.message : String(error),
    }
  }
}
