# Database Setup Guide

This guide explains how to set up separate test and production databases for your yoga booking system.

## Overview

- **Production Database**: `yoga-booking-db` - Used by the live application on Render
- **Test Database**: `yoga-booking-db-test` - Used for local development and testing

## Step 1: Create Test Database on Render

1. Go to [Render Dashboard](https://dashboard.render.com)
2. Click **"New"** → **"PostgreSQL"**
3. Configure:
   - **Name**: `yoga-booking-db-test`
   - **Database**: `yoga_booking_test`
   - **Plan**: Free
4. Click **"Create Database"**
5. Wait for database to be ready (~2 minutes)

## Step 2: Get Database Connection URLs

### Test Database URL:
1. Go to Render Dashboard → `yoga-booking-db-test`
2. Find **"External Database URL"** (for connecting from your local machine)
3. Copy the entire URL (starts with `postgres://`)

### Production Database URL:
1. Go to Render Dashboard → `yoga-booking-db`
2. Find **"External Database URL"**
3. This is automatically used by your deployed app via `render.yaml`

## Step 3: Configure Local Environment

Create a `.env` file in your project root:

```bash
# ========================================
# LOCAL DEVELOPMENT (Test Database)
# ========================================

# Test Database URL (paste from Render)
DATABASE_URL=postgresql://test_user:test_pass@dpg-xxxxx-test.oregon-postgres.render.com/yoga_booking_test

# Flask Configuration
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
CORS_SECRET_KEY=your-secret-key-here-change-this

# Email Service
RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Application Base URL
BASE_URL=http://localhost:8000

# Optional
DB_POOL_SIZE=5
```

## Step 4: Verify Setup

### Test Your Local Setup:
```bash
# Activate virtual environment
source venv/bin/activate

# Run the app
python app.py

# You should see:
# Using postgresql database: ...
# ✅ PostgreSQL connection pool initialized successfully!
# Database initialized successfully in X.Xs
# Running on http://0.0.0.0:8000
```

### Test Production (on Render):
- Your production app automatically uses `yoga-booking-db`
- No changes needed - already configured in `render.yaml`

## Database Architecture

```
┌─────────────────────────────────────────┐
│ LOCAL DEVELOPMENT                       │
│ python app.py                           │
│   ↓                                     │
│ .env: DATABASE_URL → TEST DATABASE     │
│   ↓                                     │
│ yoga-booking-db-test (Render)          │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│ PRODUCTION                              │
│ gunicorn app:app (on Render)           │
│   ↓                                     │
│ Render env vars → PRODUCTION DATABASE  │
│   ↓                                     │
│ yoga-booking-db (Render)               │
└─────────────────────────────────────────┘
```

## Benefits

✅ **Safe Testing**: Test data won't affect production
✅ **Real Database**: Test against actual PostgreSQL, not SQLite
✅ **Production Parity**: Same database engine as production
✅ **Easy Switching**: Just change `DATABASE_URL` in `.env`

## Switching Between Databases

### Use Test Database (Development):
```bash
# In .env
DATABASE_URL=postgresql://...test.onrender.com/yoga_booking_test
```

### Use Production Database (Careful!):
```bash
# In .env - ONLY if you know what you're doing
DATABASE_URL=postgresql://...prod.onrender.com/yoga_booking
```

### Use Local SQLite (Offline work):
```bash
# In .env - comment out DATABASE_URL
# DATABASE_URL=postgresql://...
```

## Troubleshooting

### Connection Failed
- ✅ Check External Database URL is correct
- ✅ Verify your IP isn't blocked by Render
- ✅ Ensure database is running (green status on Render)

### Tables Not Created
- Run `python app.py` - tables are created automatically
- Check console output for errors

### Wrong Database
- Check which database is being used:
  ```bash
  # Look for this line in console output:
  Using postgresql database: ...
  ```

## Security Notes

⚠️ **Never commit your `.env` file**
⚠️ **Use different secrets for test and production**
⚠️ **Be careful when switching to production database locally**

## Next Steps

1. Push `render.yaml` changes to GitHub
2. Render will automatically create `yoga-booking-db-test`
3. Set up your local `.env` file with test database URL
4. Start developing against test database
5. Production continues using production database automatically

