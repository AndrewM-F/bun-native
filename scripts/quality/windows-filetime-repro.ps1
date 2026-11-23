param(
  [Parameter(Mandatory = $true)][string]$Output,
  [ValidateRange(1, 20)][int]$Pairs = 20
)

$ErrorActionPreference = 'Stop'
if (!$IsWindows -or !(Test-Path -LiteralPath $Output -PathType Container)) {
  throw 'A Windows runner and existing evidence directory are required'
}
$root = (Resolve-Path -LiteralPath $Output).Path
$hostPath = (Resolve-Path -LiteralPath $env:BUN_NATIVE_HOST).Path
$bun = (Get-Command bun -CommandType Application).Source
$package = Join-Path $root 'package'
$manifest = Get-Content -Raw (Join-Path $package 'manifest.json') | ConvertFrom-Json
$aot = (Resolve-Path -LiteralPath (Join-Path $package $manifest.application.file)).Path
$fixture = (Resolve-Path 'tests/native/filesystem-grants.ts').Path
$revision = bun -e 'process.stdout.write(Bun.revision)'
if ($LASTEXITCODE -ne 0) { throw 'Cannot identify the pinned Bun runtime' }
$plan = @{
  pairs = $Pairs
  ordering = 'development/AOT on even pairs; AOT/development on odd pairs'
  assertion = 'exact native whole milliseconds against Bun nanoseconds; retain all outcomes'
  boundaryControl = 'also set and independently read the 9999-tick FILETIME boundary'
  source = (git rev-parse HEAD)
  bunRevision = $revision
  bunSha256 = (Get-FileHash -Algorithm SHA256 $bun).Hash
  fixtureSha256 = (Get-FileHash -Algorithm SHA256 $fixture).Hash
  hostSha256 = (Get-FileHash -Algorithm SHA256 $hostPath).Hash
  aotSha256 = (Get-FileHash -Algorithm SHA256 $aot).Hash
  os = [Runtime.InteropServices.RuntimeInformation]::OSDescription
  architecture = [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
  image = $env:ImageVersion
}
$plan | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $root 'plan.json')
$records = [Collections.Generic.List[object]]::new()
for ($pair = 0; $pair -lt $Pairs; $pair++) {
  $modes = if ($pair % 2 -eq 0) { @('development', 'aot') } else { @('aot', 'development') }
  foreach ($mode in $modes) {
    $name = '{0:d2}-{1}' -f $pair, $mode
    $directory = Join-Path $root $name
    New-Item -ItemType Directory -Path $directory | Out-Null
    $record = [ordered]@{ pair = $pair; mode = $mode; status = 'failed'; exit = $null; error = $null }
    try {
      $start = [Diagnostics.ProcessStartInfo]::new()
      $start.FileName = if ($mode -eq 'development') { $bun } else { $aot }
      if ($mode -eq 'development') { $start.ArgumentList.Add($fixture) }
      $start.WorkingDirectory = (Get-Location).Path
      $start.UseShellExecute = $false
      $start.RedirectStandardOutput = $true
      $start.RedirectStandardError = $true
      $start.Environment['BUN_NATIVE_FILESYSTEM_EVIDENCE'] = $directory
      $start.Environment['BUN_NATIVE_FILESYSTEM_MODE'] = $mode
      $start.Environment['BUN_NATIVE_MTIME_BOUNDARY'] = '1'
      $process = [Diagnostics.Process]::new()
      $process.StartInfo = $start
      if (!$process.Start()) { throw 'Fixture process did not start' }
      $stdout = $process.StandardOutput.ReadToEndAsync()
      $stderr = $process.StandardError.ReadToEndAsync()
      $timedOut = $false
      if (!$process.WaitForExit(60000)) {
        $process.Kill($true)
        $process.WaitForExit()
        $timedOut = $true
      }
      $record.exit = $process.ExitCode
      [IO.File]::WriteAllText((Join-Path $directory 'stdout.log'), $stdout.GetAwaiter().GetResult())
      [IO.File]::WriteAllText((Join-Path $directory 'stderr.log'), $stderr.GetAwaiter().GetResult())
      if ($timedOut) { throw 'Fixture exceeded its 60-second diagnostic deadline' }
      if ($record.exit -ne 0) { throw "Fixture failed with exit $($record.exit)" }
      $report = Get-Content -Raw (Join-Path $directory 'filesystem-grants.json') | ConvertFrom-Json
      if ($report.platform -ne 'win32' -or $report.backend -ne 'ntcreatefile_walk' -or $report.mode -ne $mode -or $report.revision -ne $revision) {
        throw 'Fixture report identity mismatch'
      }
      if ($null -eq $report.outcomes.mtimeBoundary -or $report.outcomes.mtimeBoundary.nativeModifiedMs -ne 1700000000000 -or $report.outcomes.mtimeBoundary.rawWindowsFiletimeTicks -ne '133444736000009999') {
        throw 'The native FILETIME boundary control was not verified'
      }
      $record.status = 'passed'
    } catch {
      $record.error = $_.Exception.Message
    } finally {
      if ($process) { $process.Dispose(); $process = $null }
    }
    $records.Add([pscustomobject]$record)
    ConvertTo-Json -InputObject ($records.ToArray()) -Depth 5 | Set-Content -Encoding utf8 (Join-Path $root 'results.json')
    Write-Output "$name $($record.status)"
  }
}
if (@($records | Where-Object { $_.status -ne 'passed' }).Count -gt 0) {
  throw 'At least one filesystem trial failed; all results were retained'
}
