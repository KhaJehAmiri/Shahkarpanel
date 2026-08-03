"""Catalog of blockable services → domain packs for Family Guard.

Parents pick from a curated list of apps that are often unsuitable for
children. Each id expands to domain suffixes in client routing rules.
"""
from __future__ import annotations

from typing import Any, Dict, List


SERVICE_CATALOG: Dict[str, Dict[str, Any]] = {
    # —— social ——
    "instagram": {
        "label_fa": "اینستاگرام",
        "label_en": "Instagram",
        "category": "social",
        "popular": True,
        "aliases": ["اینستا", "insta", "ig"],
        # geosite covers the full community list; domains cover Meta backends
        # the mobile app still dials when geosite:instagram alone is not enough.
        # IP fallback when TLS sniffing fails (xhttp/mux) — also covers Meta CDN IPs.
        "geosites": ['geosite:instagram'],
        "geoips": ['geoip:facebook'],
        "domains": [
            "instagram.com",
            "cdninstagram.com",
            "ig.me",
            "igsonar.com",
            "igcdn.com",
            "instagram.fbcdn.net",
            "scontent.xx.fbcdn.net",
            "scontent.cdninstagram.com",
            "graph.instagram.com",
            "i.instagram.com",
            "b.i.instagram.com",
            # Instagram app shares these Meta edges (Facebook site stays a separate catalog item).
            "graph.facebook.com",
            "b-graph.facebook.com",
            "edge-mqtt.facebook.com",
            "mqtt-mini.facebook.com",
            "z-m-graph.facebook.com",
            "facebook.com",
            "fbcdn.net",
            "fb.com",
            "accountkit.com",
        ],
    },
    "tiktok": {
        "label_fa": "تیک‌تاک",
        "label_en": "TikTok",
        "category": "social",
        "popular": True,
        "aliases": ["تیک تاک", "tik tok"],
        "geosites": ['geosite:tiktok', 'geosite:bytedance'],
        "domains": [
            "tiktok.com",
            "tiktokv.com",
            "tiktokcdn.com",
            "tiktokcdn-us.com",
            "musical.ly",
            "byteoversea.com",
            "ibytedtos.com",
            "ttlivecdn.com",
            "tiktokv.us",
        ],
    },
    "twitter": {
        "label_fa": "توییتر / X",
        "label_en": "Twitter / X",
        "category": "social",
        "popular": True,
        "aliases": ["تویتر", "ایکس", "x"],
        "geosites": ['geosite:twitter'],
        "geoips": ['geoip:twitter'],
        "domains": [
            "twitter.com",
            "x.com",
            "t.co",
            "twimg.com",
            "pscp.tv",
            "ads-twitter.com",
        ],
    },
    "facebook": {
        "label_fa": "فیسبوک",
        "label_en": "Facebook",
        "category": "social",
        "popular": True,
        "aliases": ["فیس بوک", "fb"],
        "geosites": ['geosite:facebook', 'geosite:meta'],
        "geoips": ['geoip:facebook'],
        "domains": [
            "facebook.com", "fb.com", "fb.me", "fbcdn.net", "facebook.net", "meta.com",
        ],
    },
    "snapchat": {
        "label_fa": "اسنپ‌چت",
        "label_en": "Snapchat",
        "category": "social",
        "popular": True,
        "aliases": ["اسنپ چت"],
        "domains": [
            "snapchat.com",
            "sc-cdn.net",
            "snapkit.com",
            "snapads.com",
            "snap-dev.net",
            "addlive.io",
        ],
    },
    "reddit": {
        "label_fa": "ردیت",
        "label_en": "Reddit",
        "category": "social",
        "popular": True,
        "aliases": [],
        "geosites": ['geosite:reddit'],
        "domains": ["reddit.com", "redd.it", "redditmedia.com", "redditstatic.com"],
    },
    "pinterest": {
        "label_fa": "پینترست",
        "label_en": "Pinterest",
        "category": "social",
        "popular": False,
        "aliases": [],
        "geosites": ['geosite:pinterest'],
        "domains": ["pinterest.com", "pinimg.com"],
    },
    "threads": {
        "label_fa": "تریدز",
        "label_en": "Threads",
        "category": "social",
        "popular": True,
        "aliases": ["threads"],
        "geosites": ['geosite:threads'],
        "geoips": ['geoip:facebook'],
        "domains": [
            "threads.net",
            "threads.com",
        ],
    },
    "linkedin": {
        "label_fa": "لینکدین",
        "label_en": "LinkedIn",
        "category": "social",
        "popular": False,
        "aliases": [],
        "geosites": ['geosite:linkedin'],
        "domains": ["linkedin.com", "licdn.com"],
    },
    "tumblr": {
        "label_fa": "تامبلر",
        "label_en": "Tumblr",
        "category": "social",
        "popular": False,
        "aliases": [],
        "geosites": ['geosite:tumblr'],
        "domains": ["tumblr.com"],
    },
    # —— video ——
    "youtube": {
        "label_fa": "یوتیوب",
        "label_en": "YouTube",
        "category": "video",
        "popular": True,
        "aliases": ["یوتوب"],
        "geosites": ['geosite:youtube'],
        "domains": [
            "youtube.com",
            "youtu.be",
            "ytimg.com",
            "googlevideo.com",
            "youtube-nocookie.com",
            "yt.be",
            "ggpht.com",
        ],
    },
    "aparat": {
        "label_fa": "آپارات",
        "label_en": "Aparat",
        "category": "video",
        "popular": True,
        "aliases": ["اپارات"],
        "geosites": ['geosite:aparat'],
        "domains": ["aparat.com", "aparat.cloud"],
    },
    "netflix": {
        "label_fa": "نتفلیکس",
        "label_en": "Netflix",
        "category": "video",
        "popular": True,
        "aliases": [],
        "geosites": ['geosite:netflix'],
        "geoips": ['geoip:netflix'],
        "domains": [
            "netflix.com", "nflxvideo.net", "nflximg.net", "nflxext.com", "nflxso.net",
        ],
    },
    "twitch": {
        "label_fa": "توییچ",
        "label_en": "Twitch",
        "category": "video",
        "popular": True,
        "aliases": [],
        "geosites": ['geosite:twitch'],
        "domains": ["twitch.tv", "ttvnw.net", "jtvnw.net", "twitchcdn.net"],
    },
    "kick": {
        "label_fa": "کیک",
        "label_en": "Kick",
        "category": "video",
        "popular": False,
        "aliases": [],
        "domains": [
            "kick.com",
            "kickusercontent.com",
        ],
    },
    "disney": {
        "label_fa": "دیزنی+",
        "label_en": "Disney+",
        "category": "video",
        "popular": False,
        "aliases": ["disney plus"],
        "geosites": ['geosite:disney'],
        "domains": [
            "disneyplus.com",
            "disney.com",
            "bamgrid.com",
            "dssott.com",
        ],
    },
    "primevideo": {
        "label_fa": "پرایم ویدیو",
        "label_en": "Prime Video",
        "category": "video",
        "popular": False,
        "aliases": ["amazon prime"],
        "geosites": ['geosite:primevideo'],
        "domains": ["primevideo.com", "aiv-cdn.net"],
    },
    "pornhub": {
        "label_fa": "سایت‌های پورن (عمومی)",
        "label_en": "Major adult sites",
        "category": "adult",
        "popular": True,
        "aliases": ["porn", "پورن"],
        "geosites": ['geosite:category-porn', 'geosite:pornhub', 'geosite:xvideos', 'geosite:xhamster', 'geosite:xnxx', 'geosite:redtube', 'geosite:youporn', 'geosite:spankbang'],
        "domains": [
            "pornhub.com",
            "xvideos.com",
            "xnxx.com",
            "xhamster.com",
            "spankbang.com",
            "redtube.com",
            "youporn.com",
            "onlyfans.com",
        ],
    },
    # —— chat ——
    "telegram": {
        "label_fa": "تلگرام",
        "label_en": "Telegram",
        "category": "chat",
        "popular": True,
        "aliases": ["تلی", "tg"],
        "geosites": ['geosite:telegram'],
        "geoips": ['geoip:telegram'],
        "domains": [
            "telegram.org",
            "t.me",
            "telegram.me",
            "tdesktop.com",
            "telegra.ph",
            "telesco.pe",
            "telegram-cdn.org",
            "cdn-telegram.org",
            "telegram.dog",
            "tx.me",
            "fragment.com",
            "graph.org",
            "ton.org",
        ],
    },
    "whatsapp": {
        "label_fa": "واتساپ",
        "label_en": "WhatsApp",
        "category": "chat",
        "popular": True,
        "aliases": ["واتس اپ"],
        "geosites": ['geosite:whatsapp'],
        "geoips": ['geoip:facebook'],
        "domains": [
            "whatsapp.com",
            "whatsapp.net",
            "wa.me",
            "whatsapp-cdn.net",
        ],
    },
    "rubika": {
        "label_fa": "روبیکا",
        "label_en": "Rubika",
        "category": "chat",
        "popular": True,
        "aliases": [],
        "domains": [
            "rubika.ir",
            "rubika.com",
            "rbk.ir",
        ],
    },
    "eitaa": {
        "label_fa": "ایتا",
        "label_en": "Eitaa",
        "category": "chat",
        "popular": True,
        "aliases": [],
        "domains": [
            "eitaa.com",
            "eitaa.ir",
            "eitaa.net",
        ],
    },
    "bale": {
        "label_fa": "بله",
        "label_en": "Bale",
        "category": "chat",
        "popular": False,
        "aliases": [],
        "domains": [
            "ble.ir",
            "bale.ai",
            "bale.ir",
        ],
    },
    "soroush": {
        "label_fa": "سروش",
        "label_en": "Soroush",
        "category": "chat",
        "popular": False,
        "aliases": [],
        "domains": [
            "splus.ir",
            "soroush.app",
            "soroush-hamrah.ir",
        ],
    },
    "gap": {
        "label_fa": "گپ",
        "label_en": "Gap",
        "category": "chat",
        "popular": False,
        "aliases": [],
        "domains": [
            "gap.im",
        ],
    },
    "discord": {
        "label_fa": "دیسکورد",
        "label_en": "Discord",
        "category": "chat",
        "popular": True,
        "aliases": [],
        "geosites": ['geosite:discord'],
        "domains": [
            "discord.com", "discord.gg", "discord.media",
            "discordapp.com", "discordapp.net", "discordcdn.com",
        ],
    },
    "signal": {
        "label_fa": "سیگنال",
        "label_en": "Signal",
        "category": "chat",
        "popular": False,
        "aliases": [],
        "domains": [
            "signal.org",
            "whispersystems.org",
            "signal.art",
        ],
    },
    "skype": {
        "label_fa": "اسکایپ",
        "label_en": "Skype",
        "category": "chat",
        "popular": False,
        "aliases": [],
        "domains": [
            "skype.com",
            "skypeassets.com",
        ],
    },
    # —— games ——
    "roblox": {
        "label_fa": "روبلاکس",
        "label_en": "Roblox",
        "category": "game",
        "popular": True,
        "aliases": [],
        "geosites": ['geosite:roblox'],
        "domains": ["roblox.com", "rbxcdn.com", "roblox.qq.com"],
    },
    "minecraft": {
        "label_fa": "ماین‌کرافت",
        "label_en": "Minecraft",
        "category": "game",
        "popular": True,
        "aliases": ["ماینکرافت"],
        "domains": [
            "minecraft.net",
            "mojang.com",
            "minecraftservices.com",
            "minecraft-services.net",
        ],
    },
    "pubg": {
        "label_fa": "پابجی",
        "label_en": "PUBG",
        "category": "game",
        "popular": True,
        "aliases": ["پابجی موبایل"],
        "geosites": ['geosite:pubg'],
        "domains": ["pubg.com", "pubgmobile.com", "igamecj.com", "gcloudcs.com"],
    },
    "freefire": {
        "label_fa": "فری فایر",
        "label_en": "Free Fire",
        "category": "game",
        "popular": True,
        "aliases": ["فریفایر"],
        "domains": [
            "ff.garena.com",
            "garena.com",
            "freefiremobile.com",
            "garenanow.com",
        ],
    },
    "clash": {
        "label_fa": "کلش آف کلنز",
        "label_en": "Clash of Clans",
        "category": "game",
        "popular": True,
        "aliases": ["کلش", "coc"],
        "domains": [
            "clashofclans.com",
            "supercell.com",
            "supercell.net",
        ],
    },
    "clashroyale": {
        "label_fa": "کلش رویال",
        "label_en": "Clash Royale",
        "category": "game",
        "popular": True,
        "aliases": [],
        "domains": [
            "clashroyale.com",
            "supercell.com",
            "supercell.net",
        ],
    },
    "fortnite": {
        "label_fa": "فورتنایت",
        "label_en": "Fortnite",
        "category": "game",
        "popular": True,
        "aliases": [],
        "geosites": ['geosite:epicgames'],
        "domains": [
            "fortnite.com",
            "epicgames.com",
            "unrealengine.com",
        ],
    },
    "cod": {
        "label_fa": "کال آف دیوتی",
        "label_en": "Call of Duty",
        "category": "game",
        "popular": True,
        "aliases": ["کالاف", "cod mobile"],
        "domains": [
            "callofduty.com",
            "activision.com",
            "battle.net",
            "blizzard.com",
        ],
    },
    "steam": {
        "label_fa": "استیم",
        "label_en": "Steam",
        "category": "game",
        "popular": False,
        "aliases": [],
        "geosites": ['geosite:steam'],
        "domains": ["steampowered.com", "steamcommunity.com", "steamstatic.com"],
    },
    # —— dating / risky ——
    "tinder": {
        "label_fa": "تیندر",
        "label_en": "Tinder",
        "category": "dating",
        "popular": True,
        "aliases": [],
        "domains": [
            "tinder.com",
            "gotinder.com",
            "tindersparks.com",
        ],
    },
    "badoo": {
        "label_fa": "بادو",
        "label_en": "Badoo",
        "category": "dating",
        "popular": True,
        "aliases": [],
        "domains": [
            "badoo.com",
            "badoocdn.com",
        ],
    },
    "bumble": {
        "label_fa": "بامبل",
        "label_en": "Bumble",
        "category": "dating",
        "popular": False,
        "aliases": [],
        "domains": [
            "bumble.com",
        ],
    },
    # —— other ——
    "spotify": {
        "label_fa": "اسپاتیفای",
        "label_en": "Spotify",
        "category": "other",
        "popular": False,
        "aliases": [],
        "geosites": ['geosite:spotify'],
        "domains": ["spotify.com", "scdn.co", "spotifycdn.com", "spoti.fi"],
    },
    "soundcloud": {
        "label_fa": "ساوندکلاد",
        "label_en": "SoundCloud",
        "category": "other",
        "popular": False,
        "aliases": [],
        "domains": [
            "soundcloud.com",
            "sndcdn.com",
        ],
    },
    "gambling": {
        "label_fa": "سایت‌های شرط‌بندی",
        "label_en": "Gambling sites",
        "category": "other",
        "popular": True,
        "aliases": ["بت", "شرط بندی"],
        "domains": [
            "bet365.com",
            "1xbet.com",
            "melbet.com",
            "mostbet.com",
            "staking.com",
            "stake.com",
            "betfair.com",
            "pokerstars.com",
            "888casino.com",
        ],
    },
}


