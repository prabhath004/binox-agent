# Cursor — AI Code Editor

## Overview
Cursor is an AI-powered code editor built as a fork of VS Code. Founded in 2022 by Anysphere, it integrates large language models directly into the coding workflow. The editor offers autocomplete, inline editing, chat-based coding assistance, and codebase-aware context.

## Product
- AI autocomplete with multi-line suggestions (Tab)
- Inline editing via natural language instructions (Cmd+K)
- Chat panel with full codebase context (@-mentions for files, docs, web)
- Agent mode for multi-step autonomous coding tasks
- Built-in terminal, debugger, and extension support (VS Code compatible)

## Pricing
- Free: 2,000 completions/month, 50 slow premium requests
- Pro: $20/month — 500 fast premium requests, unlimited completions
- Business: $40/user/month — admin dashboard, enforced privacy, SSO

## Differentiation
- Deep IDE integration — not a plugin but a full editor
- Codebase indexing for context-aware suggestions
- Privacy mode: code never stored on servers when enabled
- Supports multiple LLM backends (GPT-4, Claude, custom)
- Agent mode can autonomously create files, run commands, fix errors

## Risks
- Dependency on upstream VS Code updates
- Competing with GitHub Copilot's distribution advantage
- Model provider lock-in risk if OpenAI/Anthropic change terms
- Retention challenge: developers are habitual about their editors
