/* Shahkar web installer — wizard logic + i18n */
(function () {
  "use strict";

  const LANGS = [
    { code: "en", label: "English", flag: "🇬🇧", dir: "ltr" },
    { code: "fa", label: "فارسی", flag: "🇮🇷", dir: "rtl" },
    { code: "ru", label: "Русский", flag: "🇷🇺", dir: "ltr" },
    { code: "zh", label: "中文", flag: "🇨🇳", dir: "ltr" },
  ];

  const STEPS = [
    "welcome", "language", "network", "admin", "branding", "advanced", "review", "progress", "done",
  ];

  const T = {
    en: {
      tagline: "Professional VPN Control Plane",
      serverInfo: "Server", ip: "IP", ram: "RAM", docker: "Docker",
      welcomeTitle: "Welcome to Shahkar",
      welcomeLead: "This wizard will guide you through a production-ready install — HTTPS, PostgreSQL, Redis, secret dashboard path, and admin credentials.",
      feat1t: "One-click stack", feat1d: "Docker + PostgreSQL + Redis",
      feat2t: "Auto TLS", feat2d: "Let's Encrypt domain or IP cert",
      feat3t: "White-label", feat3d: "Multi-tenant resellers",
      feat4t: "Xray core", feat4d: "VLESS, VMess, Trojan, WG, TUIC…",
      langTitle: "Panel language",
      langLead: "Default language for the admin dashboard (users can change it later).",
      netTitle: "Network & HTTPS",
      netLead: "Choose how users reach your panel securely.",
      domainLabel: "Domain (optional)", domainHint: "Leave empty to use a certificate on your public IP.",
      emailLabel: "Let's Encrypt email (optional)",
      skipHttps: "Skip HTTPS setup", skipHttpsHint: "Panel stays on HTTP port (not recommended for production).",
      adminTitle: "Admin account",
      adminLead: "Sudo owner credentials — shown once after install.",
      autoCreds: "Generate random username & password",
      username: "Username", password: "Password",
      dashPath: "Secret dashboard path", dashPathHint: "Only the admin UI uses this path — /sub/ and /portal/ stay public.",
      regen: "Regenerate",
      brandTitle: "Branding", brandLead: "Optional — customize how the panel appears.",
      panelTitle: "Panel title", primaryColor: "Primary color", supportUrl: "Support URL (optional)",
      advTitle: "Advanced",
      panelPort: "Internal panel port", panelPortHint: "Bound to 0.0.0.0 inside Docker; nginx terminates TLS on 443.",
      skipNode: "Skip node-agent image build", skipNodeHint: "Faster install — build later on the server.",
      ufw: "Configure UFW rules", ufwHint: "Opens 80, 443, SSH and Xray inbound ports.",
      reviewTitle: "Review & install",
      progressTitle: "Installing…",
      doneTitle: "Installation complete",
      doneHint: "Save your credentials now. The password is stored only as a bcrypt hash.",
      back: "Back", next: "Next", install: "Install now",
      stepWelcome: "Welcome", stepLanguage: "Language", stepNetwork: "Network",
      stepAdmin: "Admin", stepBranding: "Branding", stepAdvanced: "Advanced",
      stepReview: "Review", stepProgress: "Install", stepDone: "Done",
      yes: "Yes", no: "No", auto: "Auto-generated",
    },
    fa: {
      tagline: "کنترل‌پنل حرفه‌ای VPN",
      serverInfo: "سرور", ip: "آی‌پی", ram: "رم", docker: "داکر",
      welcomeTitle: "به Shahkar خوش آمدید",
      welcomeLead: "این ویزارد نصب آمادهٔ production را انجام می‌دهد — HTTPS، PostgreSQL، Redis، مسیر مخفی داشبورد و اطلاعات ادمین.",
      feat1t: "نصب یک‌کلیکی", feat1d: "Docker + PostgreSQL + Redis",
      feat2t: "TLS خودکار", feat2d: "گواهی دامنه یا IP با Let's Encrypt",
      feat3t: "وایت‌لیبل", feat3d: "نمایندگان چندمستاجری",
      feat4t: "هسته Xray", feat4d: "VLESS، VMess، Trojan، WG، TUIC…",
      langTitle: "زبان پنل",
      langLead: "زبان پیش‌فرض داشبورد (کاربران بعداً می‌توانند عوض کنند).",
      netTitle: "شبکه و HTTPS",
      netLead: "نحوه دسترسی امن به پنل را انتخاب کنید.",
      domainLabel: "دامنه (اختیاری)", domainHint: "خالی بگذارید تا گواهی روی IP عمومی صادر شود.",
      emailLabel: "ایمیل Let's Encrypt (اختیاری)",
      skipHttps: "رد کردن HTTPS", skipHttpsHint: "پنل روی HTTP می‌ماند (برای production توصیه نمی‌شود).",
      adminTitle: "حساب ادمین",
      adminLead: "اطلاعات مالک sudo — فقط یک‌بار بعد از نصب نمایش داده می‌شود.",
      autoCreds: "تولید خودکار نام کاربری و رمز",
      username: "نام کاربری", password: "رمز عبور",
      dashPath: "مسیر مخفی داشبورد", dashPathHint: "فقط UI ادمین — /sub/ و /portal/ عمومی می‌مانند.",
      regen: "تولید مجدد",
      brandTitle: "برندینگ", brandLead: "اختیاری — ظاهر پنل را سفارشی کنید.",
      panelTitle: "عنوان پنل", primaryColor: "رنگ اصلی", supportUrl: "لینک پشتیبانی (اختیاری)",
      advTitle: "پیشرفته",
      panelPort: "پورت داخلی پنل", panelPortHint: "روی 0.0.0.0 در Docker؛ nginx روی 443 TLS می‌زند.",
      skipNode: "رد کردن build ایمیج node-agent", skipNodeHint: "نصب سریع‌تر — بعداً روی سرور build کنید.",
      ufw: "تنظیم UFW", ufwHint: "باز کردن 80، 443، SSH و پورت‌های inbound.",
      reviewTitle: "بررسی و نصب",
      progressTitle: "در حال نصب…",
      doneTitle: "نصب کامل شد",
      doneHint: "اطلاعات را ذخیره کنید. رمز فقط به‌صورت bcrypt hash ذخیره می‌شود.",
      back: "قبلی", next: "بعدی", install: "شروع نصب",
      stepWelcome: "خوش‌آمد", stepLanguage: "زبان", stepNetwork: "شبکه",
      stepAdmin: "ادمین", stepBranding: "برند", stepAdvanced: "پیشرفته",
      stepReview: "بررسی", stepProgress: "نصب", stepDone: "پایان",
      yes: "بله", no: "خیر", auto: "تولید خودکار",
    },
    ru: {
      tagline: "Профессиональная VPN-панель",
      serverInfo: "Сервер", ip: "IP", ram: "RAM", docker: "Docker",
      welcomeTitle: "Добро пожаловать в Shahkar",
      welcomeLead: "Мастер установит production-стек: HTTPS, PostgreSQL, Redis, секретный путь и учётные данные.",
      feat1t: "Стек в один клик", feat1d: "Docker + PostgreSQL + Redis",
      feat2t: "Авто TLS", feat2d: "Let's Encrypt для домена или IP",
      feat3t: "White-label", feat3d: "Мультитenant реселлеры",
      feat4t: "Xray", feat4d: "VLESS, VMess, Trojan, WG, TUIC…",
      langTitle: "Язык панели",
      langLead: "Язык по умолчанию для админки.",
      netTitle: "Сеть и HTTPS",
      netLead: "Как пользователи будут подключаться к панели.",
      domainLabel: "Домен (необязательно)", domainHint: "Пусто = сертификат на публичный IP.",
      emailLabel: "Email Let's Encrypt (необязательно)",
      skipHttps: "Пропустить HTTPS", skipHttpsHint: "Панель останется на HTTP.",
      adminTitle: "Админ",
      adminLead: "Учётные данные sudo — показываются один раз.",
      autoCreds: "Сгенерировать логин и пароль",
      username: "Логин", password: "Пароль",
      dashPath: "Секретный путь", dashPathHint: "Только UI админки.",
      regen: "Обновить",
      brandTitle: "Брендинг", brandLead: "Необязательно.",
      panelTitle: "Название", primaryColor: "Цвет", supportUrl: "Support URL",
      advTitle: "Дополнительно",
      panelPort: "Порт панели", panelPortHint: "0.0.0.0 в Docker; nginx на 443.",
      skipNode: "Пропустить сборку node-agent", skipNodeHint: "Быстрее — собрать позже.",
      ufw: "Настроить UFW", ufwHint: "80, 443, SSH, inbound.",
      reviewTitle: "Проверка",
      progressTitle: "Установка…",
      doneTitle: "Готово",
      doneHint: "Сохраните данные. Пароль хранится только как bcrypt hash.",
      back: "Назад", next: "Далее", install: "Установить",
      stepWelcome: "Старт", stepLanguage: "Язык", stepNetwork: "Сеть",
      stepAdmin: "Админ", stepBranding: "Бренд", stepAdvanced: "Доп.",
      stepReview: "Обзор", stepProgress: "Установка", stepDone: "Готово",
      yes: "Да", no: "Нет", auto: "Авто",
    },
    zh: {
      tagline: "专业 VPN 控制面板",
      serverInfo: "服务器", ip: "IP", ram: "内存", docker: "Docker",
      welcomeTitle: "欢迎使用 Shahkar",
      welcomeLead: "向导将完成生产级安装：HTTPS、PostgreSQL、Redis、密钥路径和管理员凭据。",
      feat1t: "一键栈", feat1d: "Docker + PostgreSQL + Redis",
      feat2t: "自动 TLS", feat2d: "Let's Encrypt 域名或 IP 证书",
      feat3t: "白标", feat3d: "多租户经销商",
      feat4t: "Xray 核心", feat4d: "VLESS、VMess、Trojan、WG、TUIC…",
      langTitle: "面板语言",
      langLead: "管理后台默认语言。",
      netTitle: "网络与 HTTPS",
      netLead: "选择安全访问方式。",
      domainLabel: "域名（可选）", domainHint: "留空则使用公网 IP 证书。",
      emailLabel: "Let's Encrypt 邮箱（可选）",
      skipHttps: "跳过 HTTPS", skipHttpsHint: "面板保持 HTTP（不推荐）。",
      adminTitle: "管理员账户",
      adminLead: "Sudo 凭据 — 安装后仅显示一次。",
      autoCreds: "自动生成用户名和密码",
      username: "用户名", password: "密码",
      dashPath: "密钥仪表板路径", dashPathHint: "仅管理 UI 使用。",
      regen: "重新生成",
      brandTitle: "品牌", brandLead: "可选定制。",
      panelTitle: "面板标题", primaryColor: "主色", supportUrl: "支持链接",
      advTitle: "高级",
      panelPort: "内部端口", panelPortHint: "Docker 0.0.0.0；nginx 443 TLS。",
      skipNode: "跳过 node-agent 构建", skipNodeHint: "更快 — 稍后构建。",
      ufw: "配置 UFW", ufwHint: "开放 80、443、SSH。",
      reviewTitle: "确认并安装",
      progressTitle: "安装中…",
      doneTitle: "安装完成",
      doneHint: "请立即保存凭据。密码仅以 bcrypt 存储。",
      back: "上一步", next: "下一步", install: "开始安装",
      stepWelcome: "欢迎", stepLanguage: "语言", stepNetwork: "网络",
      stepAdmin: "管理员", stepBranding: "品牌", stepAdvanced: "高级",
      stepReview: "确认", stepProgress: "安装", stepDone: "完成",
      yes: "是", no: "否", auto: "自动生成",
    },
  };

  const stepLabels = {
    en: ["stepWelcome", "stepLanguage", "stepNetwork", "stepAdmin", "stepBranding", "stepAdvanced", "stepReview", "stepProgress", "stepDone"],
    fa: ["stepWelcome", "stepLanguage", "stepNetwork", "stepAdmin", "stepBranding", "stepAdvanced", "stepReview", "stepProgress", "stepDone"],
    ru: ["stepWelcome", "stepLanguage", "stepNetwork", "stepAdmin", "stepBranding", "stepAdvanced", "stepReview", "stepProgress", "stepDone"],
    zh: ["stepWelcome", "stepLanguage", "stepNetwork", "stepAdmin", "stepBranding", "stepAdvanced", "stepReview", "stepProgress", "stepDone"],
  };

  let uiLang = "en";
  let panelLang = "en";
  let step = 0;
  let preflight = {};
  let progressTimer = null;

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  function t(key) {
    return (T[uiLang] && T[uiLang][key]) || T.en[key] || key;
  }

  function applyI18n() {
    const meta = LANGS.find((l) => l.code === uiLang) || LANGS[0];
    document.documentElement.lang = uiLang;
    document.documentElement.dir = meta.dir;
    $$("[data-i18n]").forEach((el) => {
      const k = el.getAttribute("data-i18n");
      if (T[uiLang][k]) el.textContent = T[uiLang][k];
    });
    renderSteps();
    if (step === 6) renderReview();
    updateNav();
  }

  function rand(n) {
    const chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
    let s = "";
    const arr = new Uint8Array(n);
    crypto.getRandomValues(arr);
    for (let i = 0; i < n; i++) s += chars[arr[i] % chars.length];
    return s;
  }

  function genDashPath() {
    return "/" + rand(16) + "/";
  }

  function genCreds() {
    $("#admin-user").value = "u" + rand(10);
    $("#admin-pass").value = rand(24);
  }

  function renderSteps() {
    const ol = $("#step-list");
    ol.innerHTML = "";
    stepLabels[uiLang].forEach((key, i) => {
      const li = document.createElement("li");
      if (i === step) li.classList.add("active");
      else if (i < step) li.classList.add("done");
      li.innerHTML = `<span class="num">${i < step ? "✓" : i + 1}</span><span>${t(key)}</span>`;
      ol.appendChild(li);
    });
  }

  function renderLangCards() {
    const box = $("#panel-lang-cards");
    box.innerHTML = "";
    LANGS.forEach((l) => {
      const div = document.createElement("div");
      div.className = "sk-lang-card" + (l.code === panelLang ? " selected" : "");
      div.innerHTML = `<span class="flag">${l.flag}</span><b>${l.label}</b>`;
      div.onclick = () => {
        panelLang = l.code;
        renderLangCards();
      };
      box.appendChild(div);
    });
  }

  function showStep(n) {
    step = n;
    $$(".sk-step-view").forEach((el) => {
      el.classList.toggle("sk-hidden", parseInt(el.getAttribute("data-step"), 10) !== n);
    });
    renderSteps();
    updateNav();
    if (n === 6) renderReview();
  }

  function updateNav() {
    const back = $("#btn-back");
    const next = $("#btn-next");
    const footer = $("#nav-footer");
    back.disabled = step <= 0 || step >= 7;
    if (step >= 7) {
      footer.classList.add("sk-hidden");
      return;
    }
    footer.classList.remove("sk-hidden");
    next.textContent = step === 6 ? t("install") : t("next");
  }

  function collectConfig() {
    const auto = $("#auto-creds").checked;
    return {
      panel_default_lang: panelLang,
      installer_ui_lang: uiLang,
      domain: $("#domain").value.trim(),
      email: $("#email").value.trim(),
      skip_https: $("#skip-https").checked,
      admin_username: auto ? "" : $("#admin-user").value.trim(),
      admin_password: auto ? "" : $("#admin-pass").value,
      auto_credentials: auto,
      dashboard_path: $("#dash-path").value.trim(),
      panel_title: $("#panel-title").value.trim() || "Shahkar",
      primary_color: $("#primary-color").value,
      support_url: $("#support-url").value.trim(),
      panel_port: parseInt($("#panel-port").value, 10) || 8000,
      skip_node_build: $("#skip-node-build").checked,
      configure_firewall: $("#enable-firewall").checked,
    };
  }

  function renderReview() {
    const c = collectConfig();
    const box = $("#review-box");
    const rows = [
      [t("stepLanguage"), LANGS.find((l) => l.code === c.panel_default_lang)?.label || c.panel_default_lang],
      ["Domain", c.domain || t("auto") + " (IP cert)"],
      ["HTTPS", c.skip_https ? t("no") : t("yes")],
      [t("username"), c.auto_credentials ? t("auto") : c.admin_username],
      [t("dashPath"), c.dashboard_path],
      [t("panelTitle"), c.panel_title],
      [t("panelPort"), String(c.panel_port)],
    ];
    box.innerHTML = "<dl>" + rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("") + "</dl>";
  }

  async function loadPreflight() {
    try {
      const res = await fetch("/api/preflight");
      preflight = await res.json();
      $("#pf-ip").textContent = preflight.public_ip || "—";
      $("#pf-ram").textContent = (preflight.ram_mb || "?") + " MB";
      const dEl = $("#pf-docker");
      dEl.textContent = preflight.docker_installed ? "OK" : "—";
      dEl.className = "sk-badge " + (preflight.docker_installed ? "ok" : "no");
      if (preflight.recommended_skip_node_build) {
        $("#skip-node-build").checked = true;
      }
    } catch (e) {
      console.warn("preflight failed", e);
    }
  }

  async function submitInstall() {
    const config = collectConfig();
    showStep(7);
    try {
      await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config),
      });
    } catch (e) {
      $("#progress-msg").textContent = "Failed to submit config: " + e.message;
      return;
    }
    pollProgress();
  }

  function pollProgress() {
    if (progressTimer) clearInterval(progressTimer);
    progressTimer = setInterval(async () => {
      try {
        const res = await fetch("/api/progress");
        const p = await res.json();
        $("#progress-fill").style.width = (p.pct || 0) + "%";
        $("#progress-pct").textContent = (p.pct || 0) + "%";
        $("#progress-msg").textContent = p.msg || "";
        if (p.log) $("#progress-log").textContent = p.log;
        if (p.done) {
          clearInterval(progressTimer);
          if (p.result) showDone(p.result);
          else showStep(8);
        }
      } catch (e) {
        /* retry */
      }
    }, 1200);
  }

  function showDone(result) {
    showStep(8);
    const el = $("#done-creds");
    el.innerHTML =
      `<div><b>${t("username")}:</b> ${result.admin_username || "—"}</div>` +
      `<div><b>${t("password")}:</b> ${result.admin_password || "—"}</div>` +
      `<div><b>${t("dashPath")}:</b> ${result.dashboard_url || result.dashboard_path || "—"}</div>`;
  }

  function bindEvents() {
    $("#ui-lang").value = uiLang;
    $("#ui-lang").onchange = (e) => {
      uiLang = e.target.value;
      applyI18n();
    };

    $("#auto-creds").onchange = (e) => {
      const on = e.target.checked;
      $("#admin-user").disabled = on;
      $("#admin-pass").disabled = on;
      if (on) genCreds();
    };

    $("#regen-path").onclick = () => {
      $("#dash-path").value = genDashPath();
    };

    $("#btn-back").onclick = () => {
      if (step > 0 && step < 7) showStep(step - 1);
    };

    $("#btn-next").onclick = () => {
      if (step < 6) showStep(step + 1);
      else if (step === 6) submitInstall();
    };
  }

  function init() {
    $("#dash-path").value = genDashPath();
    genCreds();
    renderLangCards();
    renderSteps();
    bindEvents();
    loadPreflight();
    applyI18n();
    showStep(0);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
