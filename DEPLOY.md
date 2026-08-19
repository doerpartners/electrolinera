# Subir el demo a una URL pública (gratis / barato)

El servidor usa **solo la librería estándar de Python** y los datos ya están en
`data/` (no depende de los Excel de tu carpeta Downloads). Ya quedó listo para la
nube: escucha en `0.0.0.0` y toma el puerto de la variable `PORT`.

## Opción A — Render.com (recomendada: gratis y siempre en línea)

URL fija tipo `https://ev-siting-demo.onrender.com`. El plan free "duerme" tras
15 min sin uso y tarda ~30–50 s en despertar (aceptable para demo).

1. **Sube el repo a GitHub** (ya está commiteado localmente):
   ```bash
   cd ~/ev-siting-demo
   gh repo create ev-siting-demo --private --source=. --push
   ```
   (o crea el repo en github.com y `git remote add origin <url> && git push -u origin main`)
2. Entra a **https://render.com** → *New* → *Web Service* → conecta tu GitHub y elige el repo.
3. Render detecta `render.yaml` solo. Si te pide datos a mano:
   - Runtime: **Python** · Build: `pip install -r requirements.txt` · Start: `python run.py`
   - Plan: **Free**
4. *Create Web Service* → en 2–3 min tienes la URL pública. Listo.

## Opción B — Compartir YA, sin crear cuenta (túnel, gratis)

Publica tu servidor local con un URL temporal en segundos. Requiere tu Mac
encendida y el servidor corriendo.

```bash
# 1) corre el server local
cd ~/ev-siting-demo && python3 run.py 8077
# 2) en otra terminal, exponlo (instala cloudflared con: brew install cloudflared)
cloudflared tunnel --url http://localhost:8077
```
Te da un URL `https://xxxx.trycloudflare.com`. Alternativa: `ngrok http 8077`.
Ideal para enseñarlo a alguien ahora; no es permanente.

## Opción C — Google Cloud Run (barato, escala a cero)

Usa el `Dockerfile` incluido. Casi gratis (paga solo por uso; escala a 0).
```bash
gcloud run deploy ev-siting --source . --region us-central1 --allow-unauthenticated
```

## Comparativa rápida

| Opción | Costo | URL permanente | Setup | Notas |
|---|---|---|---|---|
| **Render free** | Gratis | Sí | ~10 min | Duerme tras 15 min; cold start |
| **Cloudflare/ngrok** | Gratis | No (temporal) | ~2 min | Requiere tu equipo encendido |
| **Cloud Run** | ~Gratis por uso | Sí | ~15 min | Necesita cuenta GCP + Docker |
| **Railway** | ~$5/mes | Sí | ~10 min | Sin sleep, más estable |

## Nota sobre datos que se escriben en runtime

Agregar observaciones (`POST /api/observations`) y ajustar pesos/pricing escribe
en disco/memoria del contenedor. En planes free ese disco es **efímero**: se
reinicia en cada redeploy o al despertar. Los datos semilla (Samara, Parque Delta,
Pabellón, NSE, cargadores) **sí persisten** porque van en el repo. Para que las
observaciones nuevas persistan, se necesita un disco/DB persistente (siguiente paso).
