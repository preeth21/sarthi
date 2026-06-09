# ServiceNow AD Group Request Automation

> **Automate Active Directory group membership requests via the Walmart ServiceNow portal using Python + Selenium.**

This tool eliminates the manual, repetitive process of navigating the ServiceNow portal to raise AD group access requests. It handles single users, multiple users, single groups, and batch groups — all from the command line.

---

## Table of Contents

- [Overview](#overview)
- [Script Variants](#script-variants)
- [Prerequisites](#prerequisites)
- [Installation & Setup](#installation--setup)
  - [Mac / Linux](#mac--linux)
  - [Windows](#windows)
- [Configuration](#configuration)
- [Usage](#usage)
  - [Single Group, Single User](#single-group-single-user)
  - [Single Group, Multiple Users](#single-group-multiple-users)
  - [Multiple Groups, Multiple Users (Batch)](#multiple-groups-multiple-users-batch)
  - [Dry Run (Test Without Submitting)](#dry-run-test-without-submitting)
- [Command-Line Reference](#command-line-reference)
- [How It Works](#how-it-works)
- [SSO Authentication](#sso-authentication)
- [Troubleshooting](#troubleshooting)
- [Project Structure](#project-structure)
- [Contributing](#contributing)
- [Important Notes & Limitations](#important-notes--limitations)

---

## Overview

This automation suite interacts with the **Walmart ServiceNow portal** (`walmartglobal.service-now.com`) to submit AD group membership requests on your behalf. It:

1. Launches a Chrome browser window
2. Navigates to the ServiceNow AD request form
3. Pauses for **manual Walmart SSO login** (required — cannot be automated)
4. Fills all form fields (group names, usernames, justification)
5. Submits the request and captures the confirmation

**Key use cases:**
- Onboarding a team of users to multiple AD groups at once
- Automating repetitive access requests during sprint planning
- Batch-processing access for new joiners

---

## Script Variants

| Script | Use Case | Groups | Users per Request |
|--------|----------|--------|-------------------|
| `ad_group_request.py` | Basic: single group, one user at a time | 1 | 1 |
| `ad_group_request_multi_user.py` | Add multiple users to one group in a single request | 1 | Multiple |
| `ad_group_batch.py` | Batch: one request per group, multiple users each | Multiple | Multiple |
| `ad_group_batch_wip.py` | Work-in-progress batch variant (for development/testing) | Multiple | Multiple |

**Which script should I use?**
- Need to add **one person** to **one group** → `ad_group_request.py`
- Need to add **multiple people** to **one group** → `ad_group_request_multi_user.py`
- Need to add people to **many groups at once** → `ad_group_batch.py`

The `run.sh` / `run.bat` wrapper defaults to `ad_group_request.py`. See [Configuration](#configuration) to change this.

---

## Prerequisites

Before you begin, ensure you have:

| Requirement | Version | Check Command |
|-------------|---------|---------------|
| Python | 3.8+ | `python3 --version` |
| Google Chrome | Latest stable | Open Chrome → `chrome://version` |
| pip | Bundled with Python | `pip --version` |
| Git | Any recent | `git --version` |
| Walmart network / VPN | Required for SSO | — |

> **ChromeDriver** is automatically downloaded and managed by `webdriver-manager` — you do **not** need to install it manually.

---

## Installation & Setup

### Mac / Linux

```bash
# 1. Clone the repository
git clone https://github.com/<your-org>/servicenow-ad-automation.git
cd servicenow-ad-automation

# 2. Copy the example config and fill in your defaults
cp config.example.yaml config.yaml
# Edit config.yaml with your preferred editor

# 3. Run one-time setup (creates .venv and installs dependencies)
chmod +x setup.sh run.sh
./setup.sh

# 4. Verify setup
./run.sh --help
```

### Windows

```cmd
REM 1. Clone the repository
git clone https://github.com/<your-org>/servicenow-ad-automation.git
cd servicenow-ad-automation

REM 2. Copy the example config and fill in your defaults
copy config.example.yaml config.yaml
REM Edit config.yaml with Notepad or VS Code

REM 3. Run one-time setup
setup.bat

REM 4. Verify setup
run.bat --help
```

> **Note:** If you see a "permission denied" error on Mac/Linux, run `chmod +x setup.sh run.sh` first.

---

## Configuration

Copy `config.example.yaml` to `config.yaml` (this file is git-ignored and stays local):

```bash
cp config.example.yaml config.yaml
```

Edit `config.yaml` to set your personal defaults:

```yaml
# config.yaml — your personal settings (git-ignored, never committed)

defaults:
  justification: "Access required for team project work"  # Default justification text
  timeout: 30              # Element wait timeout in seconds
  sso_timeout: 120         # Seconds to wait for manual SSO login

script:
  # Which script to run via run.sh / run.bat
  # Options: ad_group_request | ad_group_request_multi_user | ad_group_batch
  variant: ad_group_request

chrome:
  headless: false          # Always false recommended (SSO requires visible browser)
  window_width: 1920
  window_height: 1080
```

> CLI flags always override `config.yaml` values when both are provided.

---

## Usage

### Single Group, Single User

```bash
./run.sh \
  --groups "MY-AD-GROUP" \
  --users "jsmith" \
  --justification "Need access for Project Alpha"
```

### Single Group, Multiple Users

Use `ad_group_request_multi_user.py` directly:

```bash
source .venv/bin/activate

python ad_group_request_multi_user.py \
  --groups "MY-AD-GROUP" \
  --users "jsmith,mjones,bwilliams" \
  --justification "Q1 onboarding — new team members need read access"
```

### Multiple Groups, Multiple Users (Batch)

Use `ad_group_batch.py` — submits **one request per group**:

```bash
source .venv/bin/activate

python ad_group_batch.py \
  --groups "GROUP-READ,GROUP-WRITE,GROUP-ADMIN" \
  --users "jsmith,mjones" \
  --justification "Team onboarding for Platform Engineering squad"
```

### Dry Run (Test Without Submitting)

Test the navigation flow without actually submitting any requests:

```bash
./run.sh \
  --groups "MY-AD-GROUP" \
  --users "jsmith" \
  --justification "Testing navigation" \
  --dry-run
```

---

## Command-Line Reference

| Flag | Short | Required | Default | Description |
|------|-------|----------|---------|-------------|
| `--groups` | `-g` | ✅ Yes | — | Comma-separated AD group name(s) |
| `--users` | `-u` | ✅ Yes | — | Comma-separated username(s) to add |
| `--justification` | `-j` | ✅ Yes | — | Business justification text |
| `--headless` | — | No | `false` | Run Chrome without a visible window (not recommended — breaks SSO) |
| `--dry-run` | — | No | `false` | Navigate form but **do not submit** |
| `--timeout` | — | No | `30` | Seconds to wait for page elements |

**Examples:**

```bash
# Minimal
./run.sh -g "TEAM-DEVOPS" -u "jsmith" -j "DevOps team access"

# Batch with timeout
./run.sh -g "GROUP1,GROUP2" -u "user1,user2,user3" -j "Sprint onboarding" --timeout 60

# Just testing
./run.sh -g "TEST-GROUP" -u "testuser" -j "Verification run" --dry-run
```

---

## How It Works

```
┌─────────────┐     ┌──────────────────┐     ┌────────────────────┐
│  CLI Input  │────▶│ Chrome WebDriver │────▶│ ServiceNow Portal  │
│ (groups,    │     │ (Selenium 4.x)   │     │ (walmartglobal.    │
│  users,     │     │                  │     │  service-now.com)  │
│  justif.)   │     └──────────────────┘     └────────────────────┘
└─────────────┘              │
                             │  1. Open browser
                             │  2. ⏸ Wait for manual SSO login
                             │  3. Navigate: Active Directory form
                             │  4. Select: Environment → Production
                             │  5. Select: Type → Group
                             │  6. Select: Action → Modify existing group
                             │  7. Select: Modification → Group Membership
                             │  8. Fill: Group name(s) from dropdown
                             │  9. Fill: Username(s) from dropdown
                             │ 10. Fill: Business justification
                             │ 11. Submit → capture confirmation
                             ▼
                    ✅ Request submitted (RITM number logged)
```

The scripts use:
- **Selenium 4.x** for browser automation
- **webdriver-manager** for automatic ChromeDriver version management
- **AngularJS/Select2 aware** interactions — direct JS injection to handle the dynamic dropdowns used in the ServiceNow portal
- **Multi-layer fallback strategy** — each element interaction has 2–3 fallback approaches to handle UI variations

---

## SSO Authentication

⚠️ **Manual action required every run.**

The Walmart ServiceNow portal requires Single Sign-On (SSO) via Walmart's identity provider. This **cannot be automated** due to MFA and corporate security policies.

**What happens:**
1. Chrome opens and navigates to `https://walmartglobal.service-now.com/wm_sp`
2. The script **pauses** (default: 120 seconds) and prints:
   ```
   ⏳ Please complete SSO login in the browser window...
   You have 120 seconds.
   ```
3. You complete your Walmart login (username → password → MFA if prompted)
4. Once logged in, the script auto-detects the authenticated state and continues

**Tips:**
- Keep the Chrome window visible and in focus
- Complete login within the timeout window (default 120s, configurable)
- If your MFA takes longer, increase `sso_timeout` in `config.yaml`

---

## Troubleshooting

### `ChromeDriver` version mismatch

```bash
# The script auto-manages ChromeDriver via webdriver-manager.
# If you see version mismatch errors, force a refresh:
rm -rf ~/.wdm/
./run.sh --groups "TEST" --users "test" --justification "test" --dry-run
```

### `Element not found` / `TimeoutException`

- ServiceNow UI may have updated its selectors
- Run with `--dry-run` to see exactly where navigation fails
- An error screenshot is saved to `/tmp/servicenow_error.png` — inspect it to see the page state

```bash
# Check the screenshot after a failed run
open /tmp/servicenow_error.png        # Mac
xdg-open /tmp/servicenow_error.png   # Linux
start /tmp/servicenow_error.png      # Windows
```

### SSO timeout expired

```bash
# Increase the timeout via CLI (override config)
python ad_group_request.py -g "GROUP" -u "user" -j "reason" --timeout 180
```

Or set a higher default in `config.yaml`:
```yaml
defaults:
  sso_timeout: 180
```

### `Permission denied` on setup.sh / run.sh (Mac/Linux)

```bash
chmod +x setup.sh run.sh
```

### `pip install` fails behind Walmart proxy

```bash
# Install with Walmart's trusted hosts
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt
```

### Virtual environment not activating (Windows)

```cmd
REM If PowerShell blocks activation, use cmd.exe instead:
cmd /k ".venv\Scripts\activate.bat"

REM Or allow scripts temporarily in PowerShell:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

## Project Structure

```
servicenow-ad-automation/
│
├── 📄 README.md                         ← You are here
├── 📄 requirements.txt                  ← Python dependencies (pip)
├── 📄 config.example.yaml               ← Config template (copy → config.yaml)
├── 📄 .gitignore                        ← Git exclusions
│
├── 🐍 ad_group_request.py               ← Single group, single/one user per request
├── 🐍 ad_group_request_multi_user.py    ← Single group, multiple users
├── 🐍 ad_group_batch.py                 ← Multiple groups (one request per group)
├── 🐍 ad_group_batch_wip.py             ← WIP / development variant
│
├── 🔧 setup.sh                          ← Mac/Linux: create venv + install deps
├── 🔧 setup.bat                         ← Windows: create venv + install deps
├── ▶️  run.sh                            ← Mac/Linux: activate venv + run script
├── ▶️  run.bat                           ← Windows: activate venv + run script
│
└── 🚫 (git-ignored)
    ├── .venv/                           ← Python virtual environment
    ├── config.yaml                      ← Your personal config (copy from example)
    ├── .servicenow_cookies.pkl          ← Session cookies (auth tokens)
    ├── chrome_profile/                  ← Chrome user data
    ├── html_page_*.txt                  ← Debug HTML captures
    └── bkp/                             ← Local backup copies
```

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-enhancement`
3. Make your changes to the relevant script
4. Test with `--dry-run` before submitting
5. Open a Pull Request with a description of what changed and why

**Do not commit:**
- `config.yaml` (contains personal values)
- `.servicenow_cookies.pkl` (contains auth tokens)
- `chrome_profile/` (contains browser user data)
- `.venv/` (generated locally by setup)

---

## Important Notes & Limitations

| Topic | Details |
|-------|---------|
| **SSO Required** | Manual Walmart login is needed every run (no headless bypass) |
| **Internal Network** | Must be on Walmart network or VPN to reach ServiceNow |
| **UI Fragility** | ServiceNow portal updates may break selectors — test with `--dry-run` first |
| **Headless Mode** | Not recommended — SSO and certain dropdowns require visible browser |
| **No MFA Bypass** | MFA prompts during SSO must be completed manually |
| **Rate Limiting** | Avoid running batch operations too rapidly to prevent ServiceNow throttling |
| **Credentials** | Never hardcode credentials anywhere — SSO handles authentication |

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `selenium` | `>=4.15.0` | Browser automation via WebDriver |
| `webdriver-manager` | `>=4.0.0` | Auto-download/manage ChromeDriver binaries |

Install via:
```bash
pip install -r requirements.txt
```

---

*Built for Walmart internal use. Requires access to `walmartglobal.service-now.com`.*
