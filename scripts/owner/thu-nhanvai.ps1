<#
.SYNOPSIS
  NHANVAI M2: a trial ledger with an internal plan of four sub-tasks like the owner's picture of 25/11 22:34, opened on the tracking page
  of the trial runtime (built from the commit that passed M1), to compare the "Danh sach task" block with the picture.
.DESCRIPTION
  Default = dry run: checks the trial runtime and the folder, shows what would be done, writes nothing, starts nothing.
  -ApDung (your own terminal only; refused inside an AI session, because the trial plan is approved in your name):
    1. creates the trial folder D:\OneCrewRuns\nhanvai\thu: a small git project (du-an), its own ledger (so) and its own machine folders
       (may); the folder must not exist yet (run -QuayVe -ApDung first to set an older one aside);
    2. with the trial runtime's python: proposes and approves the trial plan NHANVAITHU, writes the internal plan of four sub-tasks with
       role labels and a roles table, runs sub-tasks 1 and 2 to "checked" with fixture workers, starts sub-task 3 and leaves it running;
    3. reads the trial ledger back (track show --json) and checks: 1 and 2 checked, 3 running, 4 waiting for 2 and 3, the four labels;
    4. starts the tracking page of the trial ledger (track open --plan NHANVAITHU --no-browser) and prints its address.
  Then open the address, open "Xem sau" > "Agent va viec nen": the "Danh sach task" block is above the table "Phan viec".
  Compare it with the picture: 4 rows, number and name in bold, @backend/@frontend/@lead under the name, on the right
  "xong . cong dat" (green) twice, "dang lam" (orange), "cho task 2, 3" (grey).
  -QuayVe -ApDung: stops the trial tracking page and renames the trial folder to thu-cu-<time> (nothing is deleted). -QuayVe alone = its dry run.
  Nothing here touches the real ledger, the development ledger, the installed runtimes or the machine-wide hook.
  Exit 0 = every step passed; 1 = a step failed; 2 = -ApDung inside an AI session.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\owner\thu-nhanvai.ps1
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\owner\thu-nhanvai.ps1 -ApDung
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\owner\thu-nhanvai.ps1 -QuayVe -ApDung
#>
param(
    [switch]$ApDung,
    [switch]$QuayVe,
    [string]$RuntimeThu = 'D:\OneCrewRuns\nhanvai\runtime-thu\Scripts\onecrew.exe',
    [string]$Thu = 'D:\OneCrewRuns\nhanvai\thu'
)
$ErrorActionPreference = 'Continue'
if ($ApDung -and ($env:CLAUDE_CODE_CHILD_SESSION -or $env:CLAUDECODE)) { Write-Host 'KHONG DAT: -ApDung dang o trong phien AI; mo terminal rieng cua ban roi chay lai.' -ForegroundColor Red; exit 2 }
$savedEncoding = [Console]::OutputEncoding
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
$OutputEncoding = [Text.Encoding]::UTF8
$noBom = New-Object System.Text.UTF8Encoding $false
$Plan = 'NHANVAITHU'
$Project = Join-Path $Thu 'du-an'
$So = Join-Path $Thu 'so'
$May = Join-Path $Thu 'may'
$PyThu = Join-Path (Split-Path -Parent $RuntimeThu) 'python.exe'
$mode = if ($ApDung) { 'CHAY THAT' } else { 'CHAY THU (khong ghi gi, khong mo gi)' }
Write-Host ('NHANVAI M2 - ' + $mode + $(if ($QuayVe) { ' - QUAY VE' } else { '' }))

# The trial runtime's python writes this seed into the trial folder and runs it. ASCII only: the Vietnamese names are \u escapes.
$Seed = @'
"""seed-nhanvai.py <trial folder> dung|kiem: written by scripts/owner/thu-nhanvai.ps1 (NHANVAI M2); runs with the trial runtime's python.
dung: git project, trial plan proposed and approved by the owner, internal plan of four sub-tasks like the owner's picture of 25/11 22:34
(role labels, roles table), sub-tasks 1 and 2 run and checked with fixture workers, sub-task 3 started and left running (this process
ends inside its worker). kiem: prints the four sub-tasks as the tracking detail shows them (JSON)."""
import json
import os
import subprocess
import sys
from pathlib import Path

