"""Enable SigmaGuard / tunnel feature flags on the panel database.

Usage:
  python3 scripts/enable_panel_flags.py
  python3 scripts/enable_panel_flags.py --flags client_api client_ss2022 cdn_fallback tunneling client_push
"""
import argparse

from app import feature_flags

DEFAULT_FLAGS = [
    "client_api",
    "api_v2",
    "client_ss2022",
    "cdn_fallback",
    "tunneling",
    "client_push",
    "node_provisioning",
    "user_portal",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--flags", nargs="*", default=DEFAULT_FLAGS)
    parser.add_argument("--off", action="store_true", help="Disable instead of enable")
    args = parser.parse_args()

    for name in args.flags:
        if name not in feature_flags.KNOWN_FLAGS:
            print(f"skip unknown flag: {name}")
            continue
        feature_flags.set_flag(name, not args.off)
        print(f"{'disabled' if args.off else 'enabled'}: {name}")


if __name__ == "__main__":
    main()
