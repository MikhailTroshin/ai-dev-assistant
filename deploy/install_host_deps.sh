#!/usr/bin/env bash
# ============================================================
# install_host_deps.sh — установка хостовых зависимостей
# AI Dev Assistant (worker + Claude Code + MCP-серверы).
#
# Скрипт идемпотентен: повторный запуск ничего не ломает,
# недостающие компоненты доустанавливает, существующие пропускает.
#
# Устанавливает (в ~/, без sudo):
#   1. Node.js (standalone, ~/.local/opt/node + симлинки в ~/.local/bin)
#      — нужен для MCP-сервера gitlab (@zereight/mcp-gitlab, запуск через npx)
#   2. uv ( Astral, ~/.local/bin/uvx) — нужен для MCP-сервера jira
#      (mcp-atlassian через uvx)
#   3. Claude Code CLI (~/.local/bin/claude)
#   4. Регистрирует MCP-серверы jira/gitlab в ~/.claude.json (user scope)
#      ВАЖНО: в Claude Code >= 2.1 mcpServers из ~/.claude/settings.json
#      ИГНОРИРУЕТСЯ — только ~/.claude.json / `claude mcp add`.
#   5. Добавляет mcp__gitlab / mcp__jira в permissions.allow
#      (без этого в headless-режиме dontAsk инструменты отклоняются)
#
# Креды MCP берутся из переменных окружения (JIRA_URL, JIRA_API_TOKEN,
# GITLAB_API_URL, GITLAB_PERSONAL_ACCESS_TOKEN) либо вводятся интерактивно.
# Секреты можно передать так:
#   JIRA_API_TOKEN=xxx GITLAB_PERSONAL_ACCESS_TOKEN=yyy ./deploy/install_host_deps.sh
# или отредактировать ~/.claude.json после установки.
# ============================================================
set -euo pipefail

NODE_VERSION="${NODE_VERSION:-22.14.0}"
LOCAL_BIN="$HOME/.local/bin"
LOCAL_OPT="$HOME/.local/opt"
CLAUDE_JSON="$HOME/.claude.json"
CLAUDE_SETTINGS="$HOME/.claude/settings.json"

log()  { printf '\033[1;32m[install]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }

# ---------- 1. Node.js ----------
install_node() {
    if { command -v node >/dev/null 2>&1 && command -v npx >/dev/null 2>&1; } \
        || [ -x "${LOCAL_BIN}/node" ] && [ -x "${LOCAL_BIN}/npx" ]; then
        log "Node.js уже установлен ($("${LOCAL_BIN}/node" --version 2>/dev/null || node --version)) — пропускаю"
        return
    fi
    log "Устанавливаю Node.js v${NODE_VERSION} в ${LOCAL_OPT}/node..."
    local arch
    arch=$(uname -m)
    case "$arch" in
        x86_64)  arch="x64" ;;
        aarch64) arch="arm64" ;;
        *) warn "Неизвестная архитектура: $arch"; return 1 ;;
    esac
    local tmp
    tmp=$(mktemp -d)
    curl -fsSL -o "$tmp/node.tar.xz" \
        "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${arch}.tar.xz"
    mkdir -p "$LOCAL_OPT"
    rm -rf "${LOCAL_OPT}/node"
    tar -xJf "$tmp/node.tar.xz" -C "$LOCAL_OPT"
    mv "${LOCAL_OPT}/node-v${NODE_VERSION}-linux-${arch}" "${LOCAL_OPT}/node"
    mkdir -p "$LOCAL_BIN"
    ln -sf "${LOCAL_OPT}/node/bin/node" "${LOCAL_BIN}/node"
    ln -sf "${LOCAL_OPT}/node/bin/npx"   "${LOCAL_BIN}/npx"
    ln -sf "${LOCAL_OPT}/node/bin/npm"   "${LOCAL_BIN}/npm"
    rm -rf "$tmp"
    log "Node.js установлен: $("${LOCAL_BIN}/node" --version)"
}

# ---------- 2. uv (uvx) ----------
install_uv() {
    if command -v uvx >/dev/null 2>&1 || [ -x "${LOCAL_BIN}/uvx" ]; then
        log "uv уже установлен ($("${LOCAL_BIN}/uvx" --version 2>/dev/null | head -1)) — пропускаю"
        return
    fi
    log "Устанавливаю uv (для MCP jira через uvx)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # инсталлер кладёт в ~/.local/bin
    [ -x "${LOCAL_BIN}/uvx" ] || warn "uvx не найден в ${LOCAL_BIN} после установки"
}

# ---------- 3. Claude Code ----------
install_claude() {
    if command -v claude >/dev/null 2>&1 || [ -x "${LOCAL_BIN}/claude" ]; then
        log "Claude Code CLI уже установлен — пропускаю"
        return
    fi
    log "Устанавливаю Claude Code CLI..."
    curl -fsSL https://claude.ai/install.sh | bash
    command -v claude >/dev/null 2>&1 || [ -x "${LOCAL_BIN}/claude" ] \
        || warn "claude не найден после установки — проверь PATH вручную"
}

