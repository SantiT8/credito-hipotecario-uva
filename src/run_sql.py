"""Ejecuta archivos .sql contra la base DuckDB del proyecto.

Uso:  .venv\\Scripts\\python.exe src\\run_sql.py sql/01_staging.sql [sql/02_profiling.sql ...]

Convenciones de los .sql:
- Las rutas son relativas a la raíz del proyecto (el runner hace chdir ahí).
- Una query precedida por un comentario `-- name: <nombre>` se considera evidencia:
  su resultado se imprime y se guarda en data/processed/evidencia/<archivo>/<nombre>.csv
"""
import os
import re
import sys
from pathlib import Path

import duckdb

from config import DB_PATH, PROCESSED, ROOT

NAME_RE = re.compile(r"^--\s*name:\s*([\w\-]+)", re.MULTILINE)


def split_statements(sql: str) -> list[str]:
    """Separa por ';' ignorando los que están dentro de strings simples o de comentarios '--'."""
    statements, buf, in_str = [], [], False
    for line in sql.splitlines(keepends=True):
        if not in_str and line.lstrip().startswith("--"):
            buf.append(line)
            continue
        for ch in line:
            if ch == "'":
                in_str = not in_str
            buf.append(ch)
            if ch == ";" and not in_str:
                statements.append("".join(buf).strip())
                buf = []
    tail = "".join(buf).strip()
    if tail and not all(l.strip().startswith("--") or not l.strip() for l in tail.splitlines()):
        statements.append(tail)
    return [s for s in statements if s.strip(" ;\n")]


def run_file(con: duckdb.DuckDBPyConnection, path: Path) -> None:
    print(f"\n=== {path.name}")
    out_dir = PROCESSED / "evidencia" / path.stem
    for stmt in split_statements(path.read_text(encoding="utf-8")):
        match = NAME_RE.search(stmt)
        body = "\n".join(line for line in stmt.splitlines() if not line.strip().startswith("--")).strip()
        if not body.strip(" ;"):
            continue
        if match:
            df = con.execute(body).df()
            out_dir.mkdir(parents=True, exist_ok=True)
            df.to_csv(out_dir / f"{match.group(1)}.csv", index=False)
            print(f"\n-- {match.group(1)} ({len(df)} filas)")
            print(df.to_string(max_rows=40, max_colwidth=60))
        else:
            con.execute(body)
            first = body.splitlines()[0][:100]
            print(f"  ok: {first}")


def main() -> None:
    os.chdir(ROOT)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    for arg in sys.argv[1:]:
        run_file(con, ROOT / arg)
    con.close()


if __name__ == "__main__":
    main()
