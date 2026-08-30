#!/usr/bin/env python3
"""
ETL: procesa el catálogo nacional de códigos postales de Correos de México (SEPOMEX)
hacia un mapeo compacto código postal -> municipio/estado, usado por app/electricity.py
para resolver la tarifa eléctrica real (CFE) por ubicación.

Fuente: https://www.correosdemexico.gob.mx/datosabiertos/cp/cpdescarga.csv
(descargar a ~/Downloads si no está ya ahí — es de uso libre, catálogo oficial).

Salida: data/processed/cp_municipio.json  { "<CP 5 dígitos>": {"municipio":.., "estado":..} }
"""
import csv, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "data", "processed", "cp_municipio.json")
SRC = os.path.join(os.path.expanduser("~/Downloads"), "cpdescarga.csv")


def main():
    if not os.path.exists(SRC):
        raise SystemExit(f"Falta el catálogo SEPOMEX en {SRC} — descárgalo de "
                          f"https://www.correosdemexico.gob.mx/datosabiertos/cp/cpdescarga.csv")
    out = {}
    with open(SRC, encoding="cp1252", newline="") as f:
        for row in csv.DictReader(f):
            cp = (row.get("d_codigo") or "").strip().zfill(5)
            municipio = (row.get("D_mnpio") or "").strip()
            estado = (row.get("d_estado") or "").strip()
            if cp and municipio and estado:
                out[cp] = {"municipio": municipio, "estado": estado}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"cp_municipio.json: {len(out)} códigos postales -> {OUT}")


if __name__ == "__main__":
    main()
