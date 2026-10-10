# AutoDev dashboard

Mobile-first Next.js app: kanban, task page with live agent log, projects and releases, settings.
Installable as a PWA (Safari → Share → Add to Home Screen).

```bash
npm ci
API_PROXY=http://localhost:8000 npm run dev      # proxies /api to a local AutoDev API
npm run lint && npx tsc --noEmit
```

End-to-end smoke test (needs a running API + dashboard and Python Playwright):

```bash
python e2e/smoke.py http://localhost:3000 /tmp/shots
```
