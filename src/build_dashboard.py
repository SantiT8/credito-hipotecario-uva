"""Arma el dashboard autocontenido: dashboard/index.html (sin librerías externas ni llamadas a internet).

Uso:  .venv\\Scripts\\python.exe src\\build_dashboard.py

Une dashboard/plantilla.html + dashboard/motor.js + data/processed/resultados/dashboard_data.json y copia al
lado los PDF del resumen y la presentación (la documentación completa queda en el repositorio), para que la carpeta dashboard/ se pueda publicar tal cual.
"""
import json
import shutil

from build_docs import AUTOR, protagonista
from config import FECHA_CORTE, PROCESSED, ROOT

DASH = ROOT / "dashboard"
REPO_URL = "https://github.com/SantiT8/credito-hipotecario-uva"
DOCUMENTOS = {"resumen_en_simple.pdf": ROOT / "reports" / "resumen_en_simple.pdf",
              "presentacion.pdf": ROOT / "deck" / "presentacion.pdf"}


def main() -> None:
    datos = json.loads((PROCESSED / "resultados" / "dashboard_data.json").read_text(encoding="utf-8"))
    kpis = json.loads((PROCESSED / "resultados" / "kpis.json").read_text(encoding="utf-8"))
    links = [{"texto": "Resumen en simple (PDF)", "url": "resumen_en_simple.pdf"}]
    if DOCUMENTOS["presentacion.pdf"].exists():
        links.insert(0, {"texto": "Presentación (PDF)", "url": "presentacion.pdf"})
    links.append({"texto": "Código, documentación y fuentes en GitHub", "url": REPO_URL, "externo": True})
    datos["textos"] = {"autor": AUTOR, "fecha_corte": FECHA_CORTE.strftime("%d-%m-%Y"), "protagonista": protagonista(kpis), "links": links}

    plantilla = (DASH / "plantilla.html").read_text(encoding="utf-8")
    motor = (DASH / "motor.js").read_text(encoding="utf-8")
    json_seguro = json.dumps(datos, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = plantilla.replace("/*__MOTOR__*/", motor).replace("/*__DATOS__*/", json_seguro)
    assert "/*__" not in html, "quedó un marcador sin reemplazar"
    (DASH / "index.html").write_text(html, encoding="utf-8")
    for nombre, origen in DOCUMENTOS.items():
        if origen.exists():
            shutil.copy2(origen, DASH / nombre)
    print(f"  ✓ dashboard/index.html ({len(html.encode('utf-8')) / 1024:.0f} KB) + {sum(o.exists() for o in DOCUMENTOS.values())} PDF")


if __name__ == "__main__":
    main()
