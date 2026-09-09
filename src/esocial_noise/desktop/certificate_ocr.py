from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

import pyautogui
import pytesseract
from pywinauto import Desktop

from ..contracts import OCRSafetyBlocked
from ..runtime.execution import ExecutionContext
from ..utils import normalize_text, safe_filename


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_text(value))


def _ocr_data(image) -> dict[str, Any]:
    preferred_lang = os.getenv("OCR_LANG", "por")
    languages = [preferred_lang]
    if preferred_lang != "eng":
        languages.append("eng")
    last_error: Exception | None = None
    for lang in languages:
        try:
            return pytesseract.image_to_data(image, lang=lang, output_type=pytesseract.Output.DICT)
        except pytesseract.TesseractNotFoundError as error:
            raise OCRSafetyBlocked("Tesseract OCR nao esta instalado ou TESSERACT_CMD nao foi configurado.") from error
        except pytesseract.TesseractError as error:
            last_error = error
    raise OCRSafetyBlocked(f"Tesseract abriu, mas nao conseguiu ler a imagem. Erro: {last_error}")


def _active_window() -> tuple[str, tuple[int, int, int, int]]:
    try:
        window = Desktop(backend="uia").get_active()
        rect = window.rectangle()
        return window.window_text() or "", (rect.left, rect.top, rect.right, rect.bottom)
    except Exception:
        width, height = pyautogui.size()
        return "", (0, 0, width, height)


def _active_control():
    try:
        return Desktop(backend="uia").get_active()
    except Exception as error:
        raise OCRSafetyBlocked(f"Nao foi possivel acessar a janela ativa do Windows: {error}") from error


def _uia_descendants() -> list[Any]:
    window = _active_control()
    return window.descendants()


def _control_text(control: Any) -> tuple[str, str]:
    text = control.window_text() or control.element_info.name or ""
    control_type = control.element_info.control_type or ""
    return text, control_type


def _uia_select_certificate_and_ok(execution: ExecutionContext, target: str) -> bool:
    try:
        descendants = _uia_descendants()
    except Exception:
        return False

    target_norm = normalize_text(target)
    rows = []
    for control in descendants:
        try:
            text, control_type = _control_text(control)
        except Exception:
            continue
        if target_norm in normalize_text(text):
            rows.append(control)

    if len(rows) != 1:
        execution.event("uia_certificate_fallback_not_unique", certificate_matches=len(rows))
        return False

    try:
        execution.event("action_started", action="uia_click:certificate_subject", target=target)
        rows[0].click_input()
        time.sleep(0.25)
        rows[0].click_input()
        time.sleep(0.5)
        execution.event("action_completed", action="uia_click:certificate_subject", target=target)
        return True
    except Exception as error:
        execution.event("uia_certificate_fallback_failed", error=str(error))
        return False


def _uia_click_ok(execution: ExecutionContext) -> bool:
    try:
        descendants = _uia_descendants()
    except Exception:
        return False

    ok_buttons = []
    for control in descendants:
        try:
            text, control_type = _control_text(control)
        except Exception:
            continue
        if control_type.casefold() == "button" and normalize_text(text) == "ok":
            ok_buttons.append(control)

    if len(ok_buttons) != 1:
        execution.event("uia_ok_not_unique", ok_matches=len(ok_buttons))
        return False

    try:
        execution.event("action_started", action="uia_click:certificate_ok", target="OK")
        ok_buttons[0].click_input()
        time.sleep(0.7)
        execution.event("action_completed", action="uia_click:certificate_ok", target="OK")
        return True
    except Exception as error:
        execution.event("uia_ok_failed", error=str(error))
        return False


def _dialog_bounds_from_words(words: list[dict[str, Any]]) -> tuple[int, int, int, int] | None:
    dialog_words = [
        word for word in words
        if any(marker in normalize_text(word["text"]) for marker in ("selecione", "certificado", "tema", "emissor", "serial", "biason", "neorubber"))
    ]
    if len(dialog_words) < 5:
        return None
    left = min(word["left"] for word in dialog_words) - 20
    top = min(word["top"] for word in dialog_words) - 35
    right = max(word["left"] + word["width"] for word in dialog_words) + 60
    bottom = max(word["top"] + word["height"] for word in dialog_words) + 110
    return left, top, right, bottom


def _coordinate_click_ok(execution: ExecutionContext, words: list[dict[str, Any]]) -> bool:
    bounds = _dialog_bounds_from_words(words)
    if not bounds:
        return False
    _, _, right, bottom = bounds
    x = right - 155
    y = bottom - 38
    execution.event("action_started", action="coordinate_click:certificate_ok", target="OK", x=x, y=y)
    pyautogui.click(x, y)
    time.sleep(0.7)
    execution.event("action_completed", action="coordinate_click:certificate_ok", target="OK", x=x, y=y)
    return True


def _snapshot(execution: ExecutionContext, root: Path, label: str) -> tuple[list[dict[str, Any]], list[str], tuple[int, int, int, int], str]:
    if os.getenv("TESSERACT_CMD"):
        pytesseract.pytesseract.tesseract_cmd = os.environ["TESSERACT_CMD"]
    title, rect = _active_window()
    image = pyautogui.screenshot()
    stamp = f"{int(time.time() * 1000)}_{safe_filename(label)}"
    png = execution.artifact_dir / f"{stamp}.desktop.png"
    image.save(png)
    raw = _ocr_data(image)
    words = [
        {
            "text": str(text).strip(),
            "left": int(raw["left"][i]),
            "top": int(raw["top"][i]),
            "width": int(raw["width"][i]),
            "height": int(raw["height"][i]),
            "block": int(raw["block_num"][i]),
            "paragraph": int(raw["par_num"][i]),
            "line": int(raw["line_num"][i]),
        }
        for i, text in enumerate(raw["text"])
        if str(text).strip()
    ]
    ocr = execution.artifact_dir / f"{stamp}.ocr.json"
    ocr.write_text(json.dumps({"active_window_title": title, "rectangle": rect, "words": words}, ensure_ascii=False, indent=2), encoding="utf-8")
    artifacts = [str(png.relative_to(root)), str(ocr.relative_to(root))]
    execution.event("artifact_created", label=label, artifacts=artifacts, window_title=title)
    return words, artifacts, rect, title


