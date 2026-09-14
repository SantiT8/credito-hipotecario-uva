"""Censo 2022 (INDEC, resultados definitivos): hogares por régimen de tenencia en formato ordenado.

Uso:  .venv\\Scripts\\python.exe src\\censo.py

Descarga los cuadros 6 (hogares por régimen de tenencia) y los deja en una sola tabla:
data/processed/censo2022_hogares_tenencia.csv  (una fila por país / provincia / agregado / partido / comuna)
"""
import warnings

import pandas as pd
import requests

from config import CENSO_ARCHIVOS, CENSO_BASE_URL, HTTP_HEADERS, PROCESSED, RAW

warnings.filterwarnings("ignore")
CENSO_DIR = RAW / "censo2022"
SALIDA = PROCESSED / "censo2022_hogares_tenencia.csv"
COLS = ["codigo", "nombre", "hogares", "propia", "escritura", "boleto", "otra_doc", "sin_doc",
        "alquilada", "cedida_trabajo", "prestada", "otra"]


def descargar() -> None:
    CENSO_DIR.mkdir(parents=True, exist_ok=True)
    for nombre, carpeta in CENSO_ARCHIVOS.items():
        destino = CENSO_DIR / nombre
        if destino.exists():
            continue
        # censo.gob.ar presenta una cadena de certificados incompleta: se descarga sin verificar el
        # certificado y se valida el contenido (firma ZIP de un .xlsx) antes de usarlo.
        r = requests.get(CENSO_BASE_URL + carpeta + nombre, headers=HTTP_HEADERS, timeout=120, verify=False)
        r.raise_for_status()
        if not r.content.startswith(b"PK"):
            raise ValueError(f"{nombre} no es un xlsx válido")
        destino.write_bytes(r.content)


def leer(archivo: str, hoja=0) -> pd.DataFrame:
    df = pd.read_excel(CENSO_DIR / archivo, sheet_name=hoja, header=None).iloc[:, :12]
    df.columns = COLS
    df = df[pd.to_numeric(df.hogares, errors="coerce").notna()].copy()
    for c in COLS[2:]:
        df[c] = pd.to_numeric(df[c].astype(str).str.strip().replace({"-": "0"}), errors="coerce")
    df["nombre"] = df.nombre.astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    df["codigo"] = df.codigo.astype(str).str.strip().replace({"nan": None})
    return df


def construir() -> pd.DataFrame:
    partes = []
    pais = leer("c2022_tp_hogares_c6.xlsx")
    t = pais[pais.codigo == "Total"].assign(nivel="pais", provincia="Total del país", nombre="Total del país")
    partes.append(t)
    partes.append(pais[pais.codigo.str.len() == 2].assign(nivel="provincia", provincia=lambda d: d.nombre))

    caba = leer("c2022_caba_hogares_c6_1.xlsx")
    partes.append(caba[caba.codigo.str.len() == 5].assign(nivel="comuna", provincia="Ciudad Autónoma de Buenos Aires"))

    p24 = leer("c2022_bsas_hogares_c6_2.xlsx", "Cuadro6.2")
    p31 = leer("c2022_bsas_hogares_c6_2.xlsx", "Cuadro6.2 bis")
    partes.append(p24[p24.nombre == "24 partidos de Buenos Aires"].assign(nivel="agregado", provincia="Buenos Aires", codigo="24P"))
    partes.append(p31[p31.nombre == "31 partidos de Buenos Aires"].assign(nivel="agregado", provincia="Buenos Aires", codigo="31P"))
    partes.append(p24[p24.codigo.str.len() == 5].assign(nivel="partido", provincia="Buenos Aires"))

    cba = leer("c2022_cordoba_hogares_c6_6.xlsx")
    partes.append(cba[cba.codigo.str.len() == 5].assign(nivel="departamento", provincia="Córdoba"))

    out = pd.concat(partes, ignore_index=True)[["nivel", "provincia", "codigo", "nombre"] + COLS[2:]]
    out = out.drop_duplicates(subset=["nivel", "codigo", "nombre"])
    # Control: la suma de partidos coincide con el total provincial publicado
    prov_ba = out[(out.nivel == "provincia") & (out.nombre == "Buenos Aires")].hogares.iloc[0]
    suma = out[(out.nivel == "partido") & (out.provincia == "Buenos Aires")].hogares.sum()
    if suma != prov_ba:
        raise ValueError(f"Suma de partidos ({suma}) ≠ total provincial ({prov_ba})")
    return out


def main() -> None:
    descargar()
    tabla = construir()
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    tabla.to_csv(SALIDA, index=False)
    print(f"  ✓ {SALIDA.name}: {len(tabla)} filas")
    print(tabla.groupby("nivel").size().to_string())


if __name__ == "__main__":
    main()
