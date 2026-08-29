"""
Compila pipelines/m5_pipeline.py a YAML -- Fase 7, Tarea 3.

El YAML compilado es el entregable versionable de INSTRUCCIONES.md
("Pipeline YAML compilado"): describe exactamente los 5 componentes, sus
imagenes/paquetes, y el SQL de features_train embebido tal cual estaba al
compilar (ver docstring de m5_pipeline.py).

Uso:
    python -m pipelines.compile_pipeline
"""

from kfp import compiler

from pipelines.m5_pipeline import m5_pipeline

OUTPUT_PATH = "pipelines/m5_pipeline.yaml"


def main() -> None:
    compiler.Compiler().compile(pipeline_func=m5_pipeline, package_path=OUTPUT_PATH)
    print(f"Pipeline compilado en {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
