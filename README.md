# Weather-Aware Truck Routing

A React + Django application that compares truck route options using forecast weather at checkpoint arrival times. 

## Requirements

- Node.js 22+
- Python 3.11+
- A Mapbox account and access token for geocoding, route alternatives, and map display.
- Open-Meteo free API for a non-commercial demo. Commercial use requires an Open-Meteo commercial subscription.

The app makes geocoding and routing requests from Django. Set the server token only in the backend environment. The browser map token is public by design; restrict it to the deployed site's allowed origins.

Location search is global by default. When the map starts, the browser asks for location permission and, if allowed, uses a country-level approximation to frame the map. The origin field also includes a **Use my location** action that fills a city or region from an approximate location. The app does not save the location; reverse-geocoding lookups may count toward Mapbox usage. If permission is denied or unavailable, the map stays on a flat global view and location search remains available.

## Run locally

### Backend

```sh
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Add your server-side `MAPBOX_ACCESS_TOKEN`, then export the values from `backend/.env` before starting Django. For zsh/bash, run `set -a; source .env; set +a`. Django settings read environment variables directly. `GEOCODING_COUNTRY` is optional: leave it blank or unset for global search, or set it to `US` for U.S.-only lookup. Keep it blank for the global demo.

```sh
python manage.py runserver
```

### Frontend

In a second terminal:

```sh
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

Set `VITE_MAPBOX_ACCESS_TOKEN` in `frontend/.env.local` to a public, origin-restricted Mapbox token. The backend API URL defaults to `http://localhost:8000/api`.

## Deploy on Render

The root `render.yaml` defines a free Django API service and a free React static site. To deploy, push the project to GitHub, create a new Blueprint in Render, and select the repository. Render generates the Django secret and prompts for two Mapbox tokens:

- `MAPBOX_ACCESS_TOKEN` is the private backend token for geocoding and routing.
- `VITE_MAPBOX_ACCESS_TOKEN` is included in the public frontend build for the map and reverse geocoding. Restrict it to the deployed site's origin.

BTW- NOTE: Render's free backend sleeps after 15 minutes without traffic; the first request after that can take about a minute. The app does not rely on persistent database data, so its okay.
