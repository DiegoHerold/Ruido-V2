from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

import pyautogui
from pywinauto import Desktop


PROFILE_COPY_FILES = (
    "Preferences",
    "Secure Preferences",
    "Cookies",
    "Login Data",
)

PROFILE_COPY_DIRS = (
    "Network",
    "Local Storage",
    "Session Storage",
    "IndexedDB",
    "databases",
    "File System",
    "Extensions",
    "Extension State",
    "Local Extension Settings",
    "Sync Extension Settings",
)

PROFILE_EXTENSION_DIRS = (
    "Extensions",
    "Extension State",
    "Local Extension Settings",
    "Sync Extension Settings",
)

AUTH_STATE_FILES = (
    "Cookies",
    "Cookies-journal",
    "Current Session",
    "Current Tabs",
    "Last Session",
    "Last Tabs",
)

AUTH_STATE_DIRS = (
    "Sessions",
    "Session Storage",
    "Local Storage",
    "IndexedDB",
    "databases",
    "File System",
)


def close_all_chrome_instances(wait_seconds: int = 10) -> None:
    subprocess.run(["taskkill", "/IM", "chrome.exe", "/F"], capture_output=True, text=True, check=False)
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        probe = subprocess.run(["tasklist", "/FI", "IMAGENAME eq chrome.exe"], capture_output=True, text=True, check=False)
        if "chrome.exe" not in probe.stdout.lower():
            return
        time.sleep(0.5)
    raise RuntimeError("Ainda ha instancias do Chrome em execucao; nao e seguro reiniciar o eSocial.")


