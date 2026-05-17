import argparse
import os
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
import seaborn as sns


CSV_PATTERNS = (
    "первое задание - данные*.csv",
    "auto_ru_used_moscow*.csv",
)
NUMERIC_COLUMNS = ["мощность_лс", "пробег_км", "год_выпуска", "цена_руб"]
THIRD_TASK_DIRNAME = "третье задание - результаты"
THIRD_TASK_REPORT_NAME = "третье задание - графики.pdf"
THIRD_TASK_ARCHIVE_DIRNAME = "_архив старых раздельных pdf"
THIRD_TASK_LEGACY_REPORTS = [
    "третье задание 1 пункт - круговая диаграмма распределения автомобилей по типу кузова.pdf",
    "третье задание 2 пункт - точечная диаграмма рассеяния цены по году выпуска.pdf",
    "третье задание 3 пункт - график-скрипка разброса цены по всем автомобилям.pdf",
    "третье задание 4 пункт - многослойная гистограмма распределения автомобилей по типу двигателя со слоями - приводом.pdf",
]
logger = setup_stage_logger("этап_3_графики")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Строит графики для третьего задания и сохраняет их в один PDF."
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
    logger.debug("Этап 3: загружаю CSV %s.", csv_path)
    df = pd.read_csv(csv_path, sep=";", encoding="utf-8-sig")
    for column in NUMERIC_COLUMNS:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    for column in ["тип", "тип_привода", "тип_кузова"]:
        df[column] = df[column].astype("string").str.strip()
    logger.info("Этап 3: CSV загружен, строк=%s.", len(df))
    return df


def archive_legacy_reports(output_dir: Path) -> None:
    archive_dir = output_dir / THIRD_TASK_ARCHIVE_DIRNAME
    moved_files = []
    for file_name in THIRD_TASK_LEGACY_REPORTS:
        legacy_path = output_dir / file_name
        if not legacy_path.exists():
            continue
        archive_dir.mkdir(parents=True, exist_ok=True)
        target_path = archive_dir / legacy_path.name
        if target_path.exists():
            target_path.unlink()
        legacy_path.rename(target_path)
        moved_files.append(target_path.name)

    if moved_files:
        logger.info(
            "Этап 3: старые раздельные PDF перенесены в архив: %s.",
            ", ".join(moved_files),
        )


def add_cover_page(pdf: PdfPages, csv_path: Path, row_count: int) -> None:
    logger.info("Этап 3: добавляю титульную страницу единого PDF-отчета.")
    fig = plt.figure(figsize=(8.27, 11.69))
    fig.patch.set_facecolor("white")
    fig.text(
        0.08, 0.94, "Третье задание. Графики", fontsize=18, fontweight="bold", va="top"
    )
    fig.text(0.08, 0.88, f"Исходный файл: {csv_path.name}", fontsize=12, va="top")
    fig.text(0.08, 0.84, f"Количество объявлений: {row_count}", fontsize=12, va="top")
    fig.text(
        0.08, 0.78, "В состав отчета входят:", fontsize=13, fontweight="bold", va="top"
    )
    fig.text(
        0.10,
        0.73,
        "1. Круговая диаграмма распределения автомобилей по типу кузова",
        fontsize=12,
        va="top",
    )
    fig.text(
        0.10,
        0.68,
        "2. Точечная диаграмма рассеяния цены по году выпуска",
        fontsize=12,
        va="top",
    )
    fig.text(
        0.10,
        0.63,
        "3. График-скрипка разброса цены по всем автомобилям",
        fontsize=12,
        va="top",
    )
    fig.text(
        0.10,
        0.58,
        "4. Многослойная гистограмма распределения автомобилей по типу двигателя со слоями привода",
        fontsize=12,
        va="top",
    )
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def add_body_type_pie_page(pdf: PdfPages, df: pd.DataFrame) -> None:
    logger.info("Этап 3, подпункт 1: строю круговую диаграмму по типу кузова.")
    counts = df["тип_кузова"].fillna("Не указано").value_counts()
    fig, ax = plt.subplots(figsize=(10, 10))
    ax.pie(counts.values, labels=counts.index, autopct="%1.1f%%", startangle=140)
    ax.set_title("Распределение автомобилей по типу кузова")
    fig.tight_layout()
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)
    logger.info("Этап 3, подпункт 1: страница добавлена в единый PDF.")


