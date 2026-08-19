#!/usr/bin/env python3
"""
Agrega una observación de campo desde un archivo JSON (valida antes de guardar).

Uso:
  python3 etl/add_observation.py mi_observacion.json

El esquema está documentado en app/observations.py. Un ejemplo completo está en
etl/examples/samara.json.
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.observations import ObservationStore, validate  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    obs = json.load(open(sys.argv[1], encoding="utf-8"))
    ok, errs, norm = validate(obs)
    if not ok:
        print("✗ Observación inválida:")
        for e in errs:
            print("   -", e)
        sys.exit(2)
    store = ObservationStore()
    store.add(norm)
    zones = len(norm["zones"])
    oper = sum(c["count"] for z in norm["zones"] for c in z["chargers"] if c["status"] == "operational")
    plan = sum(c["count"] for z in norm["zones"] for c in z["chargers"] if c["status"] == "planned")
    print(f"✓ Guardada '{norm['name']}' (id={norm['id']}): {zones} zonas, "
          f"{oper} operativos, {plan} planeados. Total observaciones: {len(store.items)}.")
    print("  Reinicia el servidor o llama /api/observations para reflejarlo.")


if __name__ == "__main__":
    main()
