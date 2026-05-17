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
import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency, f as f_dist, pearsonr, ttest_ind


CSV_PATTERNS = (
    "первое задание - данные*.csv",
    "auto_ru_used_moscow*.csv",
)
NUMERIC_COLUMNS = ["цена_руб", "мощность_лс", "пробег_км", "год_выпуска"]
FOURTH_TASK_DIRNAME = "четвертое задание - результаты"
FOURTH_TASK_REPORT_NAME = "четвертое задание - статистика.pdf"
FOURTH_TASK_ARCHIVE_DIRNAME = "_архив старых раздельных pdf"
FOURTH_TASK_LEGACY_REPORTS = [
    "четвертое задание - общий отчет.pdf",
    "четвертое задание 1 пункт - хи-тест цены и типа кузова.pdf",
    "четвертое задание 2 пункт - t-тест черного и серого цвета.pdf",
    "четвертое задание 3 пункт - ANOVA по типу двигателя.pdf",
    "четвертое задание 4 пункт - корреляция цены и мощности.pdf",
]
logger = setup_stage_logger("этап_4_статистика")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Считает статистические тесты для четвертого задания и сохраняет их в один PDF."
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
    logger.debug("Этап 4: загружаю CSV %s.", csv_path)
    df = pd.read_csv(csv_path, sep=";", encoding="utf-8-sig")
    for column in NUMERIC_COLUMNS:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    for column in ["цвет", "тип", "тип_кузова"]:
        df[column] = df[column].astype("string").str.strip()
    logger.info("Этап 4: CSV загружен, строк=%s.", len(df))
    return df


def archive_legacy_reports(output_dir: Path) -> None:
    archive_dir = output_dir / FOURTH_TASK_ARCHIVE_DIRNAME
    moved_files = []
    for file_name in FOURTH_TASK_LEGACY_REPORTS:
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
            "Этап 4: старые раздельные PDF перенесены в архив: %s.",
            ", ".join(moved_files),
        )


def format_int(value: float | int) -> str:
    return f"{int(round(value)):,}".replace(",", " ")


def describe_cramers_v(value: float) -> str:
    if value < 0.10:
        return "практически отсутствующая"
    if value < 0.30:
        return "слабая"
    if value < 0.50:
        return "умеренная"
    return "достаточно сильная"


def describe_cohens_d(value: float) -> str:
    absolute = abs(value)
    if absolute < 0.20:
        return "пренебрежимо малый"
    if absolute < 0.50:
        return "малый"
    if absolute < 0.80:
        return "средний"
    return "крупный"


def describe_eta_squared(value: float) -> str:
    if value < 0.01:
        return "практически отсутствующий"
    if value < 0.06:
        return "малый"
    if value < 0.14:
        return "средний"
    return "крупный"


def describe_correlation_strength(value: float) -> str:
    absolute = abs(value)
    if absolute < 0.30:
        return "слабая"
    if absolute < 0.50:
        return "умеренная"
    if absolute < 0.70:
        return "заметная"
    return "сильная"


def normalize_color(value: str) -> str:
    return str(value).strip().lower().replace("ё", "е")


def chi_square_body_price(df: pd.DataFrame) -> dict:
    logger.info("Этап 4, подпункт 1: выполняю хи-тест связи цены и типа кузова.")

    body_grouped = df["тип_кузова"].where(
        df["тип_кузова"].isin(["Внедорожник 5 дв.", "Седан"]),
        "Прочее",
    )
    price_group = pd.qcut(
        df["цена_руб"],
        q=3,
        labels=["Низкая цена", "Средняя цена", "Высокая цена"],
        duplicates="drop",
    )
    analysis_df = pd.DataFrame(
        {"тип_кузова": body_grouped, "ценовая_категория": price_group}
    ).dropna()
    table = pd.crosstab(analysis_df["тип_кузова"], analysis_df["ценовая_категория"])
    chi2, p_value, dof, expected = chi2_contingency(table)
    n = table.to_numpy().sum()
    rows, cols = table.shape
    cramers_v = float(np.sqrt(chi2 / (n * min(rows - 1, cols - 1))))
    row_percent = table.div(table.sum(axis=1), axis=0) * 100

    dominant_patterns = []
    for body_type in table.index:
        dominant_category = row_percent.loc[body_type].idxmax()
        dominant_share = row_percent.loc[body_type].max()
        dominant_patterns.append(
            f"Для группы '{body_type}' чаще всего встречается категория '{dominant_category}' ({dominant_share:.1f}%)."
        )

    return {
        "table": table,
        "chi2": float(chi2),
        "p_value": float(p_value),
        "dof": int(dof),
        "cramers_v": cramers_v,
        "min_expected": float(expected.min()),
        "row_count": int(n),
        "dominant_patterns": dominant_patterns,
    }


