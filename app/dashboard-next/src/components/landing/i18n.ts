export type LandingLang = "fa" | "en";

export const CTA_PRIMARY_HREF = "/register/";
export const CTA_DEMO_HREF = "/register/?intent=demo";
export const CTA_SIGNIN_HREF = "/portal/";

/** Headline options — default is index 0; swap after user picks. */
export const HEADLINE_OPTIONS = {
  fa: [
    "اینترنت بدون قطعی، حتی وقتی همه‌چی فیلتره",
    "وقتش رسیده اتصال‌های شکننده را کنار بگذارید",
    "اتصالی که وسط کار قطع نمی‌شود",
  ],
  en: [
    "Stay online when everything else drops",
    "It's time to ditch fragile proxies",
    "A connection built for filtered networks",
  ],
} as const;

export type LandingCopy = {
  metaTitle: string;
  metaDescription: string;
  brand: string;
  nav: {
    product: string;
    how: string;
    platforms: string;
    stories: string;
    signIn: string;
  };
  langToggle: string;
  hero: {
    headline: string;
    subhead: string;
    primaryCta: string;
    secondaryCta: string;
  };
  trust: {
    label: string;
    badges: string[];
  };
  how: {
    eyebrow: string;
    title: string;
    body: string;
    link: string;
    left: string;
    center: string;
    right: string;
  };
  features: {
    left: {
      eyebrow: string;
      title: string;
      body: string;
      link: string;
    };
    right: {
      eyebrow: string;
      title: string;
      body: string;
      link: string;
    };
  };
  ecosystem: {
    eyebrow: string;
    title: string;
    body: string;
    items: { title: string; body: string; icon: string }[];
  };
  access: {
    eyebrow: string;
    title: string;
    body: string;
    link: string;
    treeLabels: string[];
    feedTitle: string;
    feedItems: { device: string; status: string; time: string }[];
  };
  pillars: {
    items: {
      title: string;
      body: string;
      link: string;
      icon: string;
    }[];
  };
  deploy: {
    eyebrow: string;
    title: string;
    body: string;
    primaryCta: string;
    secondaryCta: string;
    platforms: { name: string; hint: string }[];
  };
  stats: {
    eyebrow: string;
    title: string;
    items: { value: string; label: string }[];
  };
  cases: {
    eyebrow: string;
    title: string;
    items: { quote: string; name: string; role: string; outcome: string }[];
  };
  finalCta: {
    title: string;
    body: string;
    primaryCta: string;
    secondaryCta: string;
  };
  footer: {
    tagline: string;
    columns: { title: string; links: { label: string; href: string }[] }[];
    copyright: string;
    status: string;
  };
  mock: {
    dashTitle: string;
    servers: string;
    connected: string;
    latency: string;
    quickConnect: string;
    protocols: string;
    usage: string;
    used: string;
    remaining: string;
    devices: string;
  };
};

