$ErrorActionPreference = "Stop"
$CanonicalRepoRoot = "C:\Users\maxwe\OneDrive\" + [char]0x6587 + [char]0x4EF6 + "\GitHub\CRT_Master"
$ExpectedOrigin = "https://github.com/qqc168-star/CRT_Master.git"

function Fail-Preflight {
    param([string]$Code, [string]$Detail)
    Write-Output $Code
    Write-Output $Detail
    exit 1
}

# This check intentionally precedes every Git operation.  A cloud/Linux scratch
# environment must not be treated as a substitute for the locked Windows repo.
if ($env:OS -ne "Windows_NT") {
    Fail-Preflight "WRONG_EXECUTION_ENVIRONMENT" "execution_environment=non-Windows"
}

$executionIdentity = "windows;computer=$env:COMPUTERNAME;user=$env:USERNAME"

$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) {
    Fail-Preflight "GIT_UNAVAILABLE" "execution_environment=$executionIdentity"
}

try {
    $repoRoot = (& git rev-parse --show-toplevel 2>$null).Trim()
} catch {
    Fail-Preflight "INVALID_LOCAL_GIT_REPOSITORY" "execution_environment=$executionIdentity"
}

if ($LASTEXITCODE -ne 0 -or -not $repoRoot) {
    Fail-Preflight "INVALID_LOCAL_GIT_REPOSITORY" "execution_environment=$executionIdentity"
}

$normalizedRepoRoot = $repoRoot -replace "/", "\"
$normalizedCanonicalRoot = $CanonicalRepoRoot -replace "/", "\"
if (-not [string]::Equals($normalizedRepoRoot, $normalizedCanonicalRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    Fail-Preflight "WRONG_REPO_ROOT" "repo_root=$repoRoot"
}

$gitDirectory = (& git rev-parse --git-dir 2>$null).Trim()
if ($LASTEXITCODE -ne 0 -or -not $gitDirectory) {
    Fail-Preflight "INVALID_LOCAL_GIT_REPOSITORY" "repo_root=$repoRoot"
}

# Read-only capability probe: no worktree is created, removed, or changed.
$worktrees = & git worktree list --porcelain 2>$null
if ($LASTEXITCODE -ne 0 -or -not ($worktrees -match "^worktree ")) {
    Fail-Preflight "ISOLATED_WORKTREE_UNAVAILABLE" "repo_root=$repoRoot"
}

# Read-only: do not apply, pop, drop, or rewrite any stash.
$stashEntries = @(& git stash list 2>$null)
if ($LASTEXITCODE -ne 0) {
    Fail-Preflight "STASH_READ_FAILED" "repo_root=$repoRoot"
}

$origin = (& git remote get-url origin 2>$null).Trim()
if ($LASTEXITCODE -ne 0 -or -not $origin) {
    Fail-Preflight "ORIGIN_REMOTE_MISSING" "repo_root=$repoRoot"
}

if ($origin -ne $ExpectedOrigin) {
    Fail-Preflight "UNEXPECTED_ORIGIN_REMOTE" "origin=$origin"
}

$credentialHelper = (& git config --get-all credential.helper 2>$null | Select-Object -First 1)
if (-not $credentialHelper) {
    Fail-Preflight "GIT_CREDENTIAL_HELPER_UNAVAILABLE" "origin=$origin"
}

$ErrorActionPreference = "Continue"
& git ls-remote --exit-code --heads origin 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Fail-Preflight "ORIGIN_UNREACHABLE" "origin=$origin"
}

# --dry-run verifies the actual push authentication/authorization path without
# creating or modifying a remote ref.
& git push --dry-run origin HEAD:refs/heads/codex/crt-preflight-push-probe 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Fail-Preflight "GIT_PUSH_NOT_READY" "origin=$origin"
}

Write-Output "PASS"
Write-Output "repo_root=$repoRoot; origin=$origin; stash_count=$($stashEntries.Count); worktree_capability=available; execution_environment=$executionIdentity"
