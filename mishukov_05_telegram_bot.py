import logging
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests

from logging_utils import emit_level_probe, setup_stage_logger


SCRIPT_DIR = Path(__file__).resolve().parent
PARSER_SCRIPT = SCRIPT_DIR / "первое задание - парсинг.py"
SECOND_TASK_SCRIPT = SCRIPT_DIR / "второе задание - расчеты.py"
THIRD_TASK_SCRIPT = SCRIPT_DIR / "третье задание - графики.py"
FOURTH_TASK_SCRIPT = SCRIPT_DIR / "четвертое задание - статистика.py"

SECOND_TASK_PDF = (
    SCRIPT_DIR / "второе задание - результаты" / "второе задание - расчеты.pdf"
)
THIRD_TASK_PDF = (
    SCRIPT_DIR / "третье задание - результаты" / "третье задание - графики.pdf"
)
FOURTH_TASK_PDF = (
    SCRIPT_DIR / "четвертое задание - результаты" / "четвертое задание - статистика.pdf"
)
CSV_PATTERNS = ("первое задание - данные*.csv", "auto_ru_used_moscow*.csv")

PARSER_PATH_RE = re.compile(r"Сохранено \d+ записей в (.+)")
AUTO_PAGES = os.getenv("AUTO_PAGES", "5")
AUTO_HEADFUL = os.getenv("AUTO_HEADFUL", "0") == "1"
POLL_TIMEOUT = int(os.getenv("TELEGRAM_POLL_TIMEOUT", "30"))
REQUEST_TIMEOUT = int(os.getenv("TELEGRAM_REQUEST_TIMEOUT", "90"))
logger = setup_stage_logger("этап_5_чат_бот")

RUNNING_CHATS: set[int] = set()
RUNNING_LOCK = threading.Lock()


class TelegramBot:
    def __init__(self, token: str):
        if not token:
            raise SystemExit(
                "Не найден TELEGRAM_BOT_TOKEN.\n"
                "Перед запуском задайте переменную окружения, например:\n"
                "export TELEGRAM_BOT_TOKEN='ваш_токен'"
            )
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}/"
        self.session = requests.Session()

    def _post_json(self, method: str, payload: dict) -> dict:
        response = self.session.post(
            self.base_url + method,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error for {method}: {data}")
        return data["result"]

    def _post_multipart(self, method: str, data: dict, files: dict) -> dict:
        response = self.session.post(
            self.base_url + method,
            data=data,
            files=files,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        result = response.json()
        if not result.get("ok"):
            raise RuntimeError(f"Telegram API error for {method}: {result}")
        return result["result"]

    def get_updates(self, offset: int | None = None) -> list[dict]:
        payload = {
            "timeout": POLL_TIMEOUT,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset
        return self._post_json("getUpdates", payload)

    def send_message(
        self, chat_id: int, text: str, reply_markup: dict | None = None
    ) -> dict:
        payload = {
            "chat_id": chat_id,
            "text": text,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self._post_json("sendMessage", payload)

    def answer_callback_query(
        self, callback_query_id: str, text: str | None = None
    ) -> dict:
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        return self._post_json("answerCallbackQuery", payload)

    def send_chat_action(self, chat_id: int, action: str) -> dict:
        return self._post_json("sendChatAction", {"chat_id": chat_id, "action": action})

    def send_document(
        self, chat_id: int, file_path: Path, caption: str | None = None
    ) -> dict:
        with file_path.open("rb") as file_obj:
            files = {
                "document": (
                    file_path.name,
                    file_obj,
                    "application/pdf",
                )
            }
            data = {"chat_id": str(chat_id)}
            if caption:
                data["caption"] = caption
            return self._post_multipart("sendDocument", data=data, files=files)


def confirm_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "Да", "callback_data": "auto_yes"},
                {"text": "Нет", "callback_data": "auto_no"},
            ]
        ]
    }


def is_running(chat_id: int) -> bool:
    with RUNNING_LOCK:
        return chat_id in RUNNING_CHATS


def set_running(chat_id: int, value: bool) -> None:
    with RUNNING_LOCK:
        if value:
            RUNNING_CHATS.add(chat_id)
        else:
            RUNNING_CHATS.discard(chat_id)


def latest_csv() -> Path | None:
    candidates = []
    for pattern in CSV_PATTERNS:
        candidates.extend(SCRIPT_DIR.glob(pattern))
    if not candidates:
        return None
    return sorted(set(candidates), key=lambda path: path.stat().st_mtime, reverse=True)[
        0
    ]


