$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$nodeDir = Join-Path $root ".tools\node-v24.14.1-win-x64"
$env:PATH = "$nodeDir;$env:PATH"
& (Join-Path $nodeDir "npm.cmd") run dev
