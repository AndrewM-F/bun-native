param([Parameter(Mandatory = $true)][string]$Output)

$ErrorActionPreference = 'Stop'
if (!$IsWindows -or !(Test-Path -LiteralPath $Output -PathType Container)) {
  throw 'A Windows runner and existing evidence directory are required'
}
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
public static class FiletimeRoundingProbe {
  [StructLayout(LayoutKind.Sequential)] public struct FileTime { public uint Low; public uint High; }
  [StructLayout(LayoutKind.Sequential)] public struct Attributes {
    public uint Flags; public FileTime Creation, Access, Write;
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
$root = (Resolve-Path -LiteralPath $Output).Path
$path = Join-Path $root 'probe-file'
$bun = (Get-Command bun -CommandType Application).Source
$revision = bun -e 'process.stdout.write(Bun.revision)'
if ($LASTEXITCODE -ne 0) { throw 'Cannot identify the pinned Bun runtime' }
$epochTicks = [decimal]116444736000000000
$bases = @([long]1700000000000, [long]1800000000000, [long]2000000000000)
$fractions = @(0, 1, 5000, 9990, 9991, 9992, 9993, 9994, 9995, 9996, 9997, 9998, 9999)
$plan = @{
  source = (git rev-parse HEAD)
  bunRevision = $revision
  bunSha256 = (Get-FileHash -Algorithm SHA256 $bun).Hash
  baseMilliseconds = $bases
  fractionalFiletimeTicks = $fractions
  meaning = 'Independent Win32 FILETIME and Bun stat control; no native host or original failure'
}
$plan | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $root 'plan.json')
$records = [Collections.Generic.List[object]]::new()
$js = 'const fs = require("node:fs"); const p = process.argv[1]; const s = fs.statSync(p); const b = fs.statSync(p,{bigint:true}); process.stdout.write(JSON.stringify({mtimeMs:s.mtimeMs,mtimeNs:b.mtimeNs.toString()}));'
try {
  [IO.File]::WriteAllText($path, 'filetime rounding control')
  foreach ($base in $bases) {
    foreach ($fraction in $fractions) {
      $requested = [long]($epochTicks + [decimal]$base * 10000 + $fraction)
      [IO.File]::SetLastWriteTimeUtc($path, [DateTime]::FromFileTimeUtc($requested))
      $raw = [FiletimeRoundingProbe]::LastWrite($path)
      $result = & $bun -e $js $path | ConvertFrom-Json
      if ($LASTEXITCODE -ne 0 -or $null -eq $result.mtimeMs -or $null -eq $result.mtimeNs) { throw 'Bun stat control failed' }
      $expected = [long][Math]::Floor(([decimal]$raw - $epochTicks) / 10000)
      $delta = [double]$result.mtimeMs - [double]$expected
      $records.Add([pscustomobject]@{
        baseMs = $base
        fractionTicks = $fraction
        requestedFiletime = $requested.ToString()
        observedFiletime = $raw.ToString()
        appliedExactly = ($raw -eq [ulong]$requested)
        integerFloorMs = $expected
        bunMtimeMs = $result.mtimeMs
        bunMtimeNs = $result.mtimeNs
        deltaMs = $delta
        originalComparisonPasses = ([Math]::Abs($delta) -lt 1)
      })
      ConvertTo-Json -InputObject ($records.ToArray()) -Depth 5 | Set-Content -Encoding utf8 (Join-Path $root 'results.json')
    }
  }
} finally {
  Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
}
if (@($records | Where-Object { !$_.appliedExactly }).Count -gt 0) {
  throw 'The filesystem did not preserve every requested FILETIME; observations retained'
}
Write-Output "Measured $($records.Count) exact FILETIME boundaries"
