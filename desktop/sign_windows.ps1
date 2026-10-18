param([Parameter(Mandatory=$true)][ValidateSet('app', 'installer')][string]$Target)
$ErrorActionPreference = 'Stop'
if (-not $env:WINDOWS_CERTIFICATE_P12 -or -not $env:WINDOWS_CERTIFICATE_PASSWORD) {
    throw 'Stable release requires a trusted Windows code-signing certificate and password'
}
$pfx = Join-Path $env:RUNNER_TEMP 'novelcraft-signing.pfx'
$certificate = $null
try {
    [IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($env:WINDOWS_CERTIFICATE_P12))
    $password = ConvertTo-SecureString $env:WINDOWS_CERTIFICATE_PASSWORD -AsPlainText -Force
    $certificate = @(Import-PfxCertificate -FilePath $pfx -Password $password -CertStoreLocation Cert:\CurrentUser\My | Where-Object HasPrivateKey)
    if (@($certificate).Count -ne 1) { throw 'PFX must contain one signing identity' }
    $tool = Get-ChildItem 'C:\Program Files (x86)\Windows Kits\10\bin\*\x64\signtool.exe' |
        Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $tool) { throw 'Windows SDK signtool not found' }
    $files = if ($Target -eq 'app') {
        @('desktop/dist/NovelCraft/NovelCraft.exe', 'desktop/dist/NovelCraft/NovelCraftRuntime.exe')
    } else { @('desktop/dist/NovelCraft-Windows-x64-Setup.exe') }
    foreach ($file in $files) {
        & $tool.FullName sign /sha1 $certificate.Thumbprint /s My /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 $file
        if ($LASTEXITCODE -ne 0) { throw 'Authenticode signing failed' }
        & $tool.FullName verify /pa /all $file
        if ($LASTEXITCODE -ne 0) { throw 'Authenticode verification failed' }
    }
} finally {
    Remove-Item $pfx -Force -ErrorAction SilentlyContinue
    if ($certificate) { Remove-Item ('Cert:\CurrentUser\My\' + $certificate.Thumbprint) -DeleteKey }
}
