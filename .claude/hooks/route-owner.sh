#!/usr/bin/env bash
# Routes an Edit/Write target to its owning role agent and injects the
# owner + verification gate + known trap for that path.
# Always exits 0 — this hook informs, it never blocks an edit.

set -u

payload=$(cat)
path=$(printf '%s' "$payload" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
[ -z "$path" ] && exit 0

# Repo-relative
rel=${path#"${CLAUDE_PROJECT_DIR:-}"/}
rel=${rel#/Users/nkalev/git-repos-personal/bsdmirror/}

owner=""
gate=""
trap_note=""

case "$rel" in
  frontend/public/admin/js/admin.js)
    owner="developer (logic) + web-designer (appearance) — SHARED FILE"
    gate="developer: tests pass, ruff clean, escaping via the helper. web-designer: both themes, AA contrast, no new hardcoded values."
    trap_note="456 of 1162 lines are HTML markup. Logic vs appearance is a hard boundary: do not restyle while fixing logic, and do not change escaping while restyling. renderUsers (:535), renderAuditLogs (:589) and Toast.show (:291) still interpolate raw." ;;
  nginx/*|nginx/sites/*)
    owner="devops-sre"
    gate="nginx -t on EVERY site config touched, then stack healthy + /health responding. Paste real output."
    trap_note="add_header does NOT inherit: any add_header at a lower level drops all inherited ones. location /admin (default.conf:112) already serves the admin panel with no CSP and no HSTS. Fixing that also breaks the Google Fonts @import in both stylesheets — one change, not two. Loop in appsec-reviewer." ;;
  backend/app/models/*|sync/sync_service.py)
    owner="developer (schema) — with devops-sre if migrations are involved"
    gate="Both model definitions updated in the SAME change; tests pass."
    trap_note="Models are duplicated: backend/app/models/ and sync/sync_service.py:452-512 must match exactly. They drifted once already (commit 798ae79, Postgres enum mismatch). There are no migrations — schema comes from Base.metadata.create_all, so a column change is silently ignored on an existing deploy." ;;
  backend/*|sync/*)
    owner="developer"
    gate="Tests written and passing, ruff clean, no blocking call in an async path."
    trap_note="bcrypt.checkpw runs synchronously on the event loop (core/security.py:32). auth.py:169 short-circuits before hashing — a username-enumeration timing oracle." ;;
  docker-compose*.yml|scripts/*|rsync/*|*/Dockerfile|Dockerfile|.github/*)
    owner="devops-sre"
    gate="docker compose config -q parses; every \${VAR} exists in .env; stack reaches healthy; /health + login round-trip verified."
    trap_note="30 of this repo's first 36 commits were post-deploy config fixes. Verify before reporting done." ;;
  *.css|frontend/public/*.html|frontend/public/img/*)
    owner="web-designer"
    gate="Both light and dark themes checked, mobile + desktop, WCAG AA contrast, no new hardcoded values outside the tokens."
    trap_note="Two independent token sets exist: style.css and admin.css each declare their own token set (32 and 27 unique properties), diverging on the same concepts (--card-bg vs --bg-card). Both @import Google Fonts, which the production CSP does not permit." ;;
  frontend/public/js/*)
    owner="developer"
    gate="Behavior verified in the browser; escaping via the helper."
    trap_note="" ;;
  *) exit 0 ;;
esac

ctx="[role routing] ${rel} is owned by: ${owner}
Definition of done — ${gate}"
[ -n "$trap_note" ] && ctx="${ctx}
Known trap — ${trap_note}"
ctx="${ctx}
Prefer delegating to that agent. If editing directly, you still owe its verification gate: evidence before assertions."

jq -n --arg c "$ctx" \
  '{hookSpecificOutput:{hookEventName:"PreToolUse", additionalContext:$c}}'
exit 0