def chrome_executable() -> Path:
    candidates = (
        Path(os.environ.get("PROGRAMFILES", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise RuntimeError("Google Chrome nao encontrado nos caminhos padrao do Windows.")


def last_chrome_profile() -> tuple[Path, str]:
    root = Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"
    if not root.exists():
        raise RuntimeError("Perfil do Google Chrome nao encontrado. Instale/abra o Chrome antes de executar.")
    if (root / "SingletonLock").exists():
        raise RuntimeError("O perfil Chrome esta em uso. Feche todas as janelas do Chrome antes de iniciar a automacao.")
    name = "Default"
    try:
        name = json.loads((root / "Local State").read_text(encoding="utf-8")).get("profile", {}).get("last_used", "Default")
    except (OSError, json.JSONDecodeError):
        pass
    return root, name if (root / name).exists() else "Default"


def _copy_profile_data(source_profile: Path, target_profile: Path, include_extensions: bool = True) -> None:
    target_profile.mkdir(parents=True, exist_ok=True)
    for file_name in PROFILE_COPY_FILES:
        source_file = source_profile / file_name
        if source_file.exists():
            shutil.copy2(source_file, target_profile / file_name)
    copy_dirs = PROFILE_COPY_DIRS if include_extensions else tuple(item for item in PROFILE_COPY_DIRS if item not in PROFILE_EXTENSION_DIRS)
    for dir_name in copy_dirs:
        source_dir = source_profile / dir_name
        target_dir = target_profile / dir_name
        if source_dir.exists():
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(source_dir, target_dir)
    for stale_name in ("Current Session", "Current Tabs", "Last Session", "Last Tabs"):
        stale_file = target_profile / stale_name
        if stale_file.exists():
            stale_file.unlink()


def mirrored_last_chrome_profile(target_root: Path, refresh: bool = True) -> tuple[Path, str]:
    source_root, profile_name = last_chrome_profile()
    source_profile = source_root / profile_name
    target_profile = target_root / profile_name
    if not source_profile.exists():
        raise RuntimeError(f"Perfil Chrome de origem nao encontrado: {source_profile}")

    if refresh and target_root.exists():
        shutil.rmtree(target_root)
    target_root.mkdir(parents=True, exist_ok=True)

    local_state = source_root / "Local State"
    if local_state.exists():
        shutil.copy2(local_state, target_root / "Local State")

    if refresh or not target_profile.exists():
        _copy_profile_data(source_profile, target_profile)

    return target_root, profile_name


def clear_browser_auth_state(target_profile: Path) -> None:
    """Remove cookies/sessao/armazenamento, preservando extensoes e preferencias."""
    network_dir = target_profile / "Network"
    for file_name in AUTH_STATE_FILES:
        for candidate in (target_profile / file_name, network_dir / file_name):
            if candidate.exists():
                candidate.unlink()
    for dir_name in AUTH_STATE_DIRS:
        candidate = target_profile / dir_name
        if candidate.exists():
            shutil.rmtree(candidate)


def mirrored_last_chrome_profile_for_manual_login(target_root: Path) -> tuple[Path, str]:
    """Usa o ultimo usuario como base, mas sempre inicia sem cookies/sessao antigos."""
    profile_root, profile_name = mirrored_last_chrome_profile(target_root, refresh=True)
    clear_browser_auth_state(profile_root / profile_name)
    return profile_root, profile_name


def mirrored_last_chrome_profile_without_extensions(target_root: Path) -> tuple[Path, str]:
    """Copia o ultimo perfil com a sessao atual, mas sem extensoes bloqueadas por politica."""
    source_root, profile_name = last_chrome_profile()
    source_profile = source_root / profile_name
    target_profile = target_root / profile_name
    if not source_profile.exists():
        raise RuntimeError(f"Perfil Chrome de origem nao encontrado: {source_profile}")
    if target_root.exists():
        shutil.rmtree(target_root)
    target_root.mkdir(parents=True, exist_ok=True)
    local_state = source_root / "Local State"
    if local_state.exists():
        shutil.copy2(local_state, target_root / "Local State")
    _copy_profile_data(source_profile, target_profile, include_extensions=False)
    return target_root, profile_name


def clear_esocial_cookies_from_last_profile() -> None:
    """Limpa cookies de eSocial/gov.br no ultimo perfil real antes do login manual."""
    source_root, profile_name = last_chrome_profile()
    profile = source_root / profile_name
    cookie_files = [profile / "Cookies", profile / "Network" / "Cookies"]
    host_markers = ("%esocial.gov.br%", "%acesso.gov.br%", "%gov.br%")
    for cookie_file in cookie_files:
        if not cookie_file.exists():
            continue
        connection = sqlite3.connect(str(cookie_file))
        try:
            cursor = connection.cursor()
            for marker in host_markers:
                cursor.execute("DELETE FROM cookies WHERE host_key LIKE ?", (marker,))
            connection.commit()
        finally:
            connection.close()


def sync_last_chrome_extensions(target_root: Path) -> tuple[Path, str]:
    source_root, profile_name = last_chrome_profile()
    source_profile = source_root / profile_name
    target_profile = target_root / profile_name
    if not source_profile.exists():
        raise RuntimeError(f"Perfil Chrome de origem nao encontrado: {source_profile}")
    target_root.mkdir(parents=True, exist_ok=True)
    local_state = source_root / "Local State"
    if local_state.exists():
        shutil.copy2(local_state, target_root / "Local State")
    _copy_profile_data(source_profile, target_profile)
    return target_root, profile_name


def open_real_last_user_chrome(url: str, remote_debugging_port: int | None = None) -> subprocess.Popen:
    profile_root, profile_name = last_chrome_profile()
    command = [
        str(chrome_executable()),
    ]
    if remote_debugging_port:
        command.extend([
            f"--remote-debugging-port={remote_debugging_port}",
            "--remote-debugging-address=127.0.0.1",
            "--no-first-run",
            "--no-default-browser-check",
        ])
    command.extend([
        f"--profile-directory={profile_name}",
    ])
    command.append(url)
    print(f"Chrome user data: {profile_root}", flush=True)
    print(f"Chrome profile: {profile_name}", flush=True)
    print(f"Chrome debug port: {remote_debugging_port or 'desativada'}", flush=True)
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_debug_chrome(url: str, user_data_dir: Path, remote_debugging_port: int) -> subprocess.Popen:
    user_data_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(chrome_executable()),
        f"--remote-debugging-port={remote_debugging_port}",
        "--remote-debugging-address=127.0.0.1",
        "--no-first-run",
        "--no-default-browser-check",
        f"--user-data-dir={user_data_dir}",
        url,
    ]
    print(f"Chrome user data: {user_data_dir}", flush=True)
    print("Chrome profile: debug automation profile", flush=True)
    print(f"Chrome debug port: {remote_debugging_port}", flush=True)
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def maximize_chrome_window(timeout_seconds: int = 10) -> bool:
    deadline = time.monotonic() + timeout_seconds
    screen_width, screen_height = pyautogui.size()
    while time.monotonic() < deadline:
        try:
            windows = Desktop(backend="uia").windows()
            for window in windows:
                title = (window.window_text() or "").casefold()
                class_name = (window.element_info.class_name or "").casefold()
                if "chrome" in title or "chrome_widgetwin" in class_name:
                    window.set_focus()
                    try:
                        window.restore()
                    except Exception:
                        pass
                    try:
                        window.move_window(0, 0, screen_width, screen_height, repaint=True)
                    except Exception:
                        pass
                    window.maximize()
                    return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def screen_size() -> tuple[int, int]:
    width, height = pyautogui.size()
    return int(width), int(height)