def add_price_year_scatter_page(pdf: PdfPages, df: pd.DataFrame) -> None:
    logger.info("Этап 3, подпункт 2: строю точечную диаграмму цены по году выпуска.")
    scatter_df = df.dropna(subset=["год_выпуска", "цена_руб"]).copy()
    scatter_df["тип"] = scatter_df["тип"].fillna("Не указано")
    fig, ax = plt.subplots(figsize=(11, 6))
    sns.scatterplot(
        data=scatter_df,
        x="год_выпуска",
        y="цена_руб",
        hue="тип",
        alpha=0.8,
        s=70,
        ax=ax,
    )
    ax.set_title("Цена по году выпуска")
    ax.set_xlabel("Год выпуска")
    ax.set_ylabel("Цена, руб.")
    legend = ax.get_legend()
    if legend is not None:
        legend.set_title("Тип двигателя")
    fig.tight_layout()
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)
    logger.info("Этап 3, подпункт 2: страница добавлена в единый PDF.")


def add_price_violin_page(pdf: PdfPages, df: pd.DataFrame) -> None:
    logger.info("Этап 3, подпункт 3: строю график-скрипку цены.")
    violin_df = df.dropna(subset=["цена_руб"]).copy()
    violin_df["выборка"] = "Все автомобили"
    fig, ax = plt.subplots(figsize=(7, 6))
    sns.violinplot(
        data=violin_df,
        x="выборка",
        y="цена_руб",
        inner="box",
        cut=0,
        color="#6baed6",
        ax=ax,
    )
    ax.set_title("Разброс цены по всем автомобилям")
    ax.set_xlabel("")
    ax.set_ylabel("Цена, руб.")
    fig.tight_layout()
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)
    logger.info("Этап 3, подпункт 3: страница добавлена в единый PDF.")


def add_engine_drive_hist_page(pdf: PdfPages, df: pd.DataFrame) -> None:
    logger.info(
        "Этап 3, подпункт 4: строю многослойную гистограмму двигателя и привода."
    )
    hist_df = df.copy()
    hist_df["тип"] = hist_df["тип"].fillna("Не указано")
    hist_df["тип_привода"] = hist_df["тип_привода"].fillna("Не указано")
    fig, ax = plt.subplots(figsize=(11, 6))
    sns.histplot(
        data=hist_df,
        x="тип",
        hue="тип_привода",
        multiple="stack",
        discrete=True,
        shrink=0.85,
        ax=ax,
    )
    ax.set_title("Распределение автомобилей по типу двигателя со слоями привода")
    ax.set_xlabel("Тип двигателя")
    ax.set_ylabel("Количество автомобилей")
    legend = ax.get_legend()
    if legend is not None:
        legend.set_title("Тип привода")
    fig.tight_layout()
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)
    logger.info("Этап 3, подпункт 4: страница добавлена в единый PDF.")


def save_combined_pdf(report_path: Path, csv_path: Path, df: pd.DataFrame) -> Path:
    with PdfPages(report_path) as pdf:
        add_cover_page(pdf, csv_path, len(df))
        add_body_type_pie_page(pdf, df)
        add_price_year_scatter_page(pdf, df)
        add_price_violin_page(pdf, df)
        add_engine_drive_hist_page(pdf, df)
    logger.info("Этап 3: единый PDF-файл сохранен в %s.", report_path)
    return report_path


def main() -> int:
    args = parse_args()
    emit_level_probe(logger, "Этап 3")
    csv_path = args.input.resolve() if args.input else find_latest_csv()
    if not csv_path.exists():
        logger.error("Этап 3: входной CSV не найден: %s", csv_path)
        raise SystemExit(f"Файл не найден: {csv_path}")

    sns.set_theme(style="whitegrid")
    plt.rcParams["font.family"] = "DejaVu Sans"

    df = load_dataframe(csv_path)
    output_dir = csv_path.parent / THIRD_TASK_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Этап 3: результаты будут сохранены в %s.", output_dir)
    archive_legacy_reports(output_dir)

    report_path = output_dir / THIRD_TASK_REPORT_NAME
    save_combined_pdf(report_path, csv_path, df)

    print(f"Исходный файл: {csv_path}")
    print(f"PDF-отчет: {report_path}")
    logger.info("Этап 3: все графики успешно построены и собраны в один PDF.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        logger.critical("Этап 3: скрипт завершился с ошибкой: %s", exc, exc_info=True)
        print(f"Ошибка третьего задания: {exc}")
        raise SystemExit(1)
