param(
  [Parameter(Mandatory = $true)][string]$Output,
  [Parameter(Mandatory = $true)][string]$LlvmBin
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
if (!$IsWindows -or !(Test-Path -LiteralPath $Output -PathType Container)) {
  throw 'A Windows runner and existing evidence directory are required'
}
$root = (Resolve-Path -LiteralPath $Output).Path
$clang = Join-Path $LlvmBin 'clang-cl.exe'
$linker = Join-Path $LlvmBin 'lld-link.exe'
$librarian = Join-Path $LlvmBin 'llvm-lib.exe'
$version = & $clang --version
if ($LASTEXITCODE -ne 0 -or ($version -join "`n") -notmatch 'clang version 23\.1\.1') {
  throw 'The control requires LLVM 23.1.1'
}
$records = [Collections.Generic.List[object]]::new()
foreach ($linkage in @('weak', 'strong')) {
  foreach ($lto in @('off', 'on')) {
   foreach ($definitionLto in @('off', 'on')) {
    foreach ($placement in @('object', 'archive')) {
    $directory = Join-Path $root "$linkage-$lto-definition-$definitionLto-$placement"
    New-Item -ItemType Directory -Path $directory | Out-Null
    $attribute = if ($linkage -eq 'weak') { '__attribute__((weak)) ' } else { '' }
    $declaration = "extern `"C`" ${attribute}void WTFTimer__update(int);"
    $a = "$declaration`nextern `"C`" __declspec(dllexport) int callA(int x) { if (WTFTimer__update) WTFTimer__update(x); return x + 1; }`n"
    $b = "$declaration`nextern `"C`" __declspec(dllexport) int callB(int x) { if (WTFTimer__update) WTFTimer__update(x); return x + 2; }`n"
    $c = 'extern "C" void WTFTimer__update(int x) { static volatile int sink; sink = x; }'
    [IO.File]::WriteAllText((Join-Path $directory 'a.cpp'), $a)
    [IO.File]::WriteAllText((Join-Path $directory 'b.cpp'), $b)
    [IO.File]::WriteAllText((Join-Path $directory 'definition.cpp'), $c)
    $objects = @()
    foreach ($name in @('a', 'b', 'definition')) {
      $object = Join-Path $directory "$name.obj"
      $arguments = @('/nologo', '/c', '/O2', '/GS-', '/Zl', "/Fo$object")
      if (($name -ne 'definition' -and $lto -eq 'on') -or ($name -eq 'definition' -and $definitionLto -eq 'on')) { $arguments += '/clang:-flto=thin' }
      $arguments += Join-Path $directory "$name.cpp"
      & $clang @arguments *> (Join-Path $directory "$name-compile.log")
      if ($LASTEXITCODE -ne 0) { throw "Compiler failed for $linkage/$lto/$name" }
      $objects += $object
    }
    if ($placement -eq 'archive') {
      $archive = Join-Path $directory 'definition.lib'
      & $librarian "/out:$archive" $objects[2] *> (Join-Path $directory 'archive.log')
      if ($LASTEXITCODE -ne 0) { throw 'Creating the definition archive failed' }
      $objects = @($objects[0], $objects[1], $archive)
    }
    $dll = Join-Path $directory 'control.dll'
    & $linker /dll /noentry /nodefaultlib /opt:noref /LTCG /opt:lldlto=2 /opt:lldltocgo=2 "/out:$dll" @objects *> (Join-Path $directory 'link.log')
    $linkExit = $LASTEXITCODE
    $records.Add([pscustomobject]@{
      linkage = $linkage
      thinLto = ($lto -eq 'on')
      definitionThinLto = ($definitionLto -eq 'on')
      definitionPlacement = $placement
      linkExit = $linkExit
      sourceSha256 = (Get-FileHash -Algorithm SHA256 (Join-Path $directory 'a.cpp')).Hash
    })
    ConvertTo-Json -InputObject ($records.ToArray()) -Depth 5 | Set-Content -Encoding utf8 (Join-Path $root 'results.json')
    Write-Output "$linkage/$lto/definition-$definitionLto/$placement link exit $linkExit"
    if ($linkage -eq 'strong' -and $linkExit -ne 0) { throw 'Strong-import positive control failed' }
  }
  }
  }
}
$version | Set-Content -Encoding utf8 (Join-Path $root 'llvm-version.txt')