def welch_t_black_gray(df: pd.DataFrame) -> dict:
    logger.info("Этап 4, подпункт 2: выполняю t-тест для черных и серых автомобилей.")

    normalized_color = df["цвет"].fillna("").map(normalize_color)
    black = df.loc[normalized_color == "черный", "цена_руб"].dropna()
    gray = df.loc[normalized_color == "серый", "цена_руб"].dropna()

    if len(black) < 2 or len(gray) < 2:
        raise RuntimeError(
            "Для t-теста недостаточно наблюдений по черным или серым автомобилям."
        )

    t_stat, p_value = ttest_ind(black, gray, equal_var=False)

    var_black = black.var(ddof=1)
    var_gray = gray.var(ddof=1)
    welch_df = (var_black / len(black) + var_gray / len(gray)) ** 2 / (
        ((var_black / len(black)) ** 2) / (len(black) - 1)
        + ((var_gray / len(gray)) ** 2) / (len(gray) - 1)
    )
    pooled_sd = np.sqrt(
        (((len(black) - 1) * var_black) + ((len(gray) - 1) * var_gray))
        / (len(black) + len(gray) - 2)
    )
    cohens_d = float((black.mean() - gray.mean()) / pooled_sd)
    mean_diff = float(black.mean() - gray.mean())
    relative_diff = float((mean_diff / gray.mean()) * 100) if gray.mean() else 0.0

    return {
        "n_black": int(len(black)),
        "n_gray": int(len(gray)),
        "mean_black": float(black.mean()),
        "mean_gray": float(gray.mean()),
        "median_black": float(black.median()),
        "median_gray": float(gray.median()),
        "t_stat": float(t_stat),
        "p_value": float(p_value),
        "df": float(welch_df),
        "cohens_d": cohens_d,
        "mean_diff": mean_diff,
        "relative_diff": relative_diff,
    }


def welch_anova_engine(df: pd.DataFrame) -> dict:
    logger.info("Этап 4, подпункт 3: выполняю ANOVA по типу двигателя.")

    groups: dict[str, np.ndarray] = {}
    excluded_groups: list[str] = []
    for name, group in df.groupby("тип", dropna=True):
        values = group["цена_руб"].dropna().to_numpy()
        if len(values) < 2:
            excluded_groups.append(f"{name}: меньше двух наблюдений")
            continue
        if np.isclose(np.var(values, ddof=1), 0):
            excluded_groups.append(f"{name}: нулевая дисперсия")
            continue
        groups[str(name)] = values

    if len(groups) < 2:
        raise RuntimeError("Для ANOVA недостаточно групп с вариативными данными.")

    samples = list(groups.values())
    n = np.array([len(sample) for sample in samples], dtype=float)
    means = np.array([np.mean(sample) for sample in samples], dtype=float)
    variances = np.array([np.var(sample, ddof=1) for sample in samples], dtype=float)

    weights = n / variances
    weight_sum = weights.sum()
    weighted_mean = np.sum(weights * means) / weight_sum
    ss_between_adj = np.sum(weights * (means - weighted_mean) ** 2)
    df_num = float(len(samples) - 1)
    ms_between_adj = ss_between_adj / df_num
    lambda_term = (
        3
        * np.sum((1 / (n - 1)) * (1 - (weights / weight_sum)) ** 2)
        / ((len(samples) ** 2) - 1)
    )
    df_den = float(1 / lambda_term)
    statistic = float(ms_between_adj / (1 + (2 * lambda_term * (len(samples) - 2)) / 3))
    p_value = float(f_dist.sf(statistic, df_num, df_den))

    valid_df = df[df["тип"].isin(groups.keys())].copy()
    overall = valid_df["цена_руб"].mean()
    group_means = valid_df.groupby("тип")["цена_руб"].mean()
    ss_between = sum(
        len(valid_df[valid_df["тип"] == name]) * (mean - overall) ** 2
        for name, mean in group_means.items()
    )
    ss_total = ((valid_df["цена_руб"] - overall) ** 2).sum()
    eta_squared = float(ss_between / ss_total) if ss_total else 0.0

    summary = {}
    for name, values in groups.items():
        summary[name] = {
            "n": int(len(values)),
            "mean": float(np.mean(values)),
            "median": float(np.median(values)),
        }

    highest_group = max(summary.items(), key=lambda item: item[1]["mean"])
    lowest_group = min(summary.items(), key=lambda item: item[1]["mean"])
    mean_gap = float(highest_group[1]["mean"] - lowest_group[1]["mean"])

    return {
        "groups": summary,
        "excluded_groups": excluded_groups,
        "statistic": statistic,
        "p_value": p_value,
        "df_num": df_num,
        "df_den": df_den,
        "eta_squared": eta_squared,
        "highest_group": highest_group,
        "lowest_group": lowest_group,
        "mean_gap": mean_gap,
    }


