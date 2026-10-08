"""Versioned host-owned contracts. Generated code cannot edit these gates."""
import json

POLICY = {
    'version': 'local-v1',
    'light': {'model': 'gpt-6-luna', 'effort': 'medium'},
    'balanced': {'model': 'gpt-6.1-sol', 'effort': 'medium'},
    'strong': {'model': 'gpt-6.1-sol', 'effort': 'high'},
}
FILES = {
    'backend': ['server.mjs', 'README.md'],
    'frontend': ['public/index.html', 'public/app.js', 'public/styles.css'],
}
AC = ['CV-UI', 'CV-SESSION', 'CV-CHALLENGE', 'CV-COMMIT', 'CV-FILE', 'CV-RATE', 'CV-DOC']
CONTRACT = r'''Build a complete Vietnamese CV upload application from empty files.
Use Node 24 built-ins only (node:http, node:sqlite, crypto, fs). No packages, no shell,
no dynamic code execution, subprocesses, workers, native addons, or unrelated features.
Host owns package.json. Allowed files: server.mjs, README.md, public/index.html,
public/app.js, public/styles.css. Server serves HTML and exact public assets; no arbitrary
path traversal or public CV download. Use accessible, polished responsive Vietnamese UI.
Must include review/edit before submit and clear receipt. Preserve inputs/file on edit.

Environment: PORT (default 3200), HOST (default 127.0.0.1), APP_ORIGIN (default http://127.0.0.1:3200),
DATA_DIR (default .data), CV_GUARD_MODE (locked default, demo, turnstile),
TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY. Docker gate sets HOST=0.0.0.0, PORT=8080,
DATA_DIR=/data, APP_ORIGIN to the host-published loopback origin, CV_GUARD_MODE=demo.
Bind HOST/PORT as provided. Data only under DATA_DIR. In demo APP_ORIGIN must be loopback.
GET / returns HTML with visible mode banner; GET /api/config -> {mode,siteKey|null}.
No startup network calls. Turnstile verifier only calls Cloudflare Siteverify when mode=turnstile.
Locked mode refuses POST with 503. Missing real keys fail closed; never auto-demote to demo.

ALL POST API require exact Origin=APP_ORIGIN and Host=new URL(APP_ORIGIN).host.
POST /api/session (empty body allowed) -> 200 {nonce}; Set-Cookie cv_session=<opaque>;
HttpOnly; SameSite=Strict; Path=/; 15min lifetime, Secure under HTTPS. Reuse valid session.
All other POSTs require cookie and X-CSRF-Token nonce, invalid/missing ->403.
POST /api/prepare JSON {name,email,role,consent:true,file:{name,size,sha256},telemetry?:{elapsedMs,edits,pastes}}
->200 {pendingId,preview:{name,email,role,file},mode,siteKey}. Accept role: Kỹ sư phần mềm,
Thiết kế sản phẩm, Vị trí khác. Normalize/validate lengths and email. PDF extension,
size 20..5242880, 64 lowercase hex SHA256, no path separators/control chars in filename.
Store frozen payload server-side. New prepare invalidates prior pending for that session.
Pending TTL <=10min/session TTL. Only one successful application per session.
POST /api/verify with X-CV-Pending and JSON {token} ->200 {permit,expiresAt}.
Demo token exact 'local-demo-confirmed', explicitly labelled NOT real bot protection.
Real mode Siteverify with 8sec timeout, require success===true, exact expected hostname,
action==='cv_submit', cdata===pendingId. Client widget uses same action/cData, error/expiry resets.
Failed token ->403, provider error ->503. One opaque permit stored hashed, <=120sec,
bound to session+pending. Parallel verification grants only one permit.
POST /api/commit headers X-CV-Pending, X-Action-Permit, X-CSRF-Token,
Content-Type application/pdf; body RAW PDF bytes. Check permit BEFORE reading body.
Incrementally bound body <=5MiB and timeout <=15sec. Match exact prepared length and hash,
sniff %PDF- header and terminal %%EOF, quarantine unscanned, not an AV claim.
SQLite transaction: revalidate freshness/permit/session after async reads, insert application,
consume permit atomically. {receipt:<opaque>,duplicate:false,status:'quarantined_unscanned'}
with 201; identical retry within TTL ->200 same receipt duplicate:true, no second effect.
Changed bytes ->409; missing/invalid permit ->403; invalid PDF ->400; too large ->413.
Second valid session cannot use first pending/permit (403 or409).
GET /api/receipt using current valid cookie ->200 {receipt} after submission or404 otherwise.

Rate limits enforced by server: >=valid normal flow but session at most30 POST/minute,
session issuance<=60/min, global<=240/min; 3 successful submissions/email/day; storage256MiB.
Return429 with accurate Retry-After. Do not trust bot score/IP headers. Missing/fast/pasted
telemetry never bypasses challenge and never alone blocks users. Telemetry contains no text.
SQLite outside public under DATA_DIR; block DATA_DIR resolving inside public (case insensitive Windows),
no dynamic fs path from request. Clean expired session/pending/rates without deleting live receipts.
Cache-Control private,no-store and nosniff on sensitive responses; CSP compatible with own external JS
and Cloudflare only; no inline event handlers; object-src none, frame-ancestors none.
Limits also apply to malformed/missing Content-Length; JSON<=12KB.
README explains run config, local demo, no all-agent-blocking guarantee, unscanned quarantine,
Turnstile/domain/edge/AV/operational retention not live-verified, no public deployment.
No claims of email delivery, recruiters reviewing, ML accuracy, fake security, or actual job openings.
Host gate will launch actual container server and exercise this API, plus a separate locked instance.
Acceptance IDs: CV-UI(form/review/edit/receipt), CV-SESSION(origin/session/nonce),
CV-CHALLENGE(bound challenge), CV-COMMIT(atomic/idempotent), CV-FILE(bounds/quarantine),
CV-RATE(quotas), CV-DOC(honest limitations). Generated artifacts may not change this contract.
'''

