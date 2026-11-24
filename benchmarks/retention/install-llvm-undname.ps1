param([Parameter(Mandatory = $true)][string]$Destination)
$ErrorActionPreference = 'Stop'
$archive = Join-Path $env:RUNNER_TEMP 'llvm-23.1.1-windows-tools.tar.zst'
$extract = Join-Path $env:RUNNER_TEMP 'llvm-23.1.1-undname'
$member = 'clang+llvm-23.1.1-x86_64-pc-windows-msvc/bin/llvm-undname.exe'
Invoke-WebRequest -Uri 'https://github.com/llvm/llvm-project/releases/download/llvmorg-23.1.1/clang%2Bllvm-23.1.1-x86_64-pc-windows-msvc.tar.zst' -OutFile $archive
if ((Get-FileHash -Algorithm SHA256 $archive).Hash -ne 'c8a12d754b5050c5668b56a5425c806792d46c70f7244b1216046164aa4b6462') { throw 'LLVM archive digest mismatch' }
New-Item -ItemType Directory -Path $extract -Force | Out-Null
& tar.exe -xf $archive -C $extract $member
if ($LASTEXITCODE -ne 0) { throw 'LLVM demangler extraction failed' }
$binary = Join-Path $extract $member
if ((Get-FileHash -Algorithm SHA256 $binary).Hash -ne 'ecc25382fdc66442988300e6ad6b0b3ff956e3c1e4bff01442b8d37b9bc6d400') { throw 'LLVM demangler digest mismatch' }
New-Item -ItemType Directory -Path $Destination -Force | Out-Null
Copy-Item -LiteralPath $binary -Destination (Join-Path $Destination 'llvm-undname.exe') -Force
$sample = '??_E_Facet_base@std@@UEAAPEAXI@Z' | & (Join-Path $Destination 'llvm-undname.exe')
if ($LASTEXITCODE -ne 0 -or ($sample -join "`n") -notmatch 'vector deleting dtor') { throw 'LLVM demangler execution check failed' }
Get-FileHash -Algorithm SHA256 (Join-Path $Destination 'llvm-undname.exe') | Format-List
Remove-Item -LiteralPath $archive -Force
Remove-Item -LiteralPath $extract -Recurse -Force