def correlation_price_power(df: pd.DataFrame) -> dict:
    logger.info("Этап 4, подпункт 4: выполняю корреляционный анализ цены и мощности.")

    corr_df = df[["цена_руб", "мощность_лс"]].dropna()
    if len(corr_df) < 3:
        raise RuntimeError("Для корреляционного анализа недостаточно наблюдений.")

    r_value, p_value = pearsonr(corr_df["цена_руб"], corr_df["мощность_лс"])
    return {
        "n": int(len(corr_df)),
        "r_value": float(r_value),
        "p_value": float(p_value),
        "r_squared": float(r_value**2),
    }


def save_text_pdf(path: Path, title: str, sections: list[str]) -> Path:
    plt.rcParams["font.family"] = "DejaVu Sans"
    line_height = 0.032
    top_margin = 0.95
    bottom_margin = 0.06
    fig = None
    y = None

    def new_page() -> None:
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


def build_sections(
    csv_path: Path, df: pd.DataFrame, chi: dict, ttest: dict, anova: dict, corr: dict
) -> list[str]:
    chi_strength = describe_cramers_v(chi["cramers_v"])
    t_effect = describe_cohens_d(ttest["cohens_d"])
    anova_effect = describe_eta_squared(anova["eta_squared"])
    corr_strength = describe_correlation_strength(corr["r_value"])
    mean_diff_abs = abs(ttest["mean_diff"])
    more_expensive_color = "черные" if ttest["mean_diff"] > 0 else "серые"
    highest_engine, highest_info = anova["highest_group"]
    lowest_engine, lowest_info = anova["lowest_group"]
    corr_direction = "положительная" if corr["r_value"] >= 0 else "отрицательная"
    chi_significant = chi["p_value"] < 0.05
    t_significant = ttest["p_value"] < 0.05
    anova_significant = anova["p_value"] < 0.05
    corr_significant = corr["p_value"] < 0.05

    sections = [
        "Четвертое задание. Статистический анализ",
        f"Исходный файл: {csv_path.name}",
        f"Объем выборки: {len(df)} объявлений.",
        "",
        "Кратко для заказчика",
        f"- Связь между ценой и типом кузова {'подтверждена' if chi_significant else 'не подтверждена'}; сила связи {chi_strength}.",
        f"- Различие цен черных и серых автомобилей {'подтверждено' if t_significant else 'не подтверждено'}; эффект {t_effect}.",
        f"- Различия цен по типу двигателя {'подтверждены' if anova_significant else 'не подтверждены'}; размер эффекта {anova_effect}.",
        f"- Связь цены и мощности {'подтверждена' if corr_significant else 'не подтверждена'}; она {corr_direction} и {corr_strength}.",
        "",
        "1. Хи-тест на наличие связи между ценой и типом кузова",
        "Что проверяли",
        "- Нулевая гипотеза H0: ценовая категория автомобиля не связана с типом кузова.",
        "- Альтернативная гипотеза H1: между ценовой категорией и типом кузова есть связь.",
        "- Для применения χ² цену разделили на три категории: низкая, средняя и высокая.",
        "",
        "Статистический вывод",
        f"- χ²({chi['dof']}) = {chi['chi2']:.3f}, p = {chi['p_value']:.4f}.",
        f"- V Крамера = {chi['cramers_v']:.3f}, то есть связь {chi_strength}.",
        f"- Минимальная ожидаемая частота = {chi['min_expected']:.2f}; тест применим к этой таблице сопряженности.",
        (
            "- Значение p меньше 0.05, поэтому вероятность получить такое распределение случайно невелика."
            if chi_significant
            else "- Значение p больше 0.05, поэтому наблюдаемое распределение можно объяснить случайными колебаниями выборки."
        ),
        "",
        "Содержательный вывод",
        (
            "- На уровне значимости 0.05 цена и тип кузова связаны статистически значимо."
            if chi_significant
            else "- На уровне значимости 0.05 убедительной связи между ценой и типом кузова не найдено."
        ),
        (
            "- Для заказчика это означает, что тип кузова можно использовать как дополнительный признак ценового сегмента, но не как самостоятельный и главный фактор."
            if chi_significant
            else "- Для заказчика это означает, что по текущей выборке тип кузова не дает надежного самостоятельного объяснения цены."
        ),
        (
            "- Сила связи слабая, поэтому на цену одновременно заметно влияют и другие характеристики: марка, возраст, мощность и пробег."
            if chi["cramers_v"] < 0.30
            else "- Сила связи уже заметна не только статистически, но и практически."
        ),
        *[f"- {pattern}" for pattern in chi["dominant_patterns"]],
        "",
        "2. t-тест для выборок цен автомобилей черного и серого цветов",
        "Что проверяли",
        "- Нулевая гипотеза H0: средняя цена черных и серых автомобилей одинакова.",
        "- Альтернативная гипотеза H1: средние цены различаются.",
        "- Использован Welch t-test, потому что размеры групп и разброс цен могут отличаться.",
        "",
        "Статистический вывод",
        f"- Черные автомобили: n = {ttest['n_black']}, средняя цена = {format_int(ttest['mean_black'])} руб., медиана = {format_int(ttest['median_black'])} руб.",
        f"- Серые автомобили: n = {ttest['n_gray']}, средняя цена = {format_int(ttest['mean_gray'])} руб., медиана = {format_int(ttest['median_gray'])} руб.",
        f"- t = {ttest['t_stat']:.3f}, df = {ttest['df']:.2f}, p = {ttest['p_value']:.4f}.",
        f"- Cohen's d = {ttest['cohens_d']:.3f}, то есть эффект {t_effect}.",
        f"- Разница средних составляет около {format_int(mean_diff_abs)} руб. ({abs(ttest['relative_diff']):.1f}% относительно средней цены серых автомобилей).",
        (
            "- Значение p меньше 0.05, поэтому различие средних статистически подтверждается."
            if t_significant
            else "- Значение p больше 0.05, поэтому наблюдаемую разницу средних нельзя считать надежно подтвержденной."
        ),
        "",
        "Содержательный вывод",
        (
            f"- На уровне значимости 0.05 различие между ценами черных и серых автомобилей статистически значимо: в среднем {more_expensive_color} автомобили дороже."
            if t_significant
            else "- На уровне значимости 0.05 статистически значимого различия между ценами черных и серых автомобилей не найдено."
        ),
        (
            "- Для заказчика это означает, что цвет кузова не стоит использовать как самостоятельный фактор ценообразования."
            if not t_significant
            else "- Для заказчика это означает, что различие по цвету есть, но его нельзя трактовать как прямое влияние цвета на цену без учета марки, комплектации и сегмента."
        ),
        (
            f"- Эффект {t_effect}, поэтому даже разница в рублях может быть практически слабой."
            if abs(ttest["cohens_d"]) < 0.50
            else f"- Эффект {t_effect}, поэтому различие имеет и практический смысл."
        ),
        "",
        "3. ANOVA для цен автомобилей с разным типом двигателя",
        "Что проверяли",
        "- Нулевая гипотеза H0: средние цены автомобилей одинаковы для всех типов двигателя.",
        "- Альтернативная гипотеза H1: хотя бы один тип двигателя отличается по средней цене.",
        "- Использована Welch ANOVA, потому что группы неравны по численности и разбросу.",
        "",
        "Статистический вывод",
        f"- Welch ANOVA: F = {anova['statistic']:.3f}, df = ({anova['df_num']:.0f}; {anova['df_den']:.2f}), p = {anova['p_value']:.4f}.",
        f"- Eta squared = {anova['eta_squared']:.3f}, то есть эффект {anova_effect}.",
        f"- Разрыв между самой дорогой и самой дешевой по средней цене группой составляет около {format_int(anova['mean_gap'])} руб.",
        (
            "- Значение p меньше 0.05, поэтому как минимум один тип двигателя отличается по средней цене."
            if anova_significant
            else "- Значение p больше 0.05, поэтому различия средних по типам двигателя нельзя считать статистически подтвержденными."
        ),
        "- Сводка по группам:",
    ]

    for engine_type, info in anova["groups"].items():
        sections.append(
            f"- {engine_type}: n = {info['n']}, средняя цена = {format_int(info['mean'])} руб., медиана = {format_int(info['median'])} руб."
        )

    if anova["excluded_groups"]:
        sections.extend(
            [
                "",
                "Исключенные группы",
            ]
        )
        sections.extend(f"- {item}" for item in anova["excluded_groups"])

    sections.extend(
        [
            "",
            "Содержательный вывод",
            (
                "- На уровне значимости 0.05 различия средних цен между типами двигателя статистически значимы."
                if anova_significant
                else "- На уровне значимости 0.05 статистически значимых различий средних цен между типами двигателя не обнаружено."
            ),
            f"- Самая высокая средняя цена в этой выборке у группы '{highest_engine}' ({format_int(highest_info['mean'])} руб.), а самая низкая у группы '{lowest_engine}' ({format_int(lowest_info['mean'])} руб.).",
            (
                "- Для заказчика это означает, что тип двигателя можно учитывать в сегментации, но делать выводы нужно осторожно: часть эффекта может идти от премиальных моделей и малых по численности групп."
                if anova_significant
                else "- Для заказчика это означает, что в текущей выборке сам тип двигателя пока не дает надежного самостоятельного объяснения цены."
            ),
            "",
            "4. Корреляционный анализ для цены и мощности",
            "Что проверяли",
            "- Нулевая гипотеза H0: линейной связи между ценой и мощностью нет.",
            "- Альтернативная гипотеза H1: линейная связь между ценой и мощностью есть.",
            "- Использован коэффициент корреляции Пирсона.",
            "",
            "Статистический вывод",
            f"- Pearson r = {corr['r_value']:.3f}, p = {corr['p_value']:.6f}, R² = {corr['r_squared']:.3f}.",
            f"- Объем выборки для анализа: n = {corr['n']}.",
            f"- Связь {corr_direction} и по силе {corr_strength}.",
            (
                "- Значение p меньше 0.05, поэтому линейная связь статистически подтверждается."
                if corr_significant
                else "- Значение p больше 0.05, поэтому линейная связь статистически не подтверждается."
            ),
            "",
            "Содержательный вывод",
            (
                "- На уровне значимости 0.05 линейная связь между ценой и мощностью статистически значима."
                if corr_significant
                else "- На уровне значимости 0.05 статистически значимой линейной связи между ценой и мощностью не найдено."
            ),
            (
                f"- Для заказчика это самый сильный сигнал в текущем анализе: с ростом мощности автомобили в среднем становятся дороже; примерно {corr['r_squared'] * 100:.1f}% изменчивости цены линейно связано с мощностью."
                if corr_significant and corr["r_value"] > 0
                else f"- Практически это означает, что при росте мощности цена не показывает устойчивого линейного изменения, несмотря на значение r = {corr['r_value']:.3f}."
            ),
            "- Это не причинно-следственный вывод: высокая цена может быть связана не только с мощностью, но и с брендом, возрастом, сегментом и комплектацией автомобиля.",
            "",
            "Итог для заказчика",
            "- Самый полезный признак для объяснения цены в этой выборке: мощность.",
            "- Тип кузова можно использовать как вспомогательный фактор сегментации, но эффект у него слабее.",
            "- Цвет кузова в текущем наборе данных не стоит использовать как самостоятельный критерий цены.",
            "- По типу двигателя лучше делать осторожные выводы и по возможности расширить выборку, особенно по гибридам и электромобилям.",
        ]
    )

    return sections


