/** Diagnostic preload only: record the current Windows thread's OS stack bounds. */
import { dlopen, FFIType, ptr } from 'bun:ffi'
import { writeFileSync } from 'node:fs'
import { isAbsolute, join } from 'node:path'

const directory = process.env['BN_COLLECTOR_TRACE_DIR']
if (process.platform !== 'win32' || !directory || !isAbsolute(directory))
  throw new Error('Stack bounds require an absolute Windows trace directory')
const library = dlopen('kernel32.dll', {
  GetCurrentThreadStackLimits: { args: [FFIType.ptr, FFIType.ptr], returns: FFIType.void },
  GetCurrentThreadId: { args: [], returns: FFIType.u32 },
  GetModuleHandleW: { args: [FFIType.ptr], returns: FFIType.ptr },
})
const bounds = new BigUint64Array(2)
library.symbols.GetCurrentThreadStackLimits(ptr(bounds), ptr(bounds, 8))
const threadId = library.symbols.GetCurrentThreadId()
const low = bounds[0]!
const high = bounds[1]!
const moduleHandle = library.symbols.GetModuleHandleW(null)
if (!threadId || low === 0n || high <= low || !moduleHandle || !Number.isSafeInteger(moduleHandle))
  throw new Error('Invalid Windows thread stack bounds or executable module')
writeFileSync(
  join(directory, `stack-limits-${process.pid}.json`),
  JSON.stringify({
    pid: process.pid,
    threadId,
    low: low.toString(),
    high: high.toString(),
    executableModuleBase: BigInt(moduleHandle).toString(),
  }) + '\n',
  { flag: 'wx' }
)
library.close()