def extract_csv_path(command_output: str) -> Path | None:
    match = PARSER_PATH_RE.search(command_output)
    if not match:
        return None
    return Path(match.group(1).strip()).expanduser().resolve()


def summarize_error(output: str, limit: int = 8) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return "Неизвестная ошибка."
    return "\n".join(lines[-limit:])


def run_script(
    script_path: Path, extra_args: list[str] | None = None
) -> tuple[subprocess.CompletedProcess[str], str]:
    command = [sys.executable, str(script_path)]
    if extra_args:
        command.extend(extra_args)
    logger.debug("Этап 5: запускаю подпроцесс %s.", command)
    process = subprocess.run(
        command,
        cwd=SCRIPT_DIR,
        capture_output=True,
        text=True,
    )
    combined_output = "\n".join(
        part for part in [process.stdout, process.stderr] if part
    )
    return process, combined_output


def ensure_files_exist(paths: list[Path]) -> None:
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise RuntimeError("Не найдены ожидаемые файлы:\n" + "\n".join(missing))


def run_pipeline(bot: TelegramBot, chat_id: int) -> None:
    set_running(chat_id, True)
    try:
        logger.info(
            "Этап 5: подтвержден запуск полной цепочки для chat_id=%s.", chat_id
        )
        bot.send_message(chat_id, "Подтверждение получено. Начинаю парсинг и расчеты.")
        bot.send_chat_action(chat_id, "typing")

        parser_args: list[str] = []
        if AUTO_PAGES.isdigit():
            parser_args.extend(["--pages", AUTO_PAGES])
        if AUTO_HEADFUL:
            parser_args.append("--headful")

        parser_result, parser_output = run_script(PARSER_SCRIPT, parser_args)
        if parser_result.returncode != 0:
            logger.error("Этап 5: этап 1 завершился ошибкой для chat_id=%s.", chat_id)
            bot.send_message(
                chat_id,
                "Парсинг завершился неуспешно.\n" + summarize_error(parser_output),
            )
            return

        csv_path = extract_csv_path(parser_output) or latest_csv()
        if csv_path is None or not csv_path.exists():
            logger.error(
                "Этап 5: после этапа 1 не найден итоговый CSV для chat_id=%s.", chat_id
            )
            bot.send_message(chat_id, "Парсинг завершился, но итоговый CSV не найден.")
            return

        logger.info("Этап 5: этап 1 завершен, найден CSV %s.", csv_path)
        bot.send_message(chat_id, f"Парсинг завершен. Использую файл:\n{csv_path.name}")

        for script_path in [SECOND_TASK_SCRIPT, THIRD_TASK_SCRIPT, FOURTH_TASK_SCRIPT]:
            bot.send_chat_action(chat_id, "typing")
            result, output = run_script(script_path, ["--input", str(csv_path)])
            if result.returncode != 0:
                logger.error(
                    "Этап 5: подпроцесс %s завершился ошибкой для chat_id=%s.",
                    script_path.name,
                    chat_id,
                )
                bot.send_message(
                    chat_id,
                    f"Скрипт `{script_path.name}` завершился с ошибкой.\n{summarize_error(output)}",
                )
                return
            logger.info("Этап 5: подпроцесс %s завершен успешно.", script_path.name)

        second_files = [SECOND_TASK_PDF]
        third_files = [THIRD_TASK_PDF]
        fourth_files = [FOURTH_TASK_PDF]
        ensure_files_exist(second_files + third_files + fourth_files)
        logger.info(
            "Этап 5: все ожидаемые PDF найдены, начинаю отправку в chat_id=%s.", chat_id
        )

        bot.send_message(chat_id, "Готово. Отправляю PDF-результаты по заданиям 2-4.")

        for file_path in second_files:
            bot.send_chat_action(chat_id, "upload_document")
            bot.send_document(chat_id, file_path, caption="Задание 2")
            logger.info("Этап 5: отправлен PDF %s.", file_path.name)

        for file_path in third_files:
            bot.send_chat_action(chat_id, "upload_document")
            bot.send_document(
                chat_id, file_path, caption="Задание 3: единый PDF с графиками"
            )
            logger.info("Этап 5: отправлен единый PDF задания 3: %s.", file_path.name)

        for file_path in fourth_files:
            bot.send_chat_action(chat_id, "upload_document")
            bot.send_document(
                chat_id,
                file_path,
                caption="Задание 4: единый PDF со статистическим анализом",
            )
            logger.info("Этап 5: отправлен единый PDF задания 4: %s.", file_path.name)

        bot.send_message(chat_id, "Все результаты отправлены.")
        logger.info(
            "Этап 5: отправка всех результатов завершена для chat_id=%s.", chat_id
        )
    except Exception as exc:
        logger.critical(
            "Этап 5: pipeline завершился с ошибкой для chat_id=%s: %s",
            chat_id,
            exc,
            exc_info=True,
        )
        bot.send_message(chat_id, f"Во время обработки произошла ошибка: {exc}")
    finally:
        set_running(chat_id, False)


