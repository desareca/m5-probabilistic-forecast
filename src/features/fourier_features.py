"""
Generador de expresiones SQL para features Fourier de estacionalidad.

Uso: este script no se conecta a BigQuery. Genera el bloque de columnas
SQL (SIN/COS por armónico) que se pega en sql/build_features_train.sql,
bajo el CTE `fourier`. Se ejecuta una sola vez para producir ese bloque;
si cambian los periodos o n_terms de INSTRUCCIONES.md (Fase 3), correr de
nuevo y reemplazar el bloque en el .sql en vez de editar las expresiones
trigonométricas a mano (propenso a errores con exponentes/denominadores).

Time index: days_since_start = DATE_DIFF(date, '2011-01-29', DAY), un
contador de día calendario global (mismo valor para todas las series en
una fecha dada). Usar un índice por serie (p.ej. días desde la primera
venta de cada item) desalinearía la fase de las funciones seno/coseno
entre series con distinta fecha de primera venta -- days_since_start
mantiene la fase anclada al calendario real.

BigQuery no tiene una función PI() nativa; el estándar es usar ACOS(-1).
"""

from dataclasses import dataclass

TIME_COL = "t.days_since_start"
PI_EXPR = "c.pi"  # ver CTE `consts AS (SELECT ACOS(-1) AS pi)` en el .sql


@dataclass
class FourierSpec:
    name: str       # prefijo de la feature, ej. "week"
    period: float   # periodo en días
    n_terms: int    # cantidad de pares seno/coseno (armónicos)


# Especificación tomada literalmente de INSTRUCCIONES.md, Fase 3:
# - semanal: period=7, n_terms=3
# - semestral: period=182.625, n_terms=3
# - anual: period=365.25, n_terms=5
FOURIER_SPECS = [
    FourierSpec(name="week", period=7, n_terms=3),
    FourierSpec(name="semester", period=182.625, n_terms=3),
    FourierSpec(name="year", period=365.25, n_terms=5),
]


def build_fourier_columns(spec: FourierSpec) -> list[str]:
    """Expresiones SQL (SIN + COS) para los n_terms armónicos de un spec."""
    columns = []
    for k in range(1, spec.n_terms + 1):
        angle = f"2 * {PI_EXPR} * {k} * {TIME_COL} / {spec.period}"
        columns.append(f"SIN({angle}) AS fourier_{spec.name}_sin_{k}")
        columns.append(f"COS({angle}) AS fourier_{spec.name}_cos_{k}")
    return columns


def build_all_fourier_sql(specs: list[FourierSpec] = FOURIER_SPECS) -> str:
    """Bloque completo de columnas Fourier, listo para pegar en un SELECT."""
    all_columns = []
    for spec in specs:
        all_columns.append(f"    -- Fourier {spec.name} (period={spec.period}, n_terms={spec.n_terms})")
        all_columns.extend(f"    {c}" for c in build_fourier_columns(spec))
    return ",\n".join(all_columns)


if __name__ == "__main__":
    print(build_all_fourier_sql())
