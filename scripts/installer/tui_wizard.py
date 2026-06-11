#!/usr/bin/env python3
"""NexusPanel terminal installer — multi-step TUI wizard (works via curl | bash)."""
from __future__ import annotations

import argparse
import curses
import json
import os
import secrets
import string
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# i18n (installer UI language — separate from panel_default_lang)
# ---------------------------------------------------------------------------
LANGS = [
    ("en", "English", "ltr"),
    ("fa", "فارسی", "rtl"),
    ("ru", "Русский", "ltr"),
    ("zh", "中文", "ltr"),
]

PANEL_LANGS = LANGS

T = {
    "en": {
        "title": "NexusPanel Installer",
        "tagline": "Professional VPN Control Plane",
        "steps": ["Welcome", "Language", "Network", "Admin", "Branding", "Advanced", "Review"],
        "welcome_h": "Welcome to NexusPanel",
        "welcome_b": "Production-ready install: Docker, PostgreSQL, Redis, HTTPS, secret dashboard path.",
        "feat": ["One-click stack", "Auto TLS (Let's Encrypt)", "White-label resellers", "Xray: VLESS, VMess, Trojan…"],
        "press_key": "Press Enter to continue  ·  Esc to quit",
        "lang_h": "Panel language",
        "lang_b": "Default language for the admin dashboard.",
        "net_h": "Network & HTTPS",
        "net_b": "Domain for TLS cert, or leave empty for IP certificate.",
        "domain": "Domain (optional)",
        "email": "Let's Encrypt email (optional)",
        "skip_https": "Skip HTTPS (HTTP only — not recommended)",
        "admin_h": "Admin account",
        "admin_b": "Sudo owner credentials — shown once after install.",
        "auto_creds": "Generate random username & password",
        "username": "Username",
        "password": "Password",
        "dash_path": "Secret dashboard path",
        "brand_h": "Branding (optional)",
        "brand_b": "Customize how the panel appears.",
        "panel_title": "Panel title",
        "primary_color": "Primary color (#hex)",
        "support_url": "Support URL",
        "adv_h": "Advanced options",
        "panel_port": "Internal panel port",
        "skip_node": "Skip node-agent image build (faster install)",
        "ufw": "Configure UFW firewall rules",
        "review_h": "Review & install",
        "review_b": "Confirm settings, then start installation.",
        "back": "← Back",
        "next": "Next →",
        "install": "Install now",
        "yes": "Yes",
        "no": "No",
        "auto": "auto-generated",
        "ip_cert": "IP certificate",
        "server": "Server",
        "ram": "RAM",
        "docker": "Docker",
        "cancelled": "Install cancelled.",
    },
    "fa": {
        "title": "نصب NexusPanel",
        "tagline": "کنترل‌پنل حرفه‌ای VPN",
        "steps": ["خوش‌آمد", "زبان", "شبکه", "ادمین", "برند", "پیشرفته", "بررسی"],
        "welcome_h": "به NexusPanel خوش آمدید",
        "welcome_b": "نصب production: Docker، PostgreSQL، Redis، HTTPS، مسیر مخفی داشبورد.",
        "feat": ["نصب یک‌کلیکی", "TLS خودکار (Let's Encrypt)", "وایت‌لیبل", "Xray: VLESS، VMess، Trojan…"],
        "press_key": "Enter ادامه  ·  Esc خروج",
        "lang_h": "زبان پنل",
        "lang_b": "زبان پیش‌فرض داشبورد ادمین.",
        "net_h": "شبکه و HTTPS",
        "net_b": "دامنه برای گواهی TLS، یا خالی برای گواهی IP.",
        "domain": "دامنه (اختیاری)",
        "email": "ایمیل Let's Encrypt (اختیاری)",
        "skip_https": "بدون HTTPS (فقط HTTP — توصیه نمی‌شود)",
        "admin_h": "حساب ادمین",
        "admin_b": "اطلاعات sudo — فقط یک‌بار بعد از نصب نمایش داده می‌شود.",
        "auto_creds": "تولید خودکار نام کاربری و رمز",
        "username": "نام کاربری",
        "password": "رمز عبور",
        "dash_path": "مسیر مخفی داشبورد",
        "brand_h": "برندینگ (اختیاری)",
        "brand_b": "ظاهر پنل را سفارشی کنید.",
        "panel_title": "عنوان پنل",
        "primary_color": "رنگ اصلی (#hex)",
        "support_url": "لینک پشتیبانی",
        "adv_h": "تنظیمات پیشرفته",
        "panel_port": "پورت داخلی پنل",
        "skip_node": "رد کردن build ایمیج node-agent",
        "ufw": "تنظیم فایروال UFW",
        "review_h": "بررسی و نصب",
        "review_b": "تأیید تنظیمات و شروع نصب.",
        "back": "→ قبلی",
        "next": "← بعدی",
        "install": "شروع نصب",
        "yes": "بله",
        "no": "خیر",
        "auto": "تولید خودکار",
        "ip_cert": "گواهی IP",
        "server": "سرور",
        "ram": "رم",
        "docker": "داکر",
        "cancelled": "نصب لغو شد.",
    },
}


