/** Independent Windows metadata read for a failed filesystem timestamp comparison. */
const readFiletime = String.raw`
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
public static class FiletimeEvidence {
  [StructLayout(LayoutKind.Sequential)]
  public struct FileTime { public uint Low; public uint High; }
  [StructLayout(LayoutKind.Sequential)]
  public struct Attributes {
    public uint Flags;
    public FileTime Creation, Access, Write;
    public uint SizeHigh, SizeLow;
  }
  [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
  private static extern bool GetFileAttributesEx(string path, int level, out Attributes data);
  public static ulong LastWrite(string path) {
    Attributes data;
    if (!GetFileAttributesEx(path, 0, out data)) throw new Win32Exception(Marshal.GetLastWin32Error());
    return ((ulong)data.Write.High << 32) | data.Write.Low;
  }
}
'@
[Console]::Out.Write([FiletimeEvidence]::LastWrite($env:BUN_NATIVE_MTIME_EVIDENCE_PATH).ToString([Globalization.CultureInfo]::InvariantCulture))
`
const writeFiletime = String.raw`
$ErrorActionPreference = 'Stop'
$ticks = [long]::Parse($env:BUN_NATIVE_MTIME_TICKS, [Globalization.CultureInfo]::InvariantCulture)
[IO.File]::SetLastWriteTimeUtc($env:BUN_NATIVE_MTIME_EVIDENCE_PATH, [DateTime]::FromFileTimeUtc($ticks))
`

export function parseFiletimeEvidence(text: string): string | null {
  const value = text.trim()
  if (!/^(0|[1-9]\d{0,19})$/.test(value)) return null
  return BigInt(value) <= 0xffff_ffff_ffff_ffffn ? value : null
}

type FiletimeRunner = (
  command: string[],
  env: NodeJS.ProcessEnv
) => {
  success: boolean
  stdout: Uint8Array
}

/** Best effort: an unavailable diagnostic must never replace the original failure. */
export function windowsFiletimeEvidence(
  path: string,
  platform = process.platform,
  run?: FiletimeRunner
): string | null {
  if (platform !== 'win32') return null
  try {
    const powershell = `${process.env['SystemRoot']}\\System32\\WindowsPowerShell\\v1.0\\powershell.exe`
    const command = Buffer.from(readFiletime, 'utf16le').toString('base64')
    const argv = [powershell, '-NoProfile', '-NonInteractive', '-EncodedCommand', command]
    const env = { ...process.env, BUN_NATIVE_MTIME_EVIDENCE_PATH: path }
    const result = run
      ? run(argv, env)
      : Bun.spawnSync(argv, { env, stdout: 'pipe', stderr: 'ignore', timeout: 15_000 })
    if (!result.success || result.stdout.length > 64) return null
    return parseFiletimeEvidence(Buffer.from(result.stdout).toString())
  } catch {
    return null
  }
}

/** Set an exact timestamp on a private test file for the Windows boundary control. */
export function setWindowsFiletime(
  path: string,
  ticks: string,
  platform = process.platform,
  run?: FiletimeRunner
): boolean {
  const parsed = parseFiletimeEvidence(ticks)
  if (platform !== 'win32' || parsed === null || BigInt(parsed) > 2_650_467_743_999_999_999n)
    return false
  try {
    const powershell = `${process.env['SystemRoot']}\\System32\\WindowsPowerShell\\v1.0\\powershell.exe`
    const command = Buffer.from(writeFiletime, 'utf16le').toString('base64')
    const argv = [powershell, '-NoProfile', '-NonInteractive', '-EncodedCommand', command]
    const env = {
      ...process.env,
      BUN_NATIVE_MTIME_EVIDENCE_PATH: path,
      BUN_NATIVE_MTIME_TICKS: parsed,
    }
    const result = run
      ? run(argv, env)
      : Bun.spawnSync(argv, { env, stdout: 'pipe', stderr: 'ignore', timeout: 15_000 })
    return result.success
  } catch {
    return false
  }
}
