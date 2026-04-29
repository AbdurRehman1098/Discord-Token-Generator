<p align="center">
  <img src="https://img.shields.io/badge/Version-1.0-blueviolet?style=for-the-badge" alt="Version"/>
  <img src="https://img.shields.io/badge/Python-3.10+-9b59b6?style=for-the-badge&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-8e44ad?style=for-the-badge" alt="Platform"/>
  <img src="https://img.shields.io/badge/License-MIT-a855f7?style=for-the-badge" alt="License"/>
</p>

<h1 align="center">⚡ Token Gen</h1>
<p align="center"><b>Advanced Discord Account Generator with Auto Email Verification</b></p>
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

| Category | Details |
|---|---|
| **Account Generation** | Fully automated Discord account creation via Brave browser + CDP |
| **Email Verification** | Auto-verify via MS Graph (Hotmail pool), Hotmail007 API, or CyberTemp API |
| **Captcha Solving** | Automated Captcha solver | Browser integrated |
| **Proxy Support** | HTTP/SOCKS proxy rotation from `proxies.txt` |
| **Stealth** | TLS fingerprint spoofing via `tls_client`, headless Brave with off-screen windows |
| **Output** | Tokens saved to `output/valid.txt`, locked/invalid sorted automatically |

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
- **Brave Browser** installed (auto-detected on Windows/macOS/Linux)

---

## ⚙️ Configuration

Edit `input/config.json`:

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
| `proxy.enabled` | Enable proxy rotation |
| `proxy.file` | Path to proxy list (one per line, `ip:port` or `user:pass@ip:port`) |

---

## 📁 File Structure

```
Token-Gen/
├── main.py              # Main application
├── requirements.txt     # Python dependencies
├── input/
│   ├── config.json      # Tool configuration
│   ├── mails.json       # Hotmail pool accounts
│   ├── hotmails.txt     # Hotmail credentials
│   └── proxies.txt      # Proxy list
├── output/
│   ├── valid.txt        # Successfully generated tokens
│   ├── invalid.txt      # Failed/invalid tokens
│   └── locked.txt       # Locked tokens
└── README.md
```
📞 SUPPORT
---
Discord Server: https://discord.gg/uJraw4WXqd

Join for: Free Support and upcoming Updates 

## 💻 Tested On

| OS | Status |
|---|---|
| Windows 10/11 | ✅ |
| Ubuntu / Debian | ✅ |
| macOS | ✅ |

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