QUICK_PRESETS: Dict[str, Dict[str, Any]] = {
    "child_safe": {
        "label_fa": "کودک امن",
        "label_en": "Child safe",
        "hint_fa": "پورن + تبلیغات + سایت‌های بزرگسال",
        "hint_en": "Adult + ads + major adult sites",
        "block_adult": True,
        "block_ads": True,
        "services": ["pornhub"],
    },
    "no_social": {
        "label_fa": "بدون شبکه اجتماعی",
        "label_en": "No social apps",
        "hint_fa": "اینستا، تیک‌تاک، توییتر و …",
        "hint_en": "Instagram, TikTok, X, …",
        "block_adult": True,
        "block_ads": False,
        "services": [
            "instagram", "tiktok", "twitter", "facebook", "snapchat",
            "reddit", "pinterest", "threads", "tumblr",
        ],
    },
    "no_video": {
        "label_fa": "بدون ویدیو",
        "label_en": "No video apps",
        "hint_fa": "یوتیوب، آپارات، نتفلیکس، توییچ",
        "hint_en": "YouTube, Aparat, Netflix, Twitch",
        "block_adult": True,
        "block_ads": False,
        "services": ["youtube", "aparat", "netflix", "twitch", "kick", "disney", "primevideo"],
    },
    "no_games": {
        "label_fa": "بدون بازی آنلاین",
        "label_en": "No online games",
        "hint_fa": "روبلاکس، پابجی، فری‌فایر، …",
        "hint_en": "Roblox, PUBG, Free Fire, …",
        "block_adult": False,
        "block_ads": False,
        "services": [
            "roblox", "minecraft", "pubg", "freefire", "clash",
            "clashroyale", "fortnite", "cod", "steam",
        ],
    },
    "no_dating": {
        "label_fa": "بدون دوستیابی",
        "label_en": "No dating apps",
        "hint_fa": "تیندر، بادو و مشابه",
        "hint_en": "Tinder, Badoo, …",
        "block_adult": True,
        "block_ads": False,
        "services": ["tinder", "badoo", "bumble"],
    },
}


