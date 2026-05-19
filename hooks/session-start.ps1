# SessionStart hook for the Agentic Engineering System.
# Walks up from $PWD looking for a .agentic/ directory. If found, emits a JSON
# additionalContext payload naming the active project path and basic graph stats.
# Inert (no output) if no .agentic/ is found in any ancestor.
#
# Constraints per machine notes:
#   - PowerShell 5.1 cp1252 read of "..." literals = ASCII-only inside string literals.
#   - Comments and @"..."@ here-strings are safe.
#   - Avoid 2>&1 on native exes.

$ErrorActionPreference = 'Stop'

function Find-AgenticRoot {
    param([string]$Start)
    $cur = (Resolve-Path -LiteralPath $Start).Path
    while ($true) {
        $candidate = Join-Path $cur '.agentic'
        if (Test-Path -LiteralPath $candidate -PathType Container) {
            return $cur
        }
        $parent = Split-Path -Parent $cur
        if (-not $parent -or $parent -eq $cur) { return $null }
        $cur = $parent
    }
}

function Read-GraphStats {
    param([string]$ProjectRoot)
    $dbPath = Join-Path $ProjectRoot '.agentic/graph.db'
    if (-not (Test-Path -LiteralPath $dbPath)) {
        return @{ open_specs = 0; open_critical_findings = 0; db_present = $false }
    }
    # Use the bundled Python CLI to query the graph. Write the script to a
    # temp .py file rather than passing via `python -c <string>` -- PowerShell
    # 5.1's PSNativeCommandArgumentPassing strips embedded double-quotes when
    # invoking native exes, so `-c` mode mangles any SQL literal containing
    # quoted strings. Avoid 2>&1 per machine notes.
    $script = @"
import json, sqlite3, sys
p = sys.argv[1]
c = sqlite3.connect(p)
try:
    specs = c.execute("SELECT count(*) FROM spec WHERE status IN ('draft','dispatched')").fetchone()[0]
except Exception:
    specs = 0
try:
    crits = c.execute("SELECT count(*) FROM finding WHERE severity='Critical' AND status='open'").fetchone()[0]
except Exception:
    crits = 0
print(json.dumps({'open_specs': specs, 'open_critical_findings': crits, 'db_present': True}))
"@
    $tempPy = Join-Path $env:TEMP ("agentic-stats-" + [Guid]::NewGuid().ToString("N") + ".py")
    try {
        # Write UTF-8 without BOM via .NET, since Set-Content -Encoding utf8
        # in PS5.1 emits a BOM that some Python configurations dislike at SOF.
        [IO.File]::WriteAllText($tempPy, $script, (New-Object Text.UTF8Encoding $false))
        $out = & python $tempPy $dbPath
        return ($out | ConvertFrom-Json)
    } catch {
        return @{ open_specs = 0; open_critical_findings = 0; db_present = $true; error = "$_" }
    } finally {
        Remove-Item -LiteralPath $tempPy -Force -ErrorAction SilentlyContinue
    }
}

$root = Find-AgenticRoot -Start $PWD.Path
if (-not $root) { exit 0 }

$stats = Read-GraphStats -ProjectRoot $root

$context = @"
Agentic Engineering System is active for this project.
Project root: $root
Open specs: $($stats.open_specs)
Open critical findings: $($stats.open_critical_findings)
State lives under $($root)\.agentic\graph.db (SQLite + sqlite-vec).
All durable writes must flow through the agentic-graph MCP server tools.
Skill entry point: skills/router/SKILL.md.
"@

$payload = @{ additionalContext = $context } | ConvertTo-Json -Depth 4
Write-Output $payload
exit 0
