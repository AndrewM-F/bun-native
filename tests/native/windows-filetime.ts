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

export function parseFiletimeEvidence(text: string): string | null {
  const value = text.trim()
  if (!/^(0|[1-9]\d{0,19})$/.test(value)) return null
  return BigInt(value) <= 0xffff_ffff_ffff_ffffn ? value : null
}

/** Best effort: an unavailable diagnostic must never replace the original failure. */
export function windowsFiletimeEvidence(path: string): string | null {
  if (process.platform !== 'win32') return null
  try {
    const powershell = `${process.env['SystemRoot']}\\System32\\WindowsPowerShell\\v1.0\\powershell.exe`
    const command = Buffer.from(readFiletime, 'utf16le').toString('base64')
    const result = Bun.spawnSync(
      [powershell, '-NoProfile', '-NonInteractive', '-EncodedCommand', command],
      {
        env: { ...process.env, BUN_NATIVE_MTIME_EVIDENCE_PATH: path },
        stdout: 'pipe',
        stderr: 'ignore',
        timeout: 15_000,
      }
    )
    if (!result.success || result.stdout.length > 64) return null
    return parseFiletimeEvidence(result.stdout.toString())
  } catch {
    return null
  }
}