CATEGORY_ORDER = ["social", "video", "chat", "game", "dating", "adult", "other"]

ADULT_GEOSITE = "geosite:category-porn"
ADS_GEOSITE = "geosite:category-ads-all"


def list_services_for_api(*, lang: str = "fa") -> List[Dict[str, Any]]:
    fa = lang.startswith("fa")
    rows: List[Dict[str, Any]] = []
    for sid, meta in SERVICE_CATALOG.items():
        label = meta.get("label_fa") if fa else meta.get("label_en")
        rows.append(
            {
                "id": sid,
                "label": label or sid,
                "category": meta.get("category") or "other",
                "popular": bool(meta.get("popular")),
                "aliases": list(meta.get("aliases") or []),
                "domain_count": len(meta.get("domains") or []),
            }
        )
    cat_rank = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    rows.sort(
        key=lambda r: (
            cat_rank.get(r["category"], 99),
            0 if r["popular"] else 1,
            r["label"],
        )
    )
    return rows


def list_presets_for_api(*, lang: str = "fa") -> List[Dict[str, Any]]:
    fa = lang.startswith("fa")
    out: List[Dict[str, Any]] = []
    for pid, meta in QUICK_PRESETS.items():
        out.append(
            {
                "id": pid,
                "label": meta.get("label_fa") if fa else meta.get("label_en"),
                "hint": meta.get("hint_fa") if fa else meta.get("hint_en"),
                "block_adult": bool(meta.get("block_adult")),
                "block_ads": bool(meta.get("block_ads")),
                "services": list(meta.get("services") or []),
            }
        )
    return out


