# PC Monitoring System Dev Run

## Backend

```powershell
cd D:\Projects\pc-monitoring-system\backend
.\venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload
```

Backend API is expected at `http://127.0.0.1:8000`.

## Frontend

```powershell
cd D:\Projects\pc-monitoring-system\frontend
npm run dev
```

Frontend dev server is expected at `http://localhost:5173`.

## Notes

- Vite proxy forwards `/api/*` to `http://127.0.0.1:8000/*`.
- If you want the frontend to bypass Vite proxy and call backend directly, set `VITE_API_PROXY_BYPASS=true`.
