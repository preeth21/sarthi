# sArthI

**Self-healing Autonomous Runtime Troubleshooting & Health Intelligence**

sArthI is an AI-powered ops assistant for Walmart engineers, built as a plugin for [Wibey CLI](https://wibey.walmart.com/cli). It connects to your entire stack — orchestrators, cloud, Kubernetes, ServiceNow, messaging, and more — and lets you monitor, investigate, and fix issues in plain English.

## Quick Start (macOS)

```bash
git clone https://gecgithub01.walmart.com/WITDnA/sarthi.git ~/sarthi && bash ~/sarthi/install.sh
```

Then open Wibey and type `/custom/sarthi`.

## Full Installation Guide

See [FIRST_RUN.md](./FIRST_RUN.md) for step-by-step instructions including auth setup.

## What sArthI can do

- **Orchestrator Monitoring** — check workflow health, drill into failures, read execution logs
- **Predictive Health Monitoring** — surfaces warning signs from environment logs before issues occur
- **Autonomous Incident Resolution** — clears failed tasks, triggers reruns, restarts services
- **GCP, Azure & Beyond** — BigQuery, GCS, Dataproc, Azure, CosmosDB, Redis
- **Kubernetes / WCNP** — pods, logs, deployments, rollouts across 30+ clusters
- **ServiceNow** — CRQs, incidents, RITM approvals, AD group access requests
- **Inbox, Teams & Slack** — read/reply to Outlook, Teams, and Slack
- **Cost Intelligence** — surface anomalies and optimisation recommendations
- **Git & Code** — search repos, list PRs, create pull requests on GEC GitHub

## Repository Structure

```
sarthi/
├── install.sh                  ← one-liner installer
├── setup.sh                    ← full setup (deps, symlinks, MCP injection, auth)
├── FIRST_RUN.md                ← installation guide
├── index.html                  ← project landing page
├── mcp/                        ← 12 sarthi MCP servers
├── skills/                     ← 24 sar-* skills
├── commands/                   ← Wibey custom commands (/custom/sarthi etc.)
├── agents/                     ← sArthI agent definition
├── scripts/                    ← auth, headless refresh, snow-ad-automation
└── knowledge/                  ← team config, environments, channels
```

## Team

Built by [WITDnA](https://gecgithub01.walmart.com/WITDnA) · Walmart International Data & Analytics