def domains_for_services(service_ids: List[str] | None) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for sid in service_ids or []:
        meta = SERVICE_CATALOG.get(str(sid))
        if not meta:
            continue
        for domain in meta.get("domains") or []:
            d = str(domain).strip().lower().lstrip(".")
            if d and d not in seen:
                seen.add(d)
                out.append(d)
    return out


def geosites_for_services(service_ids: List[str] | None) -> List[str]:
    """Geosite tags declared on catalog entries (e.g. ``geosite:instagram``)."""
    out: List[str] = []
    seen: set[str] = set()
    for sid in service_ids or []:
        meta = SERVICE_CATALOG.get(str(sid))
        if not meta:
            continue
        for raw in meta.get("geosites") or []:
            g = str(raw).strip()
            if not g:
                continue
            if not g.startswith("geosite:"):
                g = f"geosite:{g}"
            if g not in seen:
                seen.add(g)
                out.append(g)
    return out


def geoips_for_services(service_ids: List[str] | None) -> List[str]:
    """GeoIP tags for IP-level blocks when domain sniffing is unavailable."""
    out: List[str] = []
    seen: set[str] = set()
    for sid in service_ids or []:
        meta = SERVICE_CATALOG.get(str(sid))
        if not meta:
            continue
        for raw in meta.get("geoips") or []:
            g = str(raw).strip()
            if not g:
                continue
            if not g.startswith("geoip:"):
                g = f"geoip:{g}"
            if g not in seen:
                seen.add(g)
                out.append(g)
    return out
