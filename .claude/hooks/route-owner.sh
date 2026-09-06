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
    gate="developer: tests pass (docker compose run --rm test), ruff clean, markup built with the html`` tagged template. web-designer: both themes, AA contrast, no new hardcoded values."
    trap_note="Most of this 1242-line file is HTML markup, with 24 inline style= attributes still to migrate to classes. Logic vs appearance is a hard boundary: do not restyle while fixing logic, and do not change escaping while restyling. Markup is built with the html`` tagged template (:1118), which escapes every interpolation — do not downgrade one to a plain template literal, and do not introduce SafeHtml (zero uses, deliberately)." ;;
  nginx/*)
    owner="devops-sre"
    gate="nginx -t on EVERY site config touched, then stack healthy + /health responding. Paste real output."
    trap_note="add_header does NOT inherit: any add_header at a level drops every inherited one. Headers live in nginx/snippets/security-headers*.conf and are included at each level that needs them — if you add an add_header here, re-include the snippet here too. Site configs are DIRECTORIES: nginx/sites/{bootstrap,dev,production}/*.conf, so a sites/*.conf glob matches nothing and reports clean. Fonts are self-hosted under /fonts/; do not reintroduce a Google @import. Loop in appsec-reviewer." ;;
  shared/models/*|sync/sync_service.py)
    owner="developer (schema) — with devops-sre if migrations are involved"
    gate="Schema shape verified against the real Postgres schema, not just SQLite; tests pass."
    trap_note="Models live once in shared/models/, imported by both services. They were duplicated until the copies had drifted 17 ways (commit 798ae79 was one such break). Do not reintroduce a second definition. Alembic owns the schema now: a column or type change needs a reviewed migration, not a model edit alone." ;;
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
    trap_note="Tokens live once, in frontend/public/css/tokens.css; style.css and admin.css consume it and must not declare their own. Fonts are self-hosted via @font-face in fonts.css pointing at /fonts/ -- do not reintroduce a Google @import. The CSP is now style-src 'self' with NO 'unsafe-inline', so an inline style= or <style> block will not render at all; use a class. error.css restates the dark mapping for the no-JS error pages and is pinned against tokens.css by test." ;;
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
