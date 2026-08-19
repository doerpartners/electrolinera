#!/usr/bin/env python3
"""Punto de entrada del demo.  Uso:  python3 run.py [puerto]"""
import os, sys, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
PROC = os.path.join(HERE, "data", "processed", "chargers.json")

if not os.path.exists(PROC):
    print("Datos procesados no encontrados → corriendo ETL…")
    subprocess.check_call([sys.executable, os.path.join(HERE, "etl", "build_dataset.py")])

sys.path.insert(0, HERE)
from app.server import run

if __name__ == "__main__":
    # En la nube (Render/Railway/Fly/Cloud Run) el puerto llega por la variable PORT
    # y hay que escuchar en 0.0.0.0. En local se mantiene 127.0.0.1.
    env_port = os.environ.get("PORT")
    port = int(env_port or (sys.argv[1] if len(sys.argv) > 1 else 8000))
    host = "0.0.0.0" if env_port else "127.0.0.1"
    run(host=host, port=port)
