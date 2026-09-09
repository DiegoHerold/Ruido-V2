from pathlib import Path

from esocial_noise.browser.profile import sync_last_chrome_extensions


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    target_root = root / ".chrome-automation-profile"
    profile_root, profile_name = sync_last_chrome_extensions(target_root)
    print(f"Extensoes sincronizadas do ultimo usuario para: {profile_root / profile_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