export const copy: Record<LandingLang, LandingCopy> = {
  fa: {
    metaTitle: "شاهکار — اینترنت بدون قطعی",
    metaDescription:
      "سرویس پرمیوم پروکسی و VPN مبتنی بر Xray. چند پروتکل، مانیتورینگ دائمی، راه‌اندازی ساده. شروع رایگان.",
    brand: "شاهکار",
    nav: {
      product: "محصول",
      how: "نحوه کار",
      platforms: "پلتفرم‌ها",
      stories: "تجربه‌ها",
      signIn: "ورود",
    },
    langToggle: "EN",
    hero: {
      headline: HEADLINE_OPTIONS.fa[0],
      subhead:
        "زیرساخت سازمانی روی Xray؛ تجربهٔ ساده برای همه — چند پروتکل، انتخاب هوشمند سرور، وصل در کمتر از یک دقیقه.",
      primaryCta: "شروع رایگان",
      secondaryCta: "درخواست دمو",
    },
    trust: {
      label: "مورد اعتماد هزاران کاربر",
      badges: ["VLESS", "Reality", "VMess", "Shadowsocks", "Trojan", "WireGuard"],
    },
    how: {
      eyebrow: "نحوه اتصال",
      title: "دسترسی امن، سرعت بدون افت",
      body: "از دستگاه شما تا سرور — مسیر تأییدشده، بدون پیچیدگی فنی.",
      link: "بیشتر بدانید",
      left: "دستگاه شما",
      center: "مسیر تأییدشده",
      right: "سرور شاهکار",
    },
    features: {
      left: {
        eyebrow: "چندپروتکل",
        title: "چند پروتکل، یک اتصال",
        body: "اگر یک مسیر بسته شد، مسیر بعدی آماده است — بدون تنظیم دستی.",
        link: "بیشتر بدانید",
      },
      right: {
        eyebrow: "مانیتورینگ",
        title: "مانیتورینگ لحظه‌ای مصرف",
        body: "حجم، وضعیت و انقضا را شفاف ببینید — بدون حدس زدن.",
        link: "بیشتر بدانید",
      },
    },
    ecosystem: {
      eyebrow: "سازگاری",
      title: "سازگار با همه‌چیز",
      body: "همان لینک اشتراک؛ روی هر دستگاهی که کار می‌کنید.",
      items: [
        { icon: "win", title: "Windows", body: "کلاینت‌های رایج دسکتاپ" },
        { icon: "mac", title: "macOS", body: "ایمپورت یک‌کلیکی اشتراک" },
        { icon: "linux", title: "Linux", body: "CLI و کلاینت گرافیکی" },
        { icon: "ios", title: "iOS", body: "اپ‌های محبوب موبایل" },
        { icon: "android", title: "Android", body: "اتصال پایدار روی گوشی" },
        { icon: "router", title: "Router", body: "پوشش کل شبکه خانگی" },
      ],
    },
    access: {
      eyebrow: "کنترل اکانت",
      title: "کنترل کامل روی اکانتت",
      body: "دستگاه‌ها، وضعیت اتصال و محدودیت پلن — همه در یک نگاه.",
      link: "بیشتر بدانید",
      treeLabels: ["اکانت شما", "پلن فعال", "دستگاه ۱", "دستگاه ۲", "دستگاه ۳"],
      feedTitle: "فعالیت اخیر",
      feedItems: [
        { device: "لپ‌تاپ — macOS", status: "وصل", time: "۲ دقیقه پیش" },
        { device: "گوشی — Android", status: "وصل", time: "۱۸ دقیقه پیش" },
        { device: "PC — Windows", status: "قطع", time: "دیروز" },
      ],
    },
    pillars: {
      items: [
        {
          icon: "devices",
          title: "مدیریت دستگاه‌ها",
          body: "ببینید کدام دستگاه وصل است و محدودیت پلن را رعایت کنید.",
          link: "بیشتر بدانید",
        },
        {
          icon: "lock",
          title: "رمزنگاری end-to-end",
          body: "ترافیک روی تونل رمزنگاری‌شده منتقل می‌شود — بدون لاگ محتوا.",
          link: "بیشتر بدانید",
        },
        {
          icon: "std",
          title: "استانداردهای باز",
          body: "پروتکل‌های رایج صنعت؛ وابسته به یک اپ اختصاصی نیستید.",
          link: "بیشتر بدانید",
        },
      ],
    },
    deploy: {
      eyebrow: "نصب سریع",
      title: "نصب روی هر پلتفرمی",
      body: "لینک اشتراک را بگیرید، در کلاینت ایمپورت کنید، وصل شوید.",
      primaryCta: "شروع رایگان",
      secondaryCta: "مشاهده راهنما",
      platforms: [
        { name: "v2rayNG", hint: "Android" },
        { name: "Streisand", hint: "iOS" },
        { name: "Hiddify", hint: "چندپلتفرم" },
        { name: "Clash Meta", hint: "دسکتاپ" },
        { name: "AmneziaWG", hint: "WireGuard" },
        { name: "Router", hint: "OpenWrt / ASUS" },
      ],
    },
    stats: {
      eyebrow: "زیرساخت",
      title: "طراحی‌شده برای سرعت و پایداری",
      items: [
        { value: "۹۹.۹٪", label: "آپتایم هدف" },
        { value: "۳۹٬۰۰۰+", label: "کاربر فعال" },
        { value: "۱۳", label: "سرور در ۳ قاره" },
      ],
    },
    cases: {
      eyebrow: "از کاربران",
      title: "کسانی که هر روز وصل می‌مانند",
      items: [
        {
          quote:
            "قبلاً وسط جلسه قطع می‌شدم. دو ماه است کال‌های کاری‌ام پایدار مانده.",
          name: "آرش م.",
          role: "فریلنسر ریموت",
          outcome: "اتصال پایدار در جلسات",
        },
        {
          quote:
            "راه‌اندازی واقعاً ساده بود. لینک را زدم، وصل شدم — بدون درگیری با تنظیمات.",
          name: "سارا ک.",
          role: "دانشجو",
          outcome: "راه‌اندازی زیر ۱ دقیقه",
        },
      ],
    },
    finalCta: {
      title: "همین امروز وصل بمانید",
      body: "اکانت بگیرید، لینک را ایمپورت کنید، کارتان را ادامه دهید.",
      primaryCta: "شروع رایگان",
      secondaryCta: "درخواست دمو",
    },
    footer: {
      tagline: "زیرساخت پایدار؛ تجربهٔ ساده.",
      columns: [
        {
          title: "محصول",
          links: [
            { label: "ویژگی‌ها", href: "#features" },
            { label: "نحوه کار", href: "#how" },
            { label: "پلتفرم‌ها", href: "#platforms" },
          ],
        },
        {
          title: "شروع",
          links: [
            { label: "ثبت‌نام", href: "/register/" },
            { label: "ورود", href: "/portal/" },
            { label: "نمایندگی", href: "/become-reseller/" },
          ],
        },
        {
          title: "منابع",
          links: [
            { label: "راهنمای اتصال", href: "#deploy" },
            { label: "پروتکل‌ها", href: "#trust" },
            { label: "تجربه‌ها", href: "#cases" },
          ],
        },
        {
          title: "قانونی",
          links: [
            { label: "حریم خصوصی", href: "#" },
            { label: "شرایط استفاده", href: "#" },
          ],
        },
      ],
      copyright: "شاهکار. تمامی حقوق محفوظ است.",
      status: "وضعیت سرویس — عملیاتی",
    },
    mock: {
      dashTitle: "پنل شاهکار",
      servers: "سرورها",
      connected: "وصل",
      latency: "تأخیر",
      quickConnect: "اتصال سریع",
      protocols: "پروتکل فعال",
      usage: "مصرف این دوره",
      used: "مصرف‌شده",
      remaining: "باقی‌مانده",
      devices: "دستگاه‌ها",
    },
  },
  en: {
    metaTitle: "Shahkar — stay online when others drop",
    metaDescription:
      "Premium Xray-based proxy/VPN. Multi-protocol, watched uptime, one-tap setup. Start free.",
    brand: "Shahkar",
    nav: {
      product: "Product",
      how: "How it works",
      platforms: "Platforms",
      stories: "Stories",
      signIn: "Sign in",
    },
    langToggle: "فا",
    hero: {
      headline: HEADLINE_OPTIONS.en[0],
      subhead:
        "Enterprise-grade Xray infrastructure with a consumer-simple experience — multi-protocol, smart server pick, live in under a minute.",
      primaryCta: "Start free",
      secondaryCta: "Request a demo",
    },
    trust: {
      label: "Trusted by thousands of users",
      badges: ["VLESS", "Reality", "VMess", "Shadowsocks", "Trojan", "WireGuard"],
    },
    how: {
      eyebrow: "Connection path",
      title: "Secure access. Speed that holds.",
      body: "From your device to the node — a verified path, no jargon.",
      link: "Learn more",
      left: "Your device",
      center: "Verified path",
      right: "Shahkar node",
    },
    features: {
      left: {
        eyebrow: "Multi-protocol",
        title: "Many protocols. One connection.",
        body: "When a path closes, the next is ready — no manual fiddling.",
        link: "Learn more",
      },
      right: {
        eyebrow: "Monitoring",
        title: "Live usage monitoring",
        body: "See traffic, status, and expiry clearly — no guessing.",
        link: "Learn more",
      },
    },
    ecosystem: {
      eyebrow: "Compatibility",
      title: "Works with everything",
      body: "One subscription link — every device you already use.",
      items: [
        { icon: "win", title: "Windows", body: "Popular desktop clients" },
        { icon: "mac", title: "macOS", body: "One-click sub import" },
        { icon: "linux", title: "Linux", body: "CLI and GUI clients" },
        { icon: "ios", title: "iOS", body: "Familiar mobile apps" },
        { icon: "android", title: "Android", body: "Stable on the go" },
        { icon: "router", title: "Router", body: "Cover the whole network" },
      ],
    },
    access: {
      eyebrow: "Account control",
      title: "Full control of your account",
      body: "Devices, connection state, and plan limits — one glance.",
      link: "Learn more",
      treeLabels: ["Your account", "Active plan", "Device 1", "Device 2", "Device 3"],
      feedTitle: "Recent activity",
      feedItems: [
        { device: "Laptop — macOS", status: "Online", time: "2 min ago" },
        { device: "Phone — Android", status: "Online", time: "18 min ago" },
        { device: "PC — Windows", status: "Offline", time: "Yesterday" },
      ],
    },
    pillars: {
      items: [
        {
          icon: "devices",
          title: "Device management",
          body: "See what’s connected and stay within plan limits.",
          link: "Learn more",
        },
        {
          icon: "lock",
          title: "End-to-end encryption",
          body: "Traffic rides an encrypted tunnel — no content logs.",
          link: "Learn more",
        },
        {
          icon: "std",
          title: "Open standards",
          body: "Industry protocols — you’re not locked to one app.",
          link: "Learn more",
        },
      ],
    },
    deploy: {
      eyebrow: "Quick setup",
      title: "Install on any platform",
      body: "Get the sub link, import it, connect.",
      primaryCta: "Start free",
      secondaryCta: "View guide",
      platforms: [
        { name: "v2rayNG", hint: "Android" },
        { name: "Streisand", hint: "iOS" },
        { name: "Hiddify", hint: "Cross-platform" },
        { name: "Clash Meta", hint: "Desktop" },
        { name: "AmneziaWG", hint: "WireGuard" },
        { name: "Router", hint: "OpenWrt / ASUS" },
      ],
    },
    stats: {
      eyebrow: "Infrastructure",
      title: "Built for speed and uptime",
      items: [
        { value: "99.9%", label: "uptime target" },
        { value: "39,000+", label: "active users" },
        { value: "13", label: "servers · 3 continents" },
      ],
    },
    cases: {
      eyebrow: "From users",
      title: "People who stay online daily",
      items: [
        {
          quote:
            "I used to drop mid-meeting. Two months on Shahkar and work calls stay stable.",
          name: "Arash M.",
          role: "Remote freelancer",
          outcome: "Stable meeting connectivity",
        },
        {
          quote:
            "Setup was genuinely simple. Imported the link and connected — no config drama.",
          name: "Sara K.",
          role: "Student",
          outcome: "Live in under a minute",
        },
      ],
    },
    finalCta: {
      title: "Stay online today",
      body: "Get an account, import the link, get back to work.",
      primaryCta: "Start free",
      secondaryCta: "Request a demo",
    },
    footer: {
      tagline: "Reliable infrastructure. Simple experience.",
      columns: [
        {
          title: "Product",
          links: [
            { label: "Features", href: "#features" },
            { label: "How it works", href: "#how" },
            { label: "Platforms", href: "#platforms" },
          ],
        },
        {
          title: "Get started",
          links: [
            { label: "Sign up", href: "/register/" },
            { label: "Sign in", href: "/portal/" },
            { label: "Reseller", href: "/become-reseller/" },
          ],
        },
        {
          title: "Resources",
          links: [
            { label: "Setup guide", href: "#deploy" },
            { label: "Protocols", href: "#trust" },
            { label: "Stories", href: "#cases" },
          ],
        },
        {
          title: "Legal",
          links: [
            { label: "Privacy", href: "#" },
            { label: "Terms", href: "#" },
          ],
        },
      ],
      copyright: "Shahkar. All rights reserved.",
      status: "System status — Operational",
    },
    mock: {
      dashTitle: "Shahkar panel",
      servers: "Servers",
      connected: "Connected",
      latency: "Latency",
      quickConnect: "Quick connect",
      protocols: "Active protocol",
      usage: "Period usage",
      used: "Used",
      remaining: "Left",
      devices: "Devices",
    },
  },
};
