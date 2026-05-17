import argparse
import os
import textwrap
from pathlib import Path

from logging_utils import emit_level_probe, setup_stage_logger

SCRIPT_DIR = Path(__file__).resolve().parent
MPLCONFIGDIR = SCRIPT_DIR / ".matplotlib"
MPLCONFIGDIR.mkdir(parents=True, exist_ok=True)
os.environ["MPLCONFIGDIR"] = str(MPLCONFIGDIR)

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import pandas as pd


CSV_PATTERNS = (
    "первое задание - данные*.csv",
    "auto_ru_used_moscow*.csv",
)
NUMERIC_COLUMNS = ["мощность_лс", "пробег_км", "год_выпуска", "цена_руб"]
SECOND_TASK_DIRNAME = "второе задание - результаты"
SECOND_TASK_REPORT_NAME = "второе задание - расчеты.pdf"
logger = setup_stage_logger("этап_2_расчеты")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Считает результаты для второго задания и сохраняет их в PDF."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Путь к CSV. Если не указан, будет взят самый свежий CSV рядом со скриптом.",
    )
    return parser.parse_args()


def find_latest_csv() -> Path:
    files = []
    for pattern in CSV_PATTERNS:
        files.extend(SCRIPT_DIR.glob(pattern))
    files = sorted(set(files), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        raise SystemExit("Не найдено CSV с данными первого задания")
    return files[0]


def load_dataframe(csv_path: Path) -> pd.DataFrame:
    logger.debug("Этап 2: загружаю CSV %s.", csv_path)
    df = pd.read_csv(csv_path, sep=";", encoding="utf-8-sig")
    for column in NUMERIC_COLUMNS:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    logger.info("Этап 2: CSV загружен, строк=%s.", len(df))
    return df


def format_int(value: float | int) -> str:
    return f"{int(round(value)):,}".replace(",", " ")


def calculate_metrics(df: pd.DataFrame) -> dict:
    logger.info("Этап 2, подпункт 1: рассчитываю топ-3 самых дешевых седанов.")
    sedans = (
        df[df["тип_кузова"].astype("string").str.lower() == "седан"]
        .nsmallest(3, "цена_руб")[
            [
                "марка",
                "цвет",
                "тип",
                "тип_привода",
                "пробег_км",
                "год_выпуска",
                "цена_руб",
            ]
        ]
        .copy()
    )
    logger.info("Этап 2, подпункт 1: найдено %s строк в результате.", len(sedans))

    logger.info("Этап 2, подпункт 2: рассчитываю топ-3 самых частых типов кузова.")
    body_type_top3 = df["тип_кузова"].value_counts().head(3)

    logger.info(
        "Этап 2, подпункт 3: считаю бензиновые автомобили с пробегом меньше 60 000 км."
    )
    gasoline_under_60k = int(
        ((df["тип"] == "бензин") & (df["пробег_км"] < 60000)).sum()
    )

    logger.info("Этап 2, подпункт 4: считаю моду, медиану, среднее и дисперсию цены.")
    prices = df["цена_руб"].dropna()

    return {
        "row_count": len(df),
        "top3_cheapest_sedans": sedans,
        "top3_body_types": body_type_top3,
        "gasoline_under_60k": gasoline_under_60k,
        "price_mode": sorted(prices.mode().astype(int).tolist()),
        "price_median": float(prices.median()),
        "price_mean": float(prices.mean()),
        "price_variance": float(prices.var(ddof=0)),
    }


def save_text_pdf(path: Path, title: str, sections: list[str]) -> Path:
    plt.rcParams["font.family"] = "DejaVu Sans"
    line_height = 0.032
    top_margin = 0.95
    bottom_margin = 0.06
    fig = None
    y = None

    def new_page():
        nonlocal fig, y
        if fig is not None:
            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.patch.set_facecolor("white")
        fig.text(0.07, 0.97, title, fontsize=15, fontweight="bold", va="top")
        y = top_margin

    with PdfPages(path) as pdf:
        new_page()
        for section in sections:
            if not section:
                y -= line_height
                continue

            wrapped_lines = []
            for raw_line in section.splitlines():
                if not raw_line.strip():
                    wrapped_lines.append("")
                    continue
                indent = "   " if raw_line.startswith("- ") else ""
                width = 84 if not indent else 80
                content = raw_line[2:] if indent else raw_line
                pieces = textwrap.wrap(content, width=width) or [""]
                wrapped_lines.extend(
                    [
                        f"{'- ' if i == 0 and indent else indent}{piece}"
                        for i, piece in enumerate(pieces)
                    ]
                )

            needed_height = max(len(wrapped_lines), 1) * line_height + 0.01
            if y - needed_height < bottom_margin:
                new_page()

            for line in wrapped_lines:
                fig.text(0.07, y, line, fontsize=11, va="top")
                y -= line_height
            y -= 0.01

        if fig is not None:
            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)

    return path


def build_sections(csv_path: Path, metrics: dict) -> list[str]:
    sections = [
        f"Исходный файл: {csv_path.name}",
        f"Количество объявлений в выборке: {metrics['row_count']}",
        "",
        "1. Топ-3 самых дешевых седана с ценой",
    ]

    for _, row in metrics["top3_cheapest_sedans"].iterrows():
        sections.append(
            f"- {row['марка']}, {row['цвет']}, {row['тип']}, {row['тип_привода']}, "
            f"пробег {int(row['пробег_км'])} км, год {int(row['год_выпуска'])}, цена {format_int(row['цена_руб'])} руб."
        )

    sections.extend(
        [
            "",
            "2. Топ-3 самых частых типов кузова",
        ]
    )
    for body_type, count in metrics["top3_body_types"].items():
        sections.append(f"- {body_type}: {count}")

    sections.extend(
        [
            "",
            "3. Количество автомобилей на бензине с пробегом меньше 60 000 км",
            f"- {metrics['gasoline_under_60k']}",
            "",
            "4. Мода, медиана, среднее и дисперсия для цены",
            f"- Мода: {', '.join(format_int(value) for value in metrics['price_mode'])} руб.",
            f"- Медиана: {format_int(metrics['price_median'])} руб.",
            f"- Среднее: {format_int(metrics['price_mean'])} руб.",
            f"- Дисперсия: {format_int(metrics['price_variance'])}",
        ]
    )
    return sections


def main() -> int:
    args = parse_args()
    emit_level_probe(logger, "Этап 2")
    csv_path = args.input.resolve() if args.input else find_latest_csv()
    if not csv_path.exists():
        logger.error("Этап 2: входной CSV не найден: %s", csv_path)
        raise SystemExit(f"Файл не найден: {csv_path}")

    df = load_dataframe(csv_path)
    metrics = calculate_metrics(df)

    output_dir = csv_path.parent / SECOND_TASK_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / SECOND_TASK_REPORT_NAME
    logger.info("Этап 2: сохраняю PDF-отчет в %s.", report_path)
    save_text_pdf(
        report_path, "Второе задание. Расчеты", build_sections(csv_path, metrics)
    )
    logger.info("Этап 2: PDF-отчет успешно сохранен.")

    print(f"Исходный файл: {csv_path}")
    print(f"PDF-отчет: {report_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        logger.critical("Этап 2: скрипт завершился с ошибкой: %s", exc, exc_info=True)
        print(f"Ошибка второго задания: {exc}")
        raise SystemExit(1)