def t(key: str, lang: str = "en") -> str:
    return T.get(lang, T["en"]).get(key, T["en"].get(key, key))


def rand_path(n: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "/" + "".join(secrets.choice(alphabet) for _ in range(n)) + "/"


def detect_preflight() -> dict:
    ram_mb = 4096
    swap_mb = 0
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    ram_mb = int(line.split()[1]) // 1024
                elif line.startswith("SwapTotal:"):
                    swap_mb = int(line.split()[1]) // 1024
    except OSError:
        pass
    docker_ok = subprocess.run(["docker", "version"], capture_output=True, timeout=10).returncode == 0
    public_ip = "127.0.0.1"
    try:
        import urllib.request

        public_ip = urllib.request.urlopen("https://api.ipify.org", timeout=6).read().decode().strip()
    except Exception:
        try:
            out = subprocess.check_output(["hostname", "-I"], text=True, stderr=subprocess.DEVNULL)
            parts = out.strip().split()
            public_ip = parts[0] if parts else "127.0.0.1"
        except Exception:
            pass
    return {
        "public_ip": public_ip,
        "ram_mb": ram_mb,
        "docker_installed": docker_ok,
        "recommended_skip_node_build": ram_mb < 3500,
    }


def attach_tty() -> bool:
    """Redirect stdin/stdout to /dev/tty so curl | bash can show TUI."""
    if sys.stdin.isatty():
        return True
    try:
        tty = os.open("/dev/tty", os.O_RDWR)
        os.dup2(tty, 0)
        os.dup2(tty, 1)
        os.dup2(tty, 2)
        os.close(tty)
        return True
    except OSError:
        return False


class Config:
    def __init__(self, preflight: dict) -> None:
        self.installer_ui_lang = "en"
        self.panel_default_lang = "en"
        self.domain = ""
        self.email = ""
        self.skip_https = False
        self.auto_credentials = True
        self.admin_username = ""
        self.admin_password = ""
        self.dashboard_path = rand_path()
        self.panel_title = "NexusPanel"
        self.primary_color = "#5b8cff"
        self.support_url = ""
        self.panel_port = 8000
        self.skip_node_build = preflight.get("recommended_skip_node_build", False)
        self.configure_firewall = True

    def to_json(self) -> dict:
        return {
            "panel_default_lang": self.panel_default_lang,
            "installer_ui_lang": self.installer_ui_lang,
            "domain": self.domain,
            "email": self.email,
            "skip_https": self.skip_https,
            "admin_username": self.admin_username if not self.auto_credentials else "",
            "admin_password": self.admin_password if not self.auto_credentials else "",
            "auto_credentials": self.auto_credentials,
            "dashboard_path": self.dashboard_path,
            "panel_title": self.panel_title,
            "primary_color": self.primary_color,
            "support_url": self.support_url,
            "panel_port": self.panel_port,
            "skip_node_build": self.skip_node_build,
            "configure_firewall": self.configure_firewall,
        }


class Wizard:
    STEP_COUNT = 7

    def __init__(self, stdscr, cfg: Config, preflight: dict) -> None:
        self.s = stdscr
        self.cfg = cfg
        self.preflight = preflight
        self.step = 0
        self.focus = 0
        self.ui_lang = cfg.installer_ui_lang
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)      # accent
        curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_BLUE)  # selected
        curses.init_pair(3, curses.COLOR_GREEN, -1)     # ok
        curses.init_pair(4, curses.COLOR_YELLOW, -1)    # warn
        curses.init_pair(5, curses.COLOR_WHITE, -1)     # normal
        curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_CYAN)  # header
        curses.init_pair(7, curses.COLOR_MAGENTA, -1)   # title
        self.s.keypad(True)
        curses.curs_set(0)

    def _lang(self) -> str:
        return self.ui_lang if self.ui_lang in T else "en"

    def draw_box(self, y: int, x: int, h: int, w: int, title: str = "") -> None:
        s = self.s
        s.attron(curses.color_pair(1))
        s.vline(y, x, curses.ACS_VLINE, h)
        s.vline(y, x + w - 1, curses.ACS_VLINE, h)
        s.hline(y, x, curses.ACS_HLINE, w)
        s.hline(y + h - 1, x, curses.ACS_HLINE, w)
        s.addch(y, x, curses.ACS_ULCORNER)
        s.addch(y, x + w - 1, curses.ACS_URCORNER)
        s.addch(y + h - 1, x, curses.ACS_LLCORNER)
        s.addch(y + h - 1, x + w - 1, curses.ACS_LRCORNER)
        if title:
            s.addstr(y, x + 2, f" {title} ", curses.color_pair(7) | curses.A_BOLD)
        s.attroff(curses.color_pair(1))

    def draw_header(self, max_y: int, max_x: int) -> None:
        s = self.s
        lang = self._lang()
        steps = t("steps", lang)
        step_label = steps[self.step] if self.step < len(steps) else ""
        header = f"  N  {t('title', lang)}"
        sub = t("tagline", lang)
        step_info = f" {self.step + 1}/{self.STEP_COUNT} · {step_label} "
        s.attron(curses.color_pair(6) | curses.A_BOLD)
        s.addstr(0, 0, " " * max_x)
        s.addstr(0, 1, header[: max_x - len(step_info) - 2])
        s.addstr(0, max(1, max_x - len(step_info) - 1), step_info)
        s.attroff(curses.color_pair(6) | curses.A_BOLD)
        s.attron(curses.color_pair(4))
        s.addstr(1, 2, sub[: max_x - 4])
        s.attroff(curses.color_pair(4))

    def draw_steps_bar(self, y: int, max_x: int) -> None:
        lang = self._lang()
        steps = t("steps", lang)
        parts = []
        for i, name in enumerate(steps):
            if i == self.step:
                parts.append(f"● {name}")
            elif i < self.step:
                parts.append(f"✓ {name}")
            else:
                parts.append(f"○ {name}")
        line = "  " + "  ·  ".join(parts)
        self.s.attron(curses.color_pair(1))
        self.s.addstr(y, 0, line[: max_x - 1])
        self.s.attroff(curses.color_pair(1))

    def draw_status_bar(self, y: int, max_x: int) -> None:
        lang = self._lang()
        pf = self.preflight
        docker = t("yes", lang) if pf.get("docker_installed") else t("no", lang)
        info = f" {t('server', lang)}: {pf.get('public_ip', '?')}  |  {t('ram', lang)}: {pf.get('ram_mb', '?')} MB  |  {t('docker', lang)}: {docker} "
        self.s.attron(curses.color_pair(5))
        self.s.addstr(y, 0, info[: max_x - 1])
        self.s.attroff(curses.color_pair(5))

    def draw_footer(self, y: int, max_x: int, show_back: bool = True, next_label: str | None = None) -> None:
        lang = self._lang()
        back = t("back", lang)
        nxt = next_label or t("next", lang)
        self.s.hline(y, 0, curses.ACS_HLINE, max_x)
        if show_back and self.step > 0:
            self.s.addstr(y + 1, 2, f"[B] {back}", curses.color_pair(1))
        self.s.addstr(y + 1, max_x - len(nxt) - 4, f"[Enter] {nxt}", curses.color_pair(3) | curses.A_BOLD)

    def draw_list(self, y: int, x: int, w: int, items: list[str], selected: int) -> None:
        for i, item in enumerate(items):
            if y + i >= curses.LINES - 4:
                break
            if i == selected:
                self.s.attron(curses.color_pair(2) | curses.A_BOLD)
                self.s.addstr(y + i, x, f" › {item}"[: w - 1])
                self.s.attroff(curses.color_pair(2) | curses.A_BOLD)
            else:
                self.s.addstr(y + i, x, f"   {item}"[: w - 1])

    def draw_toggle(self, y: int, x: int, label: str, value: bool, focused: bool) -> None:
        mark = "[✓]" if value else "[ ]"
        attr = curses.A_REVERSE if focused else curses.A_NORMAL
        self.s.attron(attr)
        self.s.addstr(y, x, f" {mark} {label}"[: curses.COLS - x - 1])
        self.s.attroff(attr)

    def prompt_string(self, y: int, x: int, w: int, initial: str) -> str:
        """Inline curses text editor."""
        buf = list(initial)
        pos = len(buf)
        curses.curs_set(1)
        while True:
            display = "".join(buf)[: w - 2]
            self.s.addstr(y, x, display + " " * max(0, w - len(display) - 2), curses.color_pair(2))
            self.s.move(y, x + min(pos, max(0, w - 3)))
            self.s.refresh()
            key = self.s.getch()
            if key in (10, 13, curses.KEY_ENTER, 27):
                break
            if key in (curses.KEY_BACKSPACE, 127, 8):
                if pos > 0:
                    pos -= 1
                    buf.pop(pos)
                continue
            if key == curses.KEY_DC and pos < len(buf):
                buf.pop(pos)
                continue
            if key == curses.KEY_LEFT and pos > 0:
                pos -= 1
                continue
            if key == curses.KEY_RIGHT and pos < len(buf):
                pos += 1
                continue
            if 32 <= key <= 126 and len(buf) < w - 2:
                buf.insert(pos, chr(key))
                pos += 1
        curses.curs_set(0)
        return "".join(buf)

    def draw_field(self, y: int, x: int, w: int, label: str, value: str, focused: bool) -> None:
        self.s.addstr(y, x, f"{label}:", curses.color_pair(1))
        display = value or "(empty)"
        attr = curses.color_pair(2) | curses.A_BOLD if focused else curses.A_NORMAL
        self.s.addstr(y + 1, x + 2, display[: w - 4], attr)

    def run(self) -> bool:
        while True:
            self.s.clear()
            max_y, max_x = self.s.getmaxyx()
            self.draw_header(max_y, max_x)
            self.draw_steps_bar(2, max_x)
            content_y = 4
            handlers = [
                self.step_welcome,
                self.step_language,
                self.step_network,
                self.step_admin,
                self.step_branding,
                self.step_advanced,
                self.step_review,
            ]
            action = handlers[self.step](content_y, max_x)
            if action == "quit":
                return False
            if action == "back":
                self.step = max(0, self.step - 1)
                self.focus = 0
                continue
            if action == "next":
                if self.step < self.STEP_COUNT - 1:
                    self.step += 1
                    self.focus = 0
                else:
                    return True
                continue

    def step_welcome(self, y: int, max_x: int) -> str:
        lang = self._lang()
        self.s.addstr(y + 1, 4, t("welcome_h", lang), curses.color_pair(7) | curses.A_BOLD)
        self.s.addstr(y + 3, 4, t("welcome_b", lang)[: max_x - 8])
        for i, feat in enumerate(t("feat", lang)):
            self.s.addstr(y + 5 + i, 6, f"▸ {feat}"[: max_x - 8], curses.color_pair(3))
        # UI language picker
        self.s.addstr(y + 10, 4, "Installer UI language / زبان نصب:", curses.color_pair(1))
        labels = [f"{code} — {name}" for code, name, _ in LANGS]
        idx = next((i for i, (c, _, _) in enumerate(LANGS) if c == self.ui_lang), 0)
        self.draw_list(y + 11, 4, max_x - 8, labels, idx)
        self.draw_status_bar(curses.LINES - 5, max_x)
        self.draw_footer(curses.LINES - 3, max_x, show_back=False)
        self.s.addstr(curses.LINES - 2, 4, t("press_key", lang)[: max_x - 8], curses.color_pair(4))
        self.s.refresh()
        key = self.s.getch()
        if key in (27, ord("q")):
            return "quit"
        if key in (curses.KEY_UP, ord("k")) and self.focus == 0:
            i = max(0, idx - 1)
            self.ui_lang = LANGS[i][0]
            self.cfg.installer_ui_lang = self.ui_lang
        elif key in (curses.KEY_DOWN, ord("j")) and self.focus == 0:
            i = min(len(LANGS) - 1, idx + 1)
            self.ui_lang = LANGS[i][0]
            self.cfg.installer_ui_lang = self.ui_lang
        elif key in (10, 13, curses.KEY_ENTER):
            return "next"
        return ""

    def step_language(self, y: int, max_x: int) -> str:
        lang = self._lang()
        self.s.addstr(y, 4, t("lang_h", lang), curses.color_pair(7) | curses.A_BOLD)
        self.s.addstr(y + 2, 4, t("lang_b", lang)[: max_x - 8])
        labels = [f"{name}" for _, name, _ in PANEL_LANGS]
        idx = next((i for i, (c, _, _) in enumerate(PANEL_LANGS) if c == self.cfg.panel_default_lang), 0)
        self.draw_list(y + 4, 4, max_x - 8, labels, idx)
        self.draw_footer(curses.LINES - 3, max_x)
        self.s.refresh()
        key = self.s.getch()
        if key in (27,):
            return "quit"
        if key in (ord("b"), curses.KEY_LEFT):
            return "back"
        if key in (curses.KEY_UP, ord("k")):
            self.cfg.panel_default_lang = PANEL_LANGS[max(0, idx - 1)][0]
        elif key in (curses.KEY_DOWN, ord("j")):
            self.cfg.panel_default_lang = PANEL_LANGS[min(len(PANEL_LANGS) - 1, idx + 1)][0]
        elif key in (10, 13, curses.KEY_ENTER):
            return "next"
        return ""

    def step_network(self, y: int, max_x: int) -> str:
        lang = self._lang()
        c = self.cfg
        self.s.addstr(y, 4, t("net_h", lang), curses.color_pair(7) | curses.A_BOLD)
        self.s.addstr(y + 2, 4, t("net_b", lang)[: max_x - 8])
        fy = y + 4
        self.draw_field(fy, 4, max_x - 8, t("domain", lang), c.domain, self.focus == 0)
        fy += 3
        self.draw_field(fy, 4, max_x - 8, t("email", lang), c.email, self.focus == 1)
        fy += 3
        self.draw_toggle(fy, 4, t("skip_https", lang), c.skip_https, self.focus == 2)
        self.draw_status_bar(curses.LINES - 5, max_x)
        self.draw_footer(curses.LINES - 3, max_x)
        self.s.refresh()
        key = self.s.getch()
        if key == 27:
            return "quit"
        if key in (ord("b"), curses.KEY_LEFT):
            self.focus = 0
            return "back"
        if key in (curses.KEY_UP, ord("k")):
            self.focus = max(0, self.focus - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self.focus = min(2, self.focus + 1)
        elif key == ord(" ") and self.focus == 2:
            c.skip_https = not c.skip_https
        elif key in (10, 13, curses.KEY_ENTER):
            if self.focus == 0:
                c.domain = self.prompt_string(fy - 3 + 1, 6, max_x - 10, c.domain)
            elif self.focus == 1:
                c.email = self.prompt_string(fy - 3 + 1, 6, max_x - 10, c.email)
            elif self.focus == 2:
                return "next"
            else:
                self.focus = min(2, self.focus + 1)
        return ""

    def step_admin(self, y: int, max_x: int) -> str:
        lang = self._lang()
        c = self.cfg
        self.s.addstr(y, 4, t("admin_h", lang), curses.color_pair(7) | curses.A_BOLD)
        self.s.addstr(y + 2, 4, t("admin_b", lang)[: max_x - 8])
        fy = y + 4
        self.draw_toggle(fy, 4, t("auto_creds", lang), c.auto_credentials, self.focus == 0)
        fy += 2
        dash_y = fy
        if not c.auto_credentials:
            self.draw_field(fy, 4, max_x - 8, t("username", lang), c.admin_username, self.focus == 1)
            fy += 3
            pw_disp = "*" * len(c.admin_password) if c.admin_password else ""
            self.draw_field(fy, 4, max_x - 8, t("password", lang), pw_disp, self.focus == 2)
            fy += 3
            dash_y = fy
        dash_focus = 1 if c.auto_credentials else 3
        self.draw_field(dash_y, 4, max_x - 8, t("dash_path", lang), c.dashboard_path, self.focus == dash_focus)
        self.s.addstr(dash_y + 2, 6, "[R] regenerate path", curses.color_pair(4))
        self.draw_status_bar(curses.LINES - 5, max_x)
        self.draw_footer(curses.LINES - 3, max_x)
        self.s.refresh()
        key = self.s.getch()
        if key == 27:
            return "quit"
        if key in (ord("b"), curses.KEY_LEFT):
            self.focus = 0
            return "back"
        if key in (curses.KEY_UP, ord("k")):
            self.focus = max(0, self.focus - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self.focus = min(dash_focus, self.focus + 1)
        elif key == ord(" "):
            if self.focus == 0:
                c.auto_credentials = not c.auto_credentials
        elif key == ord("r"):
            c.dashboard_path = rand_path()
        elif key in (10, 13, curses.KEY_ENTER):
            if self.focus == 1 and not c.auto_credentials:
                c.admin_username = self.prompt_string(fy - 6 + 1, 6, max_x - 10, c.admin_username)
            elif self.focus == 2 and not c.auto_credentials:
                c.admin_password = self.prompt_string(fy - 3 + 1, 6, max_x - 10, c.admin_password)
            elif self.focus == dash_focus:
                c.dashboard_path = self.prompt_string(dash_y + 1, 6, max_x - 10, c.dashboard_path)
                if not c.dashboard_path.startswith("/"):
                    c.dashboard_path = "/" + c.dashboard_path
                if not c.dashboard_path.endswith("/"):
                    c.dashboard_path += "/"
                return "next"
            else:
                self.focus = min(dash_focus, self.focus + 1)
        return ""

    def step_branding(self, y: int, max_x: int) -> str:
        lang = self._lang()
        c = self.cfg
        self.s.addstr(y, 4, t("brand_h", lang), curses.color_pair(7) | curses.A_BOLD)
        self.s.addstr(y + 2, 4, t("brand_b", lang)[: max_x - 8])
        fields = [
            ("panel_title", t("panel_title", lang)),
            ("primary_color", t("primary_color", lang)),
            ("support_url", t("support_url", lang)),
        ]
        fy = y + 4
        field_ys = []
        for i, (attr, label) in enumerate(fields):
            val = getattr(c, attr)
            self.draw_field(fy, 4, max_x - 8, label, val, self.focus == i)
            field_ys.append((fy, attr))
            fy += 3
        self.draw_status_bar(curses.LINES - 5, max_x)
        self.draw_footer(curses.LINES - 3, max_x)
        self.s.refresh()
        key = self.s.getch()
        if key == 27:
            return "quit"
        if key in (ord("b"), curses.KEY_LEFT):
            self.focus = 0
            return "back"
        if key in (curses.KEY_UP, ord("k")):
            self.focus = max(0, self.focus - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self.focus = min(len(fields) - 1, self.focus + 1)
        elif key in (10, 13, curses.KEY_ENTER):
            if self.focus < len(fields) - 1:
                fy_i, attr = field_ys[self.focus]
                new = self.prompt_string(fy_i + 1, 6, max_x - 10, getattr(c, attr))
                setattr(c, attr, new)
                self.focus += 1
            else:
                fy_i, attr = field_ys[self.focus]
                setattr(c, attr, self.prompt_string(fy_i + 1, 6, max_x - 10, getattr(c, attr)))
                return "next"
        return ""

    def step_advanced(self, y: int, max_x: int) -> str:
        lang = self._lang()
        c = self.cfg
        self.s.addstr(y, 4, t("adv_h", lang), curses.color_pair(7) | curses.A_BOLD)
        fy = y + 3
        self.draw_field(fy, 4, max_x - 8, t("panel_port", lang), str(c.panel_port), self.focus == 0)
        fy += 3
        self.draw_toggle(fy, 4, t("skip_node", lang), c.skip_node_build, self.focus == 1)
        fy += 2
        self.draw_toggle(fy, 4, t("ufw", lang), c.configure_firewall, self.focus == 2)
        self.draw_status_bar(curses.LINES - 5, max_x)
        self.draw_footer(curses.LINES - 3, max_x)
        self.s.refresh()
        key = self.s.getch()
        if key == 27:
            return "quit"
        if key in (ord("b"), curses.KEY_LEFT):
            self.focus = 0
            return "back"
        if key in (curses.KEY_UP, ord("k")):
            self.focus = max(0, self.focus - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self.focus = min(2, self.focus + 1)
        elif key == ord(" ") and self.focus in (1, 2):
            if self.focus == 1:
                c.skip_node_build = not c.skip_node_build
            else:
                c.configure_firewall = not c.configure_firewall
        elif key in (10, 13, curses.KEY_ENTER):
            if self.focus == 0:
                port_s = self.prompt_string(y + 4, 6, max_x - 10, str(c.panel_port))
                try:
                    c.panel_port = int(port_s) or 8000
                except ValueError:
                    c.panel_port = 8000
            elif self.focus < 2:
                self.focus += 1
            else:
                return "next"
        return ""

    def step_review(self, y: int, max_x: int) -> str:
        lang = self._lang()
        c = self.cfg
        self.s.addstr(y, 4, t("review_h", lang), curses.color_pair(7) | curses.A_BOLD)
        self.s.addstr(y + 2, 4, t("review_b", lang)[: max_x - 8])
        panel_lang = next((n for code, n, _ in PANEL_LANGS if code == c.panel_default_lang), c.panel_default_lang)
        rows = [
            (t("lang_h", lang), panel_lang),
            (t("domain", lang), c.domain or t("ip_cert", lang)),
            ("HTTPS", t("no", lang) if c.skip_https else t("yes", lang)),
            (t("username", lang), t("auto", lang) if c.auto_credentials else c.admin_username),
            (t("dash_path", lang), c.dashboard_path),
            (t("panel_title", lang), c.panel_title),
            (t("panel_port", lang), str(c.panel_port)),
        ]
        ry = y + 4
        for k, v in rows:
            self.s.addstr(ry, 6, f"{k}: ", curses.color_pair(1))
            self.s.addstr(ry, 6 + len(k) + 2, str(v)[: max_x - 12], curses.color_pair(3))
            ry += 1
        self.draw_footer(curses.LINES - 3, max_x, next_label=t("install", lang))
        self.s.refresh()
        key = self.s.getch()
        if key == 27:
            return "quit"
        if key in (ord("b"), curses.KEY_LEFT):
            return "back"
        if key in (10, 13, curses.KEY_ENTER):
            return "next"
        return ""


def run_wizard(config_path: Path) -> int:
    if not attach_tty():
        sys.stderr.write("[nexuspanel] No TTY available — set SKIP_WIZARD=1 or run with: bash -c '... install'\n")
        return 2
    preflight = detect_preflight()
    cfg = Config(preflight)

    def _main(stdscr) -> int:
        ok = Wizard(stdscr, cfg, preflight).run()
        if not ok:
            return 1
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(cfg.to_json(), indent=2, ensure_ascii=False), encoding="utf-8")
        return 0

    try:
        return curses.wrapper(_main)
    except curses.error as exc:
        sys.stderr.write(f"[nexuspanel] TUI failed ({exc}) — try: SKIP_WIZARD=1 or WEB_WIZARD=1\n")
        return 2


def main() -> None:
    parser = argparse.ArgumentParser(description="NexusPanel terminal installer wizard")
    parser.add_argument("--config", required=True, help="Path to write install config JSON")
    args = parser.parse_args()
    code = run_wizard(Path(args.config))
    sys.exit(code)


if __name__ == "__main__":
    main()
