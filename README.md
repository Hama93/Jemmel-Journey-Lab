# Jemmel Journey Lab

Jemmel Journey Lab is a Flask web platform for tourism discovery and planning.

It includes:
- Role-based access (`admin` and `visitor`)
- Admin attraction management (add/edit/delete)
- Visitor browsing with filters (city/category/budget)
- Reviews and ratings per attraction
- Budget-aware itinerary generation
- AI assistant endpoint for guidance based on available attractions

## Tech Stack
- Python + Flask
- Firebase Admin SDK + Firestore
- Gunicorn (production server)
- Jinja templates + Bootstrap

## Project Structure
- `app/routes.py`: all routes and feature logic
- `app/templates/`: web pages
- `app/static/`: css/js/assets
- `app/config.py`: app configuration
- `run.py`: Flask app entrypoint
- `requirements.txt`: Python dependencies
- `Procfile`: Render web process
- `.env.example`: environment variable template

## Prerequisites
- Python 3.10+
- Firebase project with Firestore database created
- Service account key from Firebase project settings

## Local Setup
1. Create and activate a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Configure environment variables:

```bash
cp .env.example .env
```

Then edit `.env` with your values.

4. Run locally:

```bash
python run.py
```

Or with gunicorn:

```bash
gunicorn run:app --bind 127.0.0.1:8000 --workers 1
```

## Required Environment Variables
- `FLASK_SECRET_KEY`: Flask session secret
- `FLASK_ENV`: `development` or `production`
- `ADMIN_EMAILS`: comma-separated emails that should become admins at signup

Set one Firebase credential option:
- `FIREBASE_SERVICE_ACCOUNT_JSON` (full JSON string)
- `FIREBASE_SERVICE_ACCOUNT_B64` (base64-encoded JSON)
- `FIREBASE_CREDENTIALS_PATH` (path to local key file)
- `GOOGLE_APPLICATION_CREDENTIALS` (standard Google path variable)

## Create Admin User
- Add your email to `ADMIN_EMAILS`
- Sign up using that same email
- You will get role `admin` and can access `/admin/attractions`

## Render Deployment
1. Push this repository to GitHub
2. Create a new Web Service on Render from the repo
3. Build command:

```bash
pip install -r requirements.txt
```

4. Start command:

```bash
gunicorn run:app
```

5. Add environment variables in Render dashboard:
- `FLASK_SECRET_KEY`
- `FLASK_ENV=production`
- `ADMIN_EMAILS`
- One Firebase credential option (recommended: `FIREBASE_SERVICE_ACCOUNT_B64`)

6. Ensure Firestore database exists for your Firebase project

## Notes
- Never commit service account JSON files
- Never commit `.env`
- Keep credentials in your host environment variables

## License
No license granted at this time. All rights reserved.