"""Descarga reproducible de todas las fuentes crudas a data/raw/.

Uso:  .venv\\Scripts\\python.exe src\\download.py [--skip-gcba]

Genera data/raw/manifest.json con URL, tamaño, hash y fecha de cada archivo descargado.
"""
import argparse
import hashlib
import io
import json
import sys
import zipfile
from datetime import datetime, timezone

import pandas as pd
import requests

from config import (BCRA_SERIES, BCRA_URL, BNA_ID, EPH_REGISTRO_URL, EPH_TRIMESTRES, EPH_URL, FECHA_CORTE,
                    GCBA_PACKAGE_URL, HTTP_HEADERS, RAW, RIPTE_ID, SERIES_IDS, SERIES_URL, SIPA_IDS)

MANIFEST: list[dict] = []


def _get(url: str, **kwargs) -> requests.Response:
    r = requests.get(url, headers=HTTP_HEADERS, timeout=180, **kwargs)
    r.raise_for_status()
    return r


def _save(path, content: bytes, url: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    MANIFEST.append({
        "path": str(path.relative_to(RAW)).replace("\\", "/"),
        "url": url,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    print(f"  ✓ {path.relative_to(RAW)} ({len(content) / 1e6:.1f} MB)")


def download_eph() -> None:
    print("EPH (INDEC)")
    for t, y in EPH_TRIMESTRES:
        url = EPH_URL.format(t=t, y=y)
        r = _get(url)
        # INDEC devuelve su home (HTML, status 200) cuando el archivo no existe: validar que sea un zip
        if not r.content.startswith(b"PK"):
            sys.exit(f"  ✗ {url} no devolvió un zip (¿cambió la convención de nombres?)")
        _save(RAW / "eph" / f"EPH_usu_{t}_Trim_{y}_txt.zip", r.content, url)
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            for info in z.infolist():
                name = info.filename.split("/")[-1].lower()
                if name.endswith(".txt") and ("hogar" in name or "individual" in name):
                    tipo = "hogar" if "hogar" in name else "individual"
                    (RAW / "eph" / f"usu_{tipo}_T{t}{str(y)[2:]}.txt").write_bytes(z.read(info))
    url = EPH_REGISTRO_URL.format(t=EPH_TRIMESTRES[-1][0], y=EPH_TRIMESTRES[-1][1])
    try:
        _save(RAW / "eph" / url.split("/")[-1], _get(url).content, url)
    except requests.HTTPError:
        print("  (diseño de registro no disponible, se continúa)")


def download_bcra() -> None:
    print("BCRA API v4.0")
    limit = 3000
    for var_id, nombre in BCRA_SERIES.items():
        rows, offset = [], 0
        while True:
            params = {"desde": "2000-01-01", "hasta": FECHA_CORTE.isoformat(), "limit": limit, "offset": offset}
            payload = _get(BCRA_URL.format(id=var_id), params=params).json()
            detalle = payload["results"][0]["detalle"] if payload.get("results") else []
            rows.extend(detalle)
            if len(detalle) < limit:
                break
            offset += limit
        df = pd.DataFrame(rows).assign(id_variable=var_id, serie=nombre)
        url = BCRA_URL.format(id=var_id)
        _save(RAW / "bcra" / f"bcra_{var_id}_{nombre}.csv", df.to_csv(index=False).encode("utf-8"), url)


def download_series() -> None:
    print("API Series de Tiempo (INDEC Índice de Salarios, RIPTE)")
    params = {"ids": ",".join(SERIES_IDS), "format": "csv", "limit": 5000}
    r = _get(SERIES_URL, params=params)
    _save(RAW / "series" / "indice_salarios.csv", r.content, r.url)
    r = _get(SERIES_URL, params={"ids": RIPTE_ID, "format": "csv", "limit": 5000})
    _save(RAW / "series" / "ripte.csv", r.content, r.url)
    # SIPA: remuneración bruta promedio y mediana de asalariados registrados del sector privado
    r = _get(SERIES_URL, params={"ids": ",".join(SIPA_IDS), "format": "csv", "limit": 5000})
    _save(RAW / "series" / "sipa_remuneraciones.csv", r.content, r.url)
    # Dólar Banco Nación vendedor: promedio mensual de la serie diaria
    r = _get(SERIES_URL, params={"ids": BNA_ID, "format": "csv", "limit": 5000,
                                 "collapse": "month", "collapse_aggregation": "avg"})
    _save(RAW / "series" / "dolar_bna_vendedor_mensual.csv", r.content, r.url)


def download_gcba() -> None:
    print("GCBA Departamentos en venta")
    resources = _get(GCBA_PACKAGE_URL).json()["result"]["resources"]
    for res in resources:
        url, fmt = res["url"], (res.get("format") or "").upper()
        fname = url.split("/")[-1]
        # CSV cuando existe; para 2017-2019 solo hay shapefile (ZIP)
        if fmt == "CSV" or (fmt == "ZIP" and any(y in fname for y in ("2017", "2018", "2019"))):
            _save(RAW / "gcba" / fname, _get(url).content, url)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-gcba", action="store_true")
    args = parser.parse_args()

    download_eph()
    download_bcra()
    download_series()
    if not args.skip_gcba:
        download_gcba()
    print("Censo 2022 (INDEC)")
    import censo
    censo.main()

    # El manifest se actualiza por ruta (una corrida parcial no borra lo descargado antes)
    manifest_path = RAW / "manifest.json"
    previous = json.loads(manifest_path.read_text(encoding="utf-8"))["files"] if manifest_path.exists() else []
    files = {f["path"]: f for f in previous} | {f["path"]: f for f in MANIFEST}
    manifest_path.write_text(json.dumps({"fecha_corte": FECHA_CORTE.isoformat(), "files": sorted(files.values(), key=lambda f: f["path"])},
                                        indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nManifest: {manifest_path} ({len(files)} archivos)")


if __name__ == "__main__":
    main()
