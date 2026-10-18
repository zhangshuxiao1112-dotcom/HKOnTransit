# Deploy HKOnTransit

The FastAPI server serves both the English web interface and the `/api/*` gateway from one origin. Deploy them together. GitHub Pages cannot execute this Python backend.

## Render: deploy from this repository

[Deploy to Render](https://render.com/deploy?repo=https://github.com/zhangshuxiao1112-dotcom/HKOnTransit)

1. Open the link and sign in to your Render account.
2. Authorise access to `zhangshuxiao1112-dotcom/HKOnTransit` if prompted.
3. Review the `render.yaml` Blueprint and create the web service. It requests the free plan.
4. After deployment succeeds, open the service's HTTPS URL.
5. In **More → Real-time Info**, select **Check connections**. Gateway health alone does not verify upstream transport connections.

The service runs `uvicorn server:app --host 0.0.0.0 --port $PORT`. It serves frontend assets and API requests together; no CORS change or separate API address is needed. No transport API key is required. AI defaults to labelled local rules; real DeepSeek access requires your own key in the hosting environment, never in GitHub source.

The free configuration uses temporary SQLite storage: snapshots are lost when the filesystem is replaced. Do not use it for durable arrival collection. For durable research data, provision persistent storage on a suitable plan and change `HKONTRANSIT_DB` to that mount. Do not commit database files or secrets.

Committing this Blueprint prepares deployment; it does not create a Render account or launch a service by itself. A public app URL is available only after the hosting deployment finishes.

## Docker / a server you manage

```bash
docker build -t hkontransit .
docker run --rm -p 8000:8000 -v hkontransit-data:/data hkontransit
```

Open `http://localhost:8000`. The container runs as a non-root user and keeps SQLite under `/data`. If your container platform's volume permissions differ, grant the application user write access to the mounted directory.

## Checks

GitHub Actions runs the test suite on Python 3.10 and 3.12 for pushes and pull requests. Tests use simulated upstream responses plus a real local TLS fixture; successful CI does not guarantee official API uptime. Check provider connectivity after each deployment.

Deployment reference: https://render.com/docs/deploy-fastapi
Blueprint reference: https://render.com/docs/blueprint-spec