def main() -> int:
    args = parse_args()
    emit_level_probe(logger, "Этап 4")
    csv_path = args.input.resolve() if args.input else find_latest_csv()
    if not csv_path.exists():
        logger.error("Этап 4: входной CSV не найден: %s", csv_path)
        raise SystemExit(f"Файл не найден: {csv_path}")

    df = load_dataframe(csv_path)
    output_dir = csv_path.parent / FOURTH_TASK_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Этап 4: результаты будут сохранены в %s.", output_dir)
    archive_legacy_reports(output_dir)

    chi = chi_square_body_price(df)
    ttest = welch_t_black_gray(df)
    anova = welch_anova_engine(df)
    corr = correlation_price_power(df)
    logger.info("Этап 4: все статистические расчеты завершены.")

    report_path = output_dir / FOURTH_TASK_REPORT_NAME
    save_text_pdf(
        report_path,
        "Четвертое задание. Статистический анализ",
        build_sections(csv_path, df, chi, ttest, anova, corr),
    )
    logger.info("Этап 4: единый PDF-файл сохранен в %s.", report_path)

    print(f"Исходный файл: {csv_path}")
    print(f"PDF-отчет: {report_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        logger.critical("Этап 4: скрипт завершился с ошибкой: %s", exc, exc_info=True)
        print(f"Ошибка четвертого задания: {exc}")
        raise SystemExit(1)
