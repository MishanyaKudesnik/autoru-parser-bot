import argparse
import csv
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, urlparse

from bs4 import BeautifulSoup

from logging_utils import emit_level_probe, setup_stage_logger

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError as exc:
    if exc.name == "playwright":
        raise SystemExit(
            "Не найден пакет 'playwright' для текущего интерпретатора Python.\n"
            f"Текущий интерпретатор: {sys.executable}\n"
            "Исправить можно одним из двух способов:\n"
            "1. В VS Code выбрать интерпретатор "
            "'/Users/mischukow1903gmail.com/Documents/anaconda3/bin/python3'.\n"
            "2. Установить зависимости в текущий интерпретатор командами:\n"
            f"   {sys.executable} -m pip install playwright beautifulsoup4\n"
            f"   {sys.executable} -m playwright install chromium"
        )
    raise


BASE_URL = "https://auto.ru/moskva/cars/used/"
CARD_SELECTOR = '[data-seo="listing-item"]'
CAPTCHA_MARKERS = (
    "Вы не робот",
    "captcha",
    "showcaptcha",
    "smartcaptcha",
)
CSV_FIELDS = [
    "марка",
    "цвет",
    "тип",
    "мощность_лс",
    "тип_привода",
    "тип_кузова",
    "пробег_км",
    "год_выпуска",
    "цена_руб",
]
FUEL_TYPES = ("бензин", "дизель", "электро", "гибрид")
TRANSMISSION_KEYWORDS = ("механика", "автомат", "вариатор", "робот", "редуктор")
MARK_SLUG_EXCEPTIONS = {
    "mercedes": "Mercedes-Benz",
    "vw": "Volkswagen",
    "vaz": "LADA",
    "gaz": "ГАЗ",
    "uaz": "УАЗ",
    "tagaz": "ТагАЗ",
    "izh": "ИЖ",
    "zaz": "ЗАЗ",
    "moskvich": "Москвич",
}
SCRIPT_DIR = Path(__file__).resolve().parent
FIRST_TASK_DATA_PREFIX = "первое задание - данные"
logger = setup_stage_logger("этап_1_парсинг")


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def extract_digits(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    return digits


def build_page_url(page_number: int) -> str:
    if page_number <= 1:
        return BASE_URL
    return f"{BASE_URL}?{urlencode({'page': page_number})}"


def normalize_slug(slug: str) -> str:
    return re.sub(r"[^a-zа-я0-9]+", "", slug.lower())


def extract_mark(title: str, href: str) -> str:
    parts = [part for part in urlparse(href).path.split("/") if part]
    slug = ""
    if "sale" in parts:
        sale_index = parts.index("sale")
        if sale_index + 1 < len(parts):
            slug = parts[sale_index + 1]

    if slug in MARK_SLUG_EXCEPTIONS:
        return MARK_SLUG_EXCEPTIONS[slug]

    title_words = title.split()
    slug_norm = normalize_slug(slug)

    if slug_norm and title_words:
        for length in range(1, min(4, len(title_words)) + 1):
            prefix = " ".join(title_words[:length])
            prefix_norm = normalize_slug(prefix)
            if (
                prefix_norm == slug_norm
                or prefix_norm.startswith(slug_norm)
                or slug_norm.startswith(prefix_norm)
            ):
                return prefix

        if "_" in slug:
            return slug.replace("_", " ").title()
        if "-" in slug:
            return slug.replace("-", " ").title()
        if len(slug) <= 3:
            return slug.upper()
        return slug.title()

    return title_words[0] if title_words else ""


def extract_color(subtitle_text: str) -> str:
    text = normalize_space(subtitle_text)
    if "•" in text:
        return normalize_space(text.split("•")[-1])
    return text


def extract_fuel(engine_spec: str) -> str:
    lowered = normalize_space(engine_spec).lower()
    for fuel in FUEL_TYPES:
        if fuel in lowered:
            return fuel
    return ""


def extract_power(engine_spec: str) -> str:
    match = re.search(r"(\d+)\s*л\.с\.", engine_spec.lower())
    return match.group(1) if match else ""


def extract_price(price_text: str) -> str:
    return extract_digits(price_text)


def parse_card(card) -> dict | None:
    title_link = card.select_one(".ListingItemTitle__link")
    if not title_link:
        return None

    href = title_link.get("href", "").strip()
    title = normalize_space(title_link.get_text(" ", strip=True))
    if not href or not title:
        return None

    subtitle = card.select_one('[class*="ListingItemUniversalSpecs__subtitle"]')
    subtitle_text = subtitle.get_text(" ", strip=True) if subtitle else ""

    specs = [
        normalize_space(node.get_text(" ", strip=True))
        for node in card.select(".ListingItemUniversalSpecs__spec-S5lzA")
    ]
    engine_spec = specs[0] if specs else ""
    body_type = ""
    drive_type = ""
    for spec in specs[1:]:
        lowered = spec.lower()
        if "привод" in lowered and not drive_type:
            drive_type = spec
            continue
        if any(keyword in lowered for keyword in TRANSMISSION_KEYWORDS):
            continue
        if not body_type:
            body_type = spec

    condition = card.select_one('div[class^="ListingItemUniversalCondition-"]')
    year = ""
    mileage = ""
    if condition:
        direct_divs = [child for child in condition.find_all("div", recursive=False)]
        if direct_divs:
            year = extract_digits(direct_divs[0].get_text(" ", strip=True))
        status = condition.select_one(
            '[class*="ListingItemUniversalCondition__status"]'
        )
        if status:
            mileage = extract_digits(status.get_text(" ", strip=True))

    price_node = card.select_one('[class*="ListingItemUniversalPrice__title"]')
    price_text = price_node.get_text(" ", strip=True) if price_node else ""

    return {
        "марка": extract_mark(title, href),
        "цвет": extract_color(subtitle_text),
        "тип": extract_fuel(engine_spec),
        "мощность_лс": extract_power(engine_spec),
        "тип_привода": drive_type,
        "тип_кузова": body_type,
        "пробег_км": mileage,
        "год_выпуска": year,
        "цена_руб": extract_price(price_text),
        "_href": href,
    }


def extract_cards_from_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    records = []
    for card in soup.select(CARD_SELECTOR):
        record = parse_card(card)
        if record:
            records.append(record)
    return records


def has_captcha(page) -> bool:
    title = ""
    html = ""
    try:
        title = normalize_space(page.title()).lower()
    except Exception:
        pass

    url = page.url.lower()
    try:
        html = page.content().lower()
    except Exception:
        html = ""
    return any(
        marker.lower() in title or marker.lower() in url or marker.lower() in html
        for marker in CAPTCHA_MARKERS
    )


def safe_page_content(page) -> str:
    try:
        return page.content()
    except PlaywrightError:
        return ""


def wait_for_manual_captcha(page, page_number: int) -> list[dict]:
    logger.warning(
        "Этап 1: на странице %s обнаружена антибот-проверка, ожидается ручное подтверждение.",
        page_number,
    )
    print(
        f"Страница {page_number}: обнаружена антибот-проверка. "
        "Пройдите ее вручную в открывшемся окне браузера. Жду до 180 секунд...",
        file=sys.stderr,
    )

    deadline = time.time() + 180
    while time.time() < deadline:
        html = safe_page_content(page)
        records = extract_cards_from_html(html)
        if records:
            logger.info(
                "Этап 1: антибот-проверка на странице %s успешно пройдена вручную.",
                page_number,
            )
            return records
        page.wait_for_timeout(2000)

    logger.error(
        "Этап 1: антибот-проверка на странице %s не пройдена вовремя.", page_number
    )
    raise RuntimeError(
        f"Антибот-проверка на странице {page_number} не была пройдена вовремя."
    )


def load_page_records(context, url: str, page_number: int, headful: bool) -> list[dict]:
    last_error: Exception | None = None

    for attempt in range(1, 6):
        page = context.new_page()
        logger.debug(
            "Этап 1: загрузка страницы %s, попытка %s, url=%s.",
            page_number,
            attempt,
            url,
        )
        try:
            page.goto(url, wait_until="commit", timeout=30000)
            page.wait_for_timeout(2000)

            deadline = time.time() + 45
            while time.time() < deadline:
                html = safe_page_content(page)
                records = extract_cards_from_html(html)
                if records:
                    logger.info(
                        "Этап 1: страница %s успешно загружена, найдено %s карточек.",
                        page_number,
                        len(records),
                    )
                    return records

                if has_captcha(page):
                    if headful:
                        return wait_for_manual_captcha(page, page_number)
                    logger.warning(
                        "Этап 1: auto.ru показал антибот на странице %s без режима headful.",
                        page_number,
                    )
                    raise RuntimeError(
                        f"auto.ru показал антибот-проверку на странице {page_number}. "
                        "Попробуйте запустить скрипт позже или используйте режим --headful."
                    )

                page.wait_for_timeout(1500)

            raise RuntimeError(
                f"Страница {page_number} загрузилась, но карточки объявлений не появились вовремя."
            )
        except (PlaywrightTimeoutError, RuntimeError) as exc:
            last_error = exc
            logger.warning(
                "Этап 1: страница %s, попытка %s завершилась ошибкой: %s",
                page_number,
                attempt,
                exc,
            )
            print(
                f"Страница {page_number}, попытка {attempt}: {exc}",
                file=sys.stderr,
            )
            time.sleep(min(2 * attempt, 6))
        finally:
            page.close()

    logger.error("Этап 1: страница %s не загружена после всех попыток.", page_number)
    raise RuntimeError(f"Не удалось загрузить страницу {page_number}: {last_error}")


def scrape_pages(pages: int, delay: float, headful: bool) -> list[dict]:
    results: list[dict] = []
    seen_urls: set[str] = set()
    skipped_pages: list[int] = []

    logger.info(
        "Этап 1: запуск парсинга. pages=%s, delay=%s, headful=%s.",
        pages,
        delay,
        headful,
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=not headful,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 2200},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            locale="ru-RU",
        )
        context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            """
        )

        for page_number in range(1, pages + 1):
            url = build_page_url(page_number)
            logger.debug("Этап 1: начинаю обработку страницы %s.", page_number)
            print(f"Загружаю страницу {page_number}: {url}", file=sys.stderr)

            try:
                page_records = load_page_records(
                    context, url, page_number, headful=headful
                )
            except RuntimeError as exc:
                skipped_pages.append(page_number)
                logger.warning(
                    "Этап 1: страница %s пропущена. Причина: %s", page_number, exc
                )
                print(f"Страница {page_number} пропущена: {exc}", file=sys.stderr)
                time.sleep(delay)
                continue

            fresh_records = 0

            for record in page_records:
                href = record.pop("_href")
                if href in seen_urls:
                    continue
                seen_urls.add(href)
                results.append(record)
                fresh_records += 1

            logger.info(
                "Этап 1: страница %s обработана. Найдено %s карточек, добавлено %s новых записей.",
                page_number,
                len(page_records),
                fresh_records,
            )
            print(
                f"Страница {page_number}: найдено {len(page_records)} карточек, добавлено {fresh_records}",
                file=sys.stderr,
            )
            time.sleep(delay)

        browser.close()

    if skipped_pages:
        logger.warning(
            "Этап 1: не удалось обработать страницы: %s.",
            ", ".join(str(page_number) for page_number in skipped_pages),
        )
        print(
            "Предупреждение: не удалось обработать страницы "
            + ", ".join(str(page_number) for page_number in skipped_pages),
            file=sys.stderr,
        )

    if not results:
        logger.critical("Этап 1: парсинг завершился без единой собранной записи.")
        raise RuntimeError("Не удалось собрать ни одной записи.")

    logger.info("Этап 1: парсинг завершен, всего собрано %s записей.", len(results))
    return results


def build_default_output_path() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return SCRIPT_DIR / f"{FIRST_TASK_DATA_PREFIX} {timestamp}.csv"


def make_unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix or ".csv"
    counter = 1
    while True:
        candidate = path.with_name(f"{stem}_{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def save_csv(records: list[dict], output_path: Path) -> Path:
    output_path = make_unique_path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS, delimiter=";")
        writer.writeheader()
        writer.writerows(records)
    logger.info("Этап 1: CSV сохранен в %s.", output_path)
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Собирает данные об автомобилях с auto.ru и сохраняет их в CSV."
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=5,
        help="Сколько страниц результатов обработать. По умолчанию: 5.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Пауза между страницами в секундах. По умолчанию: 2.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Путь к итоговому CSV-файлу. Если не указан, рядом со скриптом будет создан новый CSV с текущей датой и временем.",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Открывать реальное окно Chromium. Полезно, если auto.ru показывает антибот-проверку.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    emit_level_probe(logger, "Этап 1")

    if args.pages < 1:
        logger.error("Этап 1: получено некорректное значение --pages=%s.", args.pages)
        raise SystemExit("Параметр --pages должен быть не меньше 1.")

    output_path = args.output if args.output else build_default_output_path()
    logger.info("Этап 1: итоговый CSV будет сохранен по пути %s.", output_path)
    records = scrape_pages(pages=args.pages, delay=args.delay, headful=args.headful)
    try:
        saved_path = save_csv(records, output_path)
    except OSError as exc:
        fallback_path = build_default_output_path()
        logger.error(
            "Этап 1: не удалось сохранить CSV по пути %s. Использую резервный путь %s. Причина: %s",
            output_path,
            fallback_path,
            exc,
        )
        saved_path = save_csv(records, fallback_path)
        print(
            f"Не удалось сохранить файл по пути '{output_path}'. "
            f"Сохранил в '{saved_path}'. Причина: {exc}",
            file=sys.stderr,
        )

    logger.info("Этап 1: работа завершена успешно, сохранено %s записей.", len(records))
    print(f"Сохранено {len(records)} записей в {saved_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        logger.critical(
            "Этап 1: скрипт завершился без сохранения данных. Причина: %s",
            exc,
            exc_info=True,
        )
        print(f"Скрипт завершился без сохранения данных: {exc}", file=sys.stderr)
        raise SystemExit(1)