def obj(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}

STRING = {'type': 'string'}
PLAN_SCHEMA = obj({'title': STRING, 'brief': STRING, 'non_goals': {'type': 'array', 'items': STRING},
    'tasks': {'type': 'array', 'items': obj({'id': STRING, 'title': STRING,
        'kind': {'type': 'string', 'enum': list(FILES)}, 'risk': {'type': 'string', 'enum': ['low','medium','high']},
        'depends_on': {'type':'array','items':STRING}, 'acceptance_ids': {'type':'array','items':{'type':'string','enum':AC}}})}})
ARTIFACT_SCHEMA = obj({'summary': STRING, 'files': {'type':'array','items':obj({'path':STRING,'content':STRING})},
    'backlog': {'type':'array','items':STRING}})
REVIEW_SCHEMA = obj({'summary': STRING, 'findings': {'type':'array','items':obj({
    'requirement': STRING, 'severity': {'type':'string','enum':['blocking','suggestion']},
    'path': STRING, 'evidence': STRING, 'fix': STRING})}})

def route(stage, risk='medium', policy=None):
    policy = policy or POLICY
    tier = 'strong' if stage in ('backend','review','repair') or risk == 'high' else 'light' if stage == 'plan' else 'balanced'
    return dict(policy[tier], tier=tier, reason=f'{stage}/{risk}; profile minimum + policy {policy["version"]}')

def validate_plan(plan):
    tasks = plan.get('tasks', [])
    if len(tasks) != 2 or {t.get('kind') for t in tasks} != set(FILES):
        raise ValueError('Plan must have exactly backend and frontend tasks within profile.')
    ids = {t.get('id') for t in tasks}
    if len(ids) != 2 or any(not isinstance(i,str) or not i.isascii() or not i.replace('-','').isalnum() for i in ids):
        raise ValueError('Plan task IDs invalid/duplicate.')
    covered = set()
    completed, ordered = set(), []
    for t in tasks:
        if t.get('risk') not in ('low','medium','high') or not set(t.get('depends_on',[])) <= ids or t['id'] in t['depends_on']:
            raise ValueError('Invalid risk/dependencies.')
        if not set(t['acceptance_ids']) <= set(AC): raise ValueError('Plan expands acceptance scope.')
        covered.update(t['acceptance_ids'])
    while len(ordered) < len(tasks):
        ready = [t for t in tasks if t['id'] not in completed and set(t['depends_on']) <= completed]
        if not ready: raise ValueError('Cyclic dependencies.')
        task = ready[0]; ordered.append(task); completed.add(task['id'])
    if covered != set(AC): raise ValueError('Plan does not cover all fixed acceptance requirements.')
    return ordered

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':'))