base, mode = Path(sys.argv[1]), sys.argv[2]
project, state = base / 'du-an', base / 'so'
NAME = 'NHANVAITHU'
FILES = {'api/contract.md': '# API contract (trial)\n', 'api/server.py': 'print("trial")\n', 'ui/app.js': '// trial\n',
         'docs/integration.md': '# integration notes (trial)\n'}
TITLES = {'BE1': 'BE vi\u1ebft h\u1ee3p \u0111\u1ed3ng API', 'BE2': 'BE l\xe0m API', 'FE': 'FE l\xe0m giao di\u1ec7n',
          'LEAD': 'Lead ki\u1ec3m t\xedch h\u1ee3p, ghi quy\u1ebft \u0111\u1ecbnh'}
CAPS = ['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine']
ROLES = {'backend': ['api/'], 'frontend': ['ui/'], 'lead': ['docs/']}


def contract():
    return {'schema_version': 2, 'title': 'NHANVAI th\u1eed: b\u1ed1n vi\u1ec7c con nh\u01b0 \u1ea3nh c\u1ee7a ch\u1ee7', 'size': 'S',
            'understanding': {'restated_goal': 'Trial ledger of NHANVAI: four sub-tasks with role labels.',
                              'target': {'repo': '.', 'ref': 'HEAD', 'paths': ['api/contract.md']}, 'assumptions': [], 'confidence': 'high', 'unknowns': []},
            'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'api/contract.md'}, 'why': 'the work is there'}],
            'output': ['The sample exists'], 'scope': {'owned': sorted(FILES)}, 'non_goals': ['Nothing else'],
            'items': [{'id': 'I1', 'title': 'Do it', 'tier': 'must', 'milestone': 'M1'},
                      {'id': 'S1', 'title': 'Nice to have', 'tier': 'should'}, {'id': 'W1', 'title': 'Never', 'tier': 'wont'}],
            'milestones': [{'id': 'M1', 'title': 'Milestone M1', 'verifier': {'type': 'command', 'config': {'argv': [sys.executable, '-c', 'print("ok")']}},
                            'covers': ['O1']}],
            'budget': {'max_calls': 100, 'time': 120}, 'attention': {'questions': 1}, 'profile_version': None,
            'authority': {'edit': True, 'commands': True, 'edit_tests': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']}}


def node(nid, role, write, depends=(), integration=False):
    return {'id': nid, 'goal': TITLES[nid], 'role': role, 'input': [], 'output': ['Evidence for O1'], 'acceptance': ['O1'],
            'depends': [{'node': upstream, 'requires': requires} for upstream, requires in depends], 'read': ['api/contract.md'],
            'write': list(write), 'resources': [], 'estimate_seconds': [1, 2], 'execution_cap_seconds': 60, 'budget_calls': 1,
            'checks': [{'id': 'check-' + nid, 'spec': 'Check the declared O1 output of ' + nid}], 'integration': integration}


NODES = [node('BE1', 'backend', ['api/contract.md']),
         node('BE2', 'backend', ['api/server.py'], [('BE1', 'verified')]),
         node('FE', 'frontend', ['ui/app.js'], [('BE1', 'verified')]),
         node('LEAD', 'lead', ['docs/integration.md'], [('BE1', 'verified'), ('BE2', 'accepted'), ('FE', 'verified')], integration=True)]


def git(*args):
    subprocess.run(['git', '-C', str(project), *args], check=True, capture_output=True)


def make_project():
    project.mkdir(parents=True)
    git('init', '-q'); git('config', 'user.name', 'thu-nhanvai'); git('config', 'user.email', 'thu-nhanvai@localhost')
    for rel, text in FILES.items():
        (project / rel).parent.mkdir(parents=True, exist_ok=True)
        (project / rel).write_text(text, encoding='utf-8', newline='\n')
    git('add', '.'); git('commit', '-q', '-m', 'trial project of NHANVAI')


def build():
    from onecrew.control import Control, migrate
    from onecrew.ledger import Ledger
    from onecrew.snapshots import Snapshots
    from onecrew.v2 import engine, internal_plan as ip, plan as plans
    make_project()
    ledger = Ledger(project, state)
    plans.propose(ledger, NAME, contract(), 'claude-opus-5-5', workflow=True, capabilities=CAPS)
    plans.approve(ledger, NAME, 'owner', 'thu-nhanvai.ps1 -ApDung: the owner builds the NHANVAI trial ledger')
    os.environ['ONECREW_ACTOR'] = 'claude'                 # the engine's own steps below are the AI's, as in the test fixture
    store = Snapshots(ledger.state_root)
    migrate(ledger)
    control = Control(ledger)
    result = ip.revise(ledger, NAME, NODES, reason='Four sub-tasks like the picture of 25/11 22:34', evidence=['api/contract.md:1'], roles=ROLES)
    print(json.dumps({'internal_revision': result['internal_revision'], 'role_area_report': result.get('role_area_report')}), flush=True)

    def execute(ledger, control, task, item, attempt):
        control.launched(attempt['id'], attempt['generation'], {'trial': True})
        artifact = store.blob(('artifact-' + item['id']).encode())
        receipt = store.blob(('executor-' + item['id']).encode())
        control.finish(attempt['id'], attempt['generation'], {'trial': True, 'artifact': artifact})
        return {'artifact': artifact, 'receipt': receipt}

    def checker(item, artifact):
        return {'artifact': artifact, 'checks': [{'id': check['id'], 'result': 'pass', 'evidence': store.blob(b'trial check passed')}
                                                for check in item['checks']]}

    def leave_running(ledger, control, task, item, attempt):
        control.launched(attempt['id'], attempt['generation'], {'trial': True})
        print(json.dumps({'running': item['id']}), flush=True)
        os._exit(0)                                         # sub-task 3 stays "running" in the trial ledger

    for nid in ('BE1', 'BE2'):
        done = engine.step(ledger, NAME, execute, control=control)
        if done.get('node') not in (None, nid): raise SystemExit('expected sub-task ' + nid + ', the engine ran ' + str(done.get('node')))
        engine.verify(ledger, NAME, nid, checker)
        print(json.dumps({'checked': nid}), flush=True)
    engine.step(ledger, NAME, leave_running, control=control)
    raise SystemExit('sub-task FE did not start')


def check():
    from onecrew.v2 import tracking
    detail = tracking.detail(state, NAME)
    print(json.dumps({nid: {'phase': n.get('phase'), 'state': n.get('state'), 'role': n.get('role'), 'waits_for': n.get('waits_for')}
                      for nid, n in detail['nodes'].items()}), flush=True)


build() if mode == 'dung' else check()
'@

function Invoke-Thu([string]$exe, [string[]]$argv) {
    # one trial command with the trial machine folders; every variable is given back right after it
    $saved = @{ LOCALAPPDATA = $env:LOCALAPPDATA; APPDATA = $env:APPDATA; PYTHONUTF8 = $env:PYTHONUTF8; PYTHONIOENCODING = $env:PYTHONIOENCODING }
    $env:LOCALAPPDATA = Join-Path $May 'local'; $env:APPDATA = Join-Path $May 'roaming'; $env:PYTHONUTF8 = '1'; $env:PYTHONIOENCODING = 'utf-8'
    try {
        $errFile = Join-Path $Thu 'loi-lenh.txt'
        $out = (& $exe @argv 2> $errFile | ForEach-Object { "$_" }) -join "`n"
        $code = $LASTEXITCODE
        $err = if (Test-Path -LiteralPath $errFile) { [IO.File]::ReadAllText($errFile) } else { '' }
        return [pscustomobject]@{ Code = $code; Text = $out; Err = $err }
    } finally {
        foreach ($k in $saved.Keys) { Set-Item -Path ('env:' + $k) -Value $saved[$k] -ErrorAction SilentlyContinue; if ($null -eq $saved[$k]) { Remove-Item -Path ('env:' + $k) -ErrorAction SilentlyContinue } }
    }
}

function Stop-Here([string]$why) {
    Write-Host ('KHONG DAT: ' + $why) -ForegroundColor Red
    [Console]::OutputEncoding = $savedEncoding
    exit 1
}

try {
    if (-not (Test-Path -LiteralPath $RuntimeThu)) { Stop-Here ('chua co runtime thu ' + $RuntimeThu + ' (nguoi dieu phoi dung goi tu commit da qua M1).') }
    if (-not (Test-Path -LiteralPath $PyThu)) { Stop-Here ('khong thay python cua runtime thu ' + $PyThu) }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Stop-Here 'khong thay git trong PATH.' }
    $versionThu = ((& $RuntimeThu --version 2>&1 | ForEach-Object { "$_" }) -join ' ').Trim()
    Write-Host ('Runtime thu: ' + $RuntimeThu + ' (' + $versionThu + ')')
    Write-Host ('Thu muc thu: ' + $Thu)

    if ($QuayVe) {
        if (-not (Test-Path -LiteralPath $Thu)) { Write-Host 'Khong co thu muc thu: khong co gi de go.'; exit 0 }
        $aside = $Thu + '-cu-' + (Get-Date -Format 'yyyyMMddHHmmss')
        if (-not $ApDung) {
            Write-Host ('[thu] se chay: track stop cho so thu ' + $So)
            Write-Host ('[thu] se doi ten ' + $Thu + ' -> ' + $aside + ' (khong xoa gi)')
            Write-Host 'Chay thu quay ve xong: khong dung gi, khong doi gi.'
            exit 0
        }
        if (Test-Path -LiteralPath $So) {
            $r = Invoke-Thu $RuntimeThu @('--project', $Project, '--state-root', $So, 'track', 'stop')
            Write-Host ('track stop -> exit ' + $r.Code + ': ' + $r.Text)
        }
        Start-Sleep -Seconds 2
        try { Rename-Item -LiteralPath $Thu -NewName (Split-Path -Leaf $aside) -ErrorAction Stop; Write-Host ('Da doi ten thanh ' + $aside) -ForegroundColor Green }
        catch { Stop-Here ('khong doi ten duoc ' + $Thu + ': ' + $_.Exception.Message + ' (dong trang theo doi hay cua so dang mo thu muc nay roi chay lai)') }
        exit 0
    }

    if (Test-Path -LiteralPath $Thu) { Stop-Here ($Thu + ' da co. Chay -QuayVe -ApDung truoc de cat ban cu sang mot ben.') }
    if (-not $ApDung) {
        Write-Host ('[thu] se tao ' + $Thu + ': du-an (repo git nho), so (so thu rieng), may (thu muc may thu rieng)')
        Write-Host ('[thu] se chay ' + $PyThu + ' seed-nhanvai.py dung: de xuat va duyet plan thu ' + $Plan + ' (ten ban), plan noi bo 4 viec con co nhan vai,')
        Write-Host '      viec 1 va 2 chay va kiem dat, viec 3 bat dau va de dang chay'
        Write-Host '[thu] se doc lai so thu (track show --json) va kiem: 1, 2 da kiem; 3 dang chay; 4 cho 2 va 3; bon nhan vai'
        Write-Host ('[thu] se chay: ' + $RuntimeThu + ' --project ' + $Project + ' --state-root ' + $So + ' track open --plan ' + $Plan + ' --no-browser')
        Write-Host 'Chay thu xong: khong ghi gi, khong mo server nao. Chay lai voi -ApDung trong terminal cua ban.'
        exit 0
    }

    New-Item -ItemType Directory -Force -Path $Thu, (Join-Path $May 'local'), (Join-Path $May 'roaming') | Out-Null
    $seedFile = Join-Path $Thu 'seed-nhanvai.py'
    [IO.File]::WriteAllText($seedFile, $Seed, $noBom)

    Write-Host '1/3 Dung so thu (plan noi bo 4 viec con)...'
    $r = Invoke-Thu $PyThu @('-X', 'utf8', $seedFile, $Thu, 'dung')
    Write-Host $r.Text
    if ($r.Code -ne 0 -or $r.Text -notmatch '"running": "FE"') { Stop-Here ('dung so thu that bai (exit ' + $r.Code + '): ' + $r.Err.Substring([Math]::Max(0, $r.Err.Length - 1500))) }

    Write-Host '2/3 Doc lai so thu...'
    $r = Invoke-Thu $PyThu @('-X', 'utf8', $seedFile, $Thu, 'kiem')
    $v = $null; try { $v = $r.Text | ConvertFrom-Json } catch { $v = $null }
    if ($r.Code -ne 0 -or -not $v) { Stop-Here ('khong doc duoc so thu (exit ' + $r.Code + '): ' + $r.Text + ' ' + $r.Err) }
    $want = @(
        @('BE1', 'backend', 'verified', $null, ''),
        @('BE2', 'backend', 'verified', $null, ''),
        @('FE', 'frontend', $null, 'running', ''),
        @('LEAD', 'lead', $null, 'pending', 'BE2,FE')
    )
    $bad = $false
    foreach ($w in $want) {
        $n = $v.($w[0])
        $waits = (@($n.waits_for) | Where-Object { $_ }) -join ','
        $ok = $n -and $n.role -eq $w[1] -and ($null -eq $w[2] -or $n.state -eq $w[2]) -and ($null -eq $w[3] -or $n.phase -eq $w[3]) -and $waits -eq $w[4]
        Write-Host ('  ' + $w[0] + ': @' + $n.role + ', ' + $n.phase + '/' + $n.state + ', cho [' + $waits + '] ' + $(if ($ok) { 'dung' } else { 'SAI' })) -ForegroundColor $(if ($ok) { 'Green' } else { 'Red' })
        if (-not $ok) { $bad = $true }
    }
    if ($bad) { Stop-Here 'so thu khong dung nhu anh (xem dong SAI o tren).' }

    Write-Host '3/3 Mo trang theo doi cua so thu...'
    $r = Invoke-Thu $RuntimeThu @('--project', $Project, '--state-root', $So, 'track', 'open', '--plan', $Plan, '--no-browser')
    $o = $null; try { $o = $r.Text | ConvertFrom-Json } catch { $o = $null }
    if ($r.Code -ne 0 -or -not $o -or -not $o.url) { Stop-Here ('track open that bai (exit ' + $r.Code + '): ' + $r.Text) }
    Write-Host ''
    Write-Host ('DAT: trang theo doi cua so thu: ' + $o.url) -ForegroundColor Green
    Write-Host 'Mo dia chi tren, chon viec NHANVAI thu, mo "Xem sau" > "Agent va viec nen": khoi "Danh sach task" o tren bang "Phan viec".'
    Write-Host 'So voi anh 22:34: 4 dong; so va ten chu dam; @backend, @backend, @frontend, @lead duoi ten;'
    Write-Host 'goc phai: "xong . cong dat" (xanh) hai dong dau, "dang lam" (cam) dong 3, "cho task 2, 3" (xam) dong 4.'
    Write-Host 'Xong thi go: powershell -ExecutionPolicy Bypass -File scripts\owner\thu-nhanvai.ps1 -QuayVe -ApDung'
    exit 0
} finally {
    [Console]::OutputEncoding = $savedEncoding
}
