"""AmneziaWG helpers shared by panel API, provisioning, and tests."""
import random
from typing import Dict

# Obfuscation overhead + mobile paths: lower than plain WG to avoid TCP blackholes.
AWG_RECOMMENDED_MTU = 1280


def random_awg_preset() -> Dict[str, int]:
    """Return a full set of AmneziaWG obfuscation params (DB field names).

    Jmax is capped for mobile carriers — large junk packets (>~300 B) are often
    dropped on cellular (see amneziawg-go #42). Keep Jmax near Jmin+50..250.
    """
    hs = set()
    while len(hs) < 4:
        hs.add(random.randint(0x10000000, 0x7FFFFFFF))
    h1, h2, h3, h4 = sorted(hs)
    jmin = random.randint(40, 89)
    jmax = jmin + random.randint(50, 250)
    return {
        "awg_jc": random.randint(3, 6),
        "awg_jmin": jmin,
        "awg_jmax": jmax,
        "awg_s1": random.randint(15, 80),
        "awg_s2": random.randint(15, 80),
        "awg_h1": h1,
        "awg_h2": h2,
        "awg_h3": h3,
        "awg_h4": h4,
    }
