$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$nodeDir = Join-Path $root ".tools\node-v24.14.1-win-x64"
$node = Join-Path $nodeDir "node.exe"
& $node ".\node_modules\typescript\bin\tsc" -b
& $node ".\node_modules\vite\bin\vite.js" build
