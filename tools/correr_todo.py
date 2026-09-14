"""Corre el pipeline completo, desde los datos crudos hasta los productos publicados.

Uso:  python tools/correr_todo.py [--descargar]

Sin --descargar usa los archivos de data/raw/ (la fecha de corte queda fija); con --descargar los baja de nuevo.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
JUPYTER = str(Path(PY).with_name("jupyter"))
NBCONVERT = [JUPYTER, "nbconvert", "--to", "notebook", "--execute", "--inplace", "--ExecutePreprocessor.timeout=1800"]


def paso(nombre: str, comando: list[str], cwd: Path = ROOT) -> None:
    print(f"\n▶ {nombre}", flush=True)
    subprocess.run(comando, cwd=cwd, check=True)


def main() -> None:
    if "--descargar" in sys.argv:
        paso("Descarga de fuentes", [PY, "src/download.py"])
    (ROOT / "data" / "processed" / "hipotecario.duckdb").unlink(missing_ok=True)
    paso("Notebooks 01-02: staging, perfilado, limpieza y marts", NBCONVERT + ["01_exploracion.ipynb", "02_limpieza_calidad.ipynb"], ROOT / "notebooks")
    paso("Resultados y kpis.json", [PY, "src/export_results.py"])
    # Solo 03-05: los notebooks 01-02 ya se ejecutaron arriba y rearmarlos borraría sus salidas
    paso("Construcción de notebooks 03-05", [PY, "tools/construir_notebooks.py", "03", "04", "05"])
    paso("Notebooks 03-05", NBCONVERT + ["03_analisis_hipotesis.ipynb", "04_modelo_segmentacion_simulador.ipynb",
                                          "05_independientes.ipynb"], ROOT / "notebooks")
    paso("Documentos, README y reportes", [PY, "src/build_docs.py"])
    paso("Presentación y carrusel", [PY, "src/build_deck.py"])
    paso("Dashboard", [PY, "src/build_dashboard.py"])
    paso("Portada", [PY, "tools/construir_portada.py"])
    paso("Test de paridad", [PY, "tools/test_paridad.py"])
    paso("Consistencia de cifras", [PY, "tools/verificar_consistencia.py"])
    print("\n✓ Pipeline completo")


if __name__ == "__main__":
    main()
