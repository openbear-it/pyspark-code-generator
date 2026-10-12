# PySpark Code Generator

Servizio FastAPI per generare, analizzare, migliorare e commentare codice PySpark con un modello LLM OpenAI-compatible. Ogni chat, il relativo contesto e i messaggi sono persistiti in SQLite. I file allegati a un singolo prompt vengono passati al modello senza inserirne il contenuto nel testo della cronologia; i file aggiunti al contesto persistente vengono salvati con quel contesto.

## Configuration

Create a local configuration file and set the values provided by your LLM vendor:

```bash
cp .env.example .env
```

Edit `.env` and set `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL`. `LLM_BASE_URL` must include an optional `/v1` prefix; the service calls `/chat/completions`. `LLM_MAX_OUTPUT_TOKENS` defaults to `4096` and controls the maximum generated response length; keep it within the limit supported by the selected model and provider. If a response reaches that limit, the service continues it up to `LLM_MAX_CONTINUATIONS` times (default `2`). `LLM_VERIFY_SSL` defaults to `false` to support self-signed LLM certificates; set it to `true` to verify the endpoint certificate. `.env` is automatically loaded for local execution and is excluded from the Docker build context.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload
```

To start the application from this workspace when `.venv` already exists:

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Aprire `http://localhost:8000` per la UI. La documentazione interattiva Swagger UI e` disponibile su `http://localhost:8000/docs`, ReDoc su `http://localhost:8000/redoc` e lo schema OpenAPI JSON su `http://localhost:8000/openapi.json`.

## Browser privacy

Ogni browser riceve un cookie anonimo `HttpOnly` e vede solo le chat create con quel cookie. Le schede dello stesso profilo browser condividono le chat; profili o browser distinti ricevono spazi separati. Non ci sono account: cancellare il cookie crea un nuovo spazio e non consente di recuperare quello precedente. Le chat create prima dell'introduzione dell'isolamento restano nel database, ma non vengono assegnate automaticamente né mostrate.

I client API devono conservare e reinviare il cookie `pyspark_browser_session` per mantenere lo stesso spazio tra le richieste.

## Observability

`GET /health` is a liveness endpoint; `GET /ready` is a readiness endpoint that verifies SQLite availability. `GET /metrics` exposes Prometheus metrics in the standard scrape format: HTTP request counts and durations, plus LLM request counts and durations labeled by operation and result.

Per eseguire con il virtual environment locale:

```bash
.venv/bin/uvicorn app.main:app --reload
```

## API

1. `POST /api/chats` crea una sessione.
2. `GET /api/chats/{chat_id}` recupera cronologia e messaggi.
3. `GET /api/chats/{chat_id}/context` recupera il contesto della chat.
4. `PUT /api/chats/{chat_id}/context` salva `relevant_code`, `programming_language`, `requirements` e `libraries`. Il contesto e` aggiunto al prompt di sistema per ogni richiesta LLM della chat.
5. `POST /api/chats/{chat_id}/context/files` accetta uno o piu` campi multipart `files` UTF-8 fino a 2 MB ciascuno e li salva nel contesto persistente della chat. CSV, TSV, JSON e JSON Lines vengono profilati localmente (schema, tipi dedotti, valori mancanti e campione) e l'analisi viene inclusa nelle successive richieste LLM; le altre sorgenti UTF-8 vengono incluse come testo.
6. `POST /api/chats/{chat_id}/messages` accetta `multipart/form-data`: `prompt`, `operation` (`generate`, `analyze`, `improve`, `comment`) e opzionalmente uno o piu` campi `files` UTF-8 fino a 2 MB ciascuno. La risposta viene inviata come stream di testo e salvata nella chat al termine della generazione.

Esempio per un microservizio:

```bash
curl -c cookies.txt -b cookies.txt -X POST http://localhost:8000/api/chats \
  -H 'Content-Type: application/json' -d '{}'
curl -b cookies.txt -X POST http://localhost:8000/api/chats/CHAT_ID/messages \
  -F 'prompt=Create a daily aggregation by customer' \
  -F 'operation=generate' \
  -F 'files=@job.py'
```

Per impostare il contesto da un microservizio:

```bash
curl -X PUT http://localhost:8000/api/chats/CHAT_ID/context \
  -b cookies.txt \
  -H 'Content-Type: application/json' \
  -d '{
    "programming_language": "PySpark",
    "libraries": "PySpark, Delta Lake",
    "requirements": "Target Databricks; preserve the input schema.",
    "relevant_code": "df = spark.read.format(\"delta\").load(source_path)"
  }'
```

## Docker

```bash
docker build -t pyspark-code-generator .
docker run --rm -p 8000:8000 \
  --env-file .env \
  -v pyspark-generator-data:/app/data \
  pyspark-code-generator
```

## GitHub Container Registry

The [Docker publishing workflow](.github/workflows/docker-publish.yml) builds the image on pull requests and publishes it to `ghcr.io/openbear-it/pyspark-code-generator` after pushes to `main` and version tags such as `v1.0.0`. GitHub repository settings must allow GitHub Actions to write packages.

```bash
docker pull ghcr.io/openbear-it/pyspark-code-generator:latest
```