# ---------- helpers для JSON ----------
json_set_mcp() {  # json_set_mcp <name> <json-объект-сервера>
    python3 - "$CLAUDE_JSON" "$1" "$2" <<'PYEOF'
import json, sys, os
path, name, server_json = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path) as f:
    d = json.load(f)
d.setdefault('mcpServers', {})
d['mcpServers'][name] = json.loads(server_json)
with open(path, 'w') as f:
    json.dump(d, f, indent=2, ensure_ascii=False)
PYEOF
}

allow_mcp_permission() {  # allow_mcp_permission <mcp__name>
    python3 - "$CLAUDE_SETTINGS" "$1" <<'PYEOF'
import json, sys, os
path, rule = sys.argv[1], sys.argv[2]
d = {}
if os.path.exists(path):
    with open(path) as f:
        d = json.load(f)
allow = d.setdefault('permissions', {}).setdefault('allow', [])
if rule not in allow:
    allow.append(rule)
with open(path, 'w') as f:
    json.dump(d, f, indent=2, ensure_ascii=False)
PYEOF
}

# ---------- 4. MCP-серверы ----------
ask_secret() {  # ask_secret <var_name> <prompt> <is_optional>
    local var="$1" prompt="$2" optional="${3:-}"
    local val="${!var:-}"
    if [ -z "$val" ]; then
        if [ "$optional" = "optional" ]; then
            read -r -p "$prompt (Enter — пропустить): " val || val=""
        else
            read -r -p "$prompt: " val
        fi
    fi
    printf '%s' "$val"
}

configure_mcp() {
    log "Настройка MCP-серверов в ${CLAUDE_JSON}..."

    # Jira
    local jira_url jira_user jira_token
    jira_url=$(ask_secret JIRA_URL "Jira URL (например, https://your-jira.atlassian.net)")
    jira_user=$(ask_secret JIRA_USERNAME "Jira username (email)")
    jira_token=$(ask_secret JIRA_API_TOKEN "Jira API token")
    if [ -n "$jira_url" ] && [ -n "$jira_user" ] && [ -n "$jira_token" ]; then
        [ -f "$CLAUDE_JSON" ] || echo '{}' > "$CLAUDE_JSON"
        json_set_mcp jira "$(python3 -c "
import json, sys
print(json.dumps({
    'command': 'uvx',
    'args': ['mcp-atlassian==0.21.0'],
    'env': {
        'JIRA_URL': sys.argv[1],
        'JIRA_USERNAME': sys.argv[2],
        'JIRA_API_TOKEN': sys.argv[3],
    },
}) )" "$jira_url" "$jira_user" "$jira_token")"
        allow_mcp_permission mcp__jira
        log "MCP jira настроен"
    else
        warn "Jira-креды не заданы — MCP jira пропущен"
    fi

    # GitLab
    local gl_url gl_token
    gl_url=$(ask_secret GITLAB_API_URL "GitLab API URL (например, https://gitlab.yourcompany.com/api/v4)")
    gl_token=$(ask_secret GITLAB_PERSONAL_ACCESS_TOKEN "GitLab personal access token")
    if [ -n "$gl_url" ] && [ -n "$gl_token" ]; then
        [ -f "$CLAUDE_JSON" ] || echo '{}' > "$CLAUDE_JSON"
        json_set_mcp gitlab "$(python3 -c "
import json, sys
print(json.dumps({
    'command': 'npx',
    'args': ['-y', '@zereight/mcp-gitlab@latest'],
    'env': {
        'GITLAB_PERSONAL_ACCESS_TOKEN': sys.argv[1],
        'GITLAB_API_URL': sys.argv[2],
    },
}) )" "$gl_token" "$gl_url")"
        allow_mcp_permission mcp__gitlab
        log "MCP gitlab настроен"
    else
        warn "GitLab-креды не заданы — MCP gitlab пропущен"
    fi

    chmod 600 "$CLAUDE_JSON"
}

# ---------- main ----------
main() {
    mkdir -p "$HOME/.claude" "$LOCAL_BIN"

    install_node
    install_uv
    install_claude
    configure_mcp

    log ""
    log "Готово! Проверка:"
    log "  1. PATH должен содержать ~/.local/bin (для claude/node/uvx)."
    log "     Для systemd-worker это уже учтено в ai-assistant-worker.service."
    log "  2. Проверь MCP:            claude mcp list"
    log "     Оба сервера должны быть '✔ Connected'."
    log "  3. Проверь модели API в    ~/.claude/settings.json (env: ANTHROPIC_*)"
    log "     (см. README, раздел «Конфигурация Claude Code»)."
}

main "$@"