def _lines(words: list[dict[str, Any]], rect: tuple[int, int, int, int]) -> list[list[dict[str, Any]]]:
    left, top, right, bottom = rect
    grouped: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    for word in words:
        x = word["left"] + word["width"] // 2
        y = word["top"] + word["height"] // 2
        if left <= x <= right and top <= y <= bottom:
            grouped.setdefault((word["block"], word["paragraph"], word["line"]), []).append(word)
    result = list(grouped.values())
    for items in result:
        items.sort(key=lambda item: item["left"])
    return result


def _matches(words: list[dict[str, Any]], target: str, rect: tuple[int, int, int, int]) -> list[tuple[int, int]]:
    target_text = normalize_text(target)
    target_compact = _compact(target)
    result: list[tuple[int, int]] = []
    for items in _lines(words, rect):
        line_text = " ".join(item["text"] for item in items)
        if target_text in normalize_text(line_text) or target_compact in _compact(line_text):
            left = min(item["left"] for item in items)
            right = max(item["left"] + item["width"] for item in items)
            top = min(item["top"] for item in items)
            bottom = max(item["top"] + item["height"] for item in items)
            # Click near the certificate subject column, not in the issuer/serial columns.
            result.append(((left + right) // 2, (top + bottom) // 2))
    return result


def _two_clicks(x: int, y: int) -> None:
    pyautogui.moveTo(x, y, duration=0.1)
    pyautogui.click(x, y)
    time.sleep(0.25)
    pyautogui.click(x, y)


def _looks_like_certificate_dialog(title: str, words: list[dict[str, Any]]) -> bool:
    all_text = normalize_text(" ".join(item["text"] for item in words))
    compact_text = _compact(all_text)
    title_text = normalize_text(title)
    compact_title = _compact(title_text)
    markers = (
        "selecione um certificado",
        "certificado",
        "certificate",
        "windows security",
        "seguranca do windows",
        "segurança do windows",
    )
    return any(marker in title_text or marker in all_text or _compact(marker) in compact_title or _compact(marker) in compact_text for marker in markers)


class CertificateOCR:
    def __init__(self, execution: ExecutionContext, root: Path, config: dict[str, Any]):
        self.execution, self.root, self.config = execution, root, config

    def select_and_confirm(self) -> list[str]:
        evidence: list[str] = []
        timeout_seconds = max(
            int(self.config.get("timeout_seconds", 45)),
            int(self.config.get("pre_ocr_human_wait_seconds", 0)),
        )
        print(f"Aguardando seletor de certificado por ate {timeout_seconds}s...", flush=True)
        if not os.getenv("TESSERACT_CMD") and not shutil.which("tesseract"):
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                if _uia_select_certificate_and_ok(self.execution, self.config["certificate_subject_exact"]):
                    print("Certificado selecionado via componente Windows.", flush=True)
                    return evidence
                time.sleep(0.5)
            raise OCRSafetyBlocked("Tesseract OCR nao esta instalado/configurado e o fallback Windows nao encontrou uma unica linha BIASON CONTABILIDADE.")
        if not os.getenv("TESSERACT_CMD"):
            if _uia_select_certificate_and_ok(self.execution, self.config["certificate_subject_exact"]):
                return evidence

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            words, artifacts, _, title = _snapshot(self.execution, self.root, "wait_certificate_dialog")
            evidence.extend(artifacts)
            if _looks_like_certificate_dialog(title, words):
                print("Seletor de certificado detectado. Iniciando OCR...", flush=True)
                break
            remaining = int(deadline - time.monotonic())
            if remaining > 0 and remaining % 10 == 0:
                print(f"Ainda aguardando CAPTCHA/seletor de certificado... {remaining}s restantes", flush=True)
            time.sleep(1)
        else:
            raise OCRSafetyBlocked("O seletor nativo de certificado nao apareceu dentro do tempo permitido.")

        for target, action in ((self.config["certificate_subject_exact"], "certificate_subject"),):
            words, before, rect, title = _snapshot(self.execution, self.root, f"before_{action}")
            if not _looks_like_certificate_dialog(title, words):
                raise OCRSafetyBlocked("A tela visivel nao foi comprovada como dialogo de certificado Windows.")
            matches = _matches(words, target, rect)
            if len(matches) != 1:
                raise OCRSafetyBlocked(f"OCR nao comprovou uma unica ocorrencia de '{target}' (ocorrencias: {len(matches)}).")
            self.execution.last_action = f"ocr_click:{action}"
            self.execution.event("action_started", action=self.execution.last_action, target=target, evidence=before)
            x, y = matches[0]
            print(f"OCR encontrou '{target}'. Clicando duas vezes na linha...", flush=True)
            _two_clicks(x, y)
            time.sleep(0.7)
            _, after, _, _ = _snapshot(self.execution, self.root, f"after_{action}")
            self.execution.event("action_completed", action=self.execution.last_action, target=target, evidence=after)
            evidence.extend(before + after)
        return evidence
