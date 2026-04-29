<p align="center">
  <img src="https://img.shields.io/badge/Version-2.0-blueviolet?style=for-the-badge" alt="Version"/>
  <img src="https://img.shields.io/badge/Python-3.10+-9b59b6?style=for-the-badge&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/Platform-Windows-8e44ad?style=for-the-badge" alt="Platform"/>
  <img src="https://img.shields.io/badge/License-MIT-a855f7?style=for-the-badge" alt="License"/>
</p>

<h1 align="center">⚡ Token Gen</h1>
<p align="center"><b>Discord Account Generator + Token Checker
<p align="center"><i>Made by SoliderX</i></p>

---

```
▄▄▄█████▓ ▒█████   ██ ▄█▀▓█████  ███▄    █      ▄████ ▓█████  ███▄    █
▓  ██▒ ▓▒▒██▒  ██▒ ██▄█▒ ▓█   ▀  ██ ▀█   █     ██▒ ▀█▒▓█   ▀  ██ ▀█   █
▒ ▓██░ ▒░▒██░  ██▒▓███▄░ ▒███   ▓██  ▀█ ██▒   ▒██░▄▄▄░▒███   ▓██  ▀█ ██▒
░ ▓██▓ ░ ▒██   ██░▓██ █▄ ▒▓█  ▄ ▓██▒  ▐▌██▒   ░▓█  ██▓▒▓█  ▄ ▓██▒  ▐▌██▒
  ▒██▒ ░ ░ ████▓▒░▒██▒ █▄░▒████▒▒██░   ▓██░   ░▒▓███▀▒░▒████▒▒██░   ▓██░
  ▒ ░░   ░ ▒░▒░▒░ ▒ ▒▒ ▓▒░░ ▒░ ░░ ▒░   ▒ ▒     ░▒   ▒ ░░ ▒░ ░░ ▒░   ▒ ▒
    ░      ░ ▒ ▒░ ░ ░▒ ▒░ ░ ░  ░░ ░░   ░ ▒░     ░   ░  ░ ░  ░░ ░░   ░ ▒░
  ░      ░ ░ ░ ▒  ░ ░░ ░    ░      ░   ░ ░    ░ ░   ░    ░      ░   ░ ░
             ░ ░  ░  ░      ░  ░         ░          ░    ░  ░         ░
```

---

## 🚀 Features

### [1] Token Generator
| Category | Details |
|---|---|
| **Account Generation** | Fully automated Discord account creation via browser + CDP |
| **Email Verification** | Auto-verify via MS Graph (Hotmail pool), Hotmail007 API, or CyberTemp API |
| **Captcha Solving** | Browser-integrated automated captcha solver |
| **Proxy Support** | HTTP proxy rotation from `input/proxies.txt` |
| **Stealth** | TLS fingerprint spoofing via `tls_client`, headless Brave with off-screen

### [2] Token Checker
| Category | Details |
|---|---|
| **Input** | Reads tokens from `output/valid.txt` (generator output) |
| **Multi-threaded** | Configurable thread count at runtime |
| **Token Type** | Detects `unclaimed`, `email verified`, `phone verified`, `fully verified` |
| **Account Age** | Calculates account age in months/years, sorted into subfolders |
| **Nitro Detection** | Detects active Nitro subscriptions + available boost slots |
| **Flagged Detection** | Flags spammer-flagged accounts |
| **Proxy Support** | Reads from `input/proxies.txt` — auto falls back to proxyless on 407 |
| **Output** | Results saved to `output/checker output/{YYYY-MM-DD HH-MM-SS}/` |

---

## 📦 Installation

```bash
# Clone the repository
git clone https://github.com/AbdurRehman1098/Discord-Token-Generator.git
cd Discord-Token-Generator

# Install dependencies
pip install -r requirements.txt

# Run the tool
python main.py
```

### Prerequisites

- **Python 3.10+**
- **Brave Browser** installed (required for Token Generator only)

---

## 🖥️ Usage

Run `python main.py` and select a tool:

```
  [1]  Token Generator
  [2]  Token Checker

  ▸ Select option :
```

**Token Generator** — prompts for threads and account count, then starts generating.

**Token Checker** — prompts for threads, reads `output/valid.txt`, checks each token against the Discord API and saves categorised results to `output/checker output/{timestamp}/`.

---

## ⚙️ Configuration

### Token Generator — `input/config.json`

```json
{
    "Threads": 2,
    "email_api": {
        "hotmail_pool": {
            "enabled": true,
            "file": "input/mails.json"
        },
        "hotmail007": {
            "client_key": "",
            "auto_buy": false
        },
        "cybertemp": {
            "enabled": false,
            "api_key": ""
        }
    },
    "proxy": {
        "enabled": false,
        "file": "input/proxies.txt"
    }
}
```

| Setting | Description |
|---|---|
| `hotmail_pool` | Use pre-loaded Hotmail accounts from `mails.json` |
| `hotmail007` | Hotmail007 API — set `client_key` to enable |
| `cybertemp` | CyberTemp temporary emails — set `api_key` to enable |
| `proxy.enabled` | Enable proxy rotation for the generator |

### Token Checker — `input/proxies.txt`

One proxy per line. Supported formats:

```
host:port
host:port:username:password
```

---

## 📁 File Structure

```
Token-Gen/
├── main.py                        # Main application (Generator + Checker)
├── requirements.txt               # Python dependencies
├── input/
│   ├── config.json                # Generator configuration
│   ├── mails.json                 # Hotmail pool accounts
│   ├── hotmails.txt               # Hotmail credentials
│   └── proxies.txt                # Proxy list (used by both tools)
├── output/
│   ├── valid.txt                  # Generated tokens (checker input)
│   ├── invalid.txt                # Invalid tokens
│   ├── locked.txt                 # Locked tokens
│   └── checker output/
│       └── YYYY-MM-DD HH-MM-SS/   # Per-run checker results
│           ├── email verified.txt
│           ├── fully verified.txt
│           ├── unclaimed.txt
│           ├── invalid.txt
│           ├── locked.txt
│           ├── flagged.txt
│           ├── age/               # Sorted by account age
│           └── boosts/            # Sorted by Nitro boost days
└── README.md
```

---

## 📞 Support

**Discord Server:** https://discord.gg/uJraw4WXqd

Join for free support and upcoming updates.

---

## 💻 Tested On

| OS | Status |
|---|---|
| Windows 10/11 | ✅ |

---

## ⚠️ Disclaimer

> **This tool is provided for educational and research purposes only.**

By using this tool you acknowledge that:

- You are **solely responsible** for how you use it
- You will comply with all applicable laws and regulations
- You will respect Discord's Terms of Service
- The developer assumes **no liability** for any misuse, damages, or legal consequences
- Accounts created may be flagged, limited, or banned by Discord

**Do not use this tool for spam, harassment, fraud, selling accounts, or any malicious purpose.**

If you do not agree with these terms, do not use this tool.

---

## 📜 License

This project is licensed under the [MIT License](LICENSE).

---

<p align="center"><b>Made by SoliderX</b></p>