def handle_message(bot: TelegramBot, message: dict) -> None:
    text = (message.get("text") or "").strip()
    chat_id = message["chat"]["id"]
    logger.debug("Этап 5: получено сообщение '%s' от chat_id=%s.", text, chat_id)

    if text != "/auto":
        logger.info(
            "Этап 5: проигнорирована команда '%s' от chat_id=%s, ожидается /auto.",
            text,
            chat_id,
        )
        return

    if is_running(chat_id):
        logger.warning(
            "Этап 5: повторная команда /auto во время активной обработки для chat_id=%s.",
            chat_id,
        )
        bot.send_message(
            chat_id, "Я уже выполняю запрос по команде /auto. Немного подождите."
        )
        return

    logger.info(
        "Этап 5: получена команда /auto, отправляю запрос подтверждения для chat_id=%s.",
        chat_id,
    )
    bot.send_message(chat_id, "Вы уверены?", reply_markup=confirm_keyboard())


def handle_callback(bot: TelegramBot, callback_query: dict) -> None:
    callback_id = callback_query["id"]
    data = callback_query.get("data", "")
    message = callback_query.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    logger.debug("Этап 5: получен callback '%s' от chat_id=%s.", data, chat_id)

    if chat_id is None:
        logger.error("Этап 5: callback без chat_id.")
        bot.answer_callback_query(callback_id, text="Не удалось определить чат.")
        return

    if data == "auto_no":
        logger.info(
            "Этап 5: пользователь отказался от запуска для chat_id=%s.", chat_id
        )
        bot.answer_callback_query(callback_id, text="Остановлено")
        bot.send_message(chat_id, "Хорошо, я дальше спать")
        return

    if data != "auto_yes":
        logger.warning(
            "Этап 5: получен неизвестный callback '%s' для chat_id=%s.", data, chat_id
        )
        bot.answer_callback_query(callback_id)
        return

    if is_running(chat_id):
        logger.warning(
            "Этап 5: пользователь повторно нажал подтверждение во время активной обработки для chat_id=%s.",
            chat_id,
        )
        bot.answer_callback_query(callback_id, text="Я уже работаю над этим запросом.")
        return

    logger.info("Этап 5: пользователь подтвердил запуск для chat_id=%s.", chat_id)
    bot.answer_callback_query(callback_id, text="Запускаю обработку")
    worker = threading.Thread(target=run_pipeline, args=(bot, chat_id), daemon=True)
    worker.start()


def main() -> int:
    emit_level_probe(logger, "Этап 5")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.error("Этап 5: отсутствует переменная окружения TELEGRAM_BOT_TOKEN.")
        raise SystemExit(
            "Не найден TELEGRAM_BOT_TOKEN.\n"
            "Перед запуском задайте переменную окружения, например:\n"
            "export TELEGRAM_BOT_TOKEN='ваш_токен'"
        )

    bot = TelegramBot(token)
    logger.info("Этап 5: бот запущен и начал polling.")

    offset = None
    while True:
        try:
            updates = bot.get_updates(offset=offset)
            for update in updates:
                offset = update["update_id"] + 1
                if "message" in update:
                    handle_message(bot, update["message"])
                elif "callback_query" in update:
                    handle_callback(bot, update["callback_query"])
        except requests.RequestException:
            logger.error(
                "Этап 5: ошибка сетевого polling-запроса к Telegram.", exc_info=True
            )
            time.sleep(3)
        except Exception:
            logger.critical(
                "Этап 5: непредвиденная ошибка в основном цикле бота.", exc_info=True
            )
            time.sleep(3)


if __name__ == "__main__":
    raise SystemExit(main())
