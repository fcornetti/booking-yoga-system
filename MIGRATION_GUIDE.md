# 🚀 Migration Guide: Azure → Render.com

This guide will help you migrate your Yoga Booking System from Azure to Render.com while keeping **both systems running in parallel** until you're confident the migration is successful.

## 📋 Overview

**Goal**: Run your app on both Azure and Render simultaneously, then shut down Azure once Render is working perfectly.

**What you'll migrate**:
- ✅ All user accounts (with password hashes preserved)
- ✅ All yoga classes
- ✅ All bookings
- ✅ Web application

**Benefits of Render.com**:
- 🆓 **Free tier**: No monthly costs
- 🚀 Fast deployment from GitHub
- 📦 PostgreSQL database included
- 🔒 Free SSL/HTTPS
- 🔄 Auto-deployments

---

## 🎯 Migration Strategy

### Phase 1: Export from Azure ✅
Export your current data without affecting Azure

### Phase 2: Set up Render 🆕
Create and configure Render services

### Phase 3: Import to Render 📥
Import your data to Render's PostgreSQL

### Phase 4: Parallel Testing 🔀
Both Azure and Render running simultaneously

### Phase 5: Cutover ✂️
Point your domain to Render, shut down Azure

---

## 📦 PHASE 1: Export Your Azure Data

### Step 1.1: Verify Your Azure Connection

Make sure your `.env` file has Azure credentials:

```env
# Azure SQL Server (keep these for now)
DB_SERVER=your-server.database.windows.net
DB_NAME=your-database-name
DB_USERNAME=your-username
DB_PASSWORD=your-password
```

### Step 1.2: Run the Export Script

```bash
# Export all your data from Azure
python export_azure_data.py
```

**Expected output**:
```
🔌 Connecting to Azure SQL Server...
✅ Connected successfully!

👥 Exporting Users...
   ✅ Exported 25 users
🧘 Exporting Yoga Classes...
   ✅ Exported 15 yoga classes
📅 Exporting Bookings...
   ✅ Exported 50 bookings

✅ EXPORT COMPLETED SUCCESSFULLY!
📁 All data saved to: azure_export_20250126_143022/
```

**⚠️ IMPORTANT**: Keep this export directory safe! It contains all your users' data and password hashes.

---

## 🆕 PHASE 2: Set Up Render.com

### Step 2.1: Create Render Account

1. Go to [render.com](https://render.com)
2. Sign up with GitHub (recommended for easy deployment)
3. Authorize Render to access your repository

### Step 2.2: Push Your Code to GitHub

```bash
# Initialize git if you haven't already
git init
git add .
git commit -m "Prepare for Render migration"

# Create repository on GitHub, then:
git remote add origin https://github.com/your-username/yoga-booking-system.git
git push -u origin main
```

### Step 2.3: Create PostgreSQL Database on Render

1. Go to [Render Dashboard](https://dashboard.render.com)
2. Click **"New +"** → **"PostgreSQL"**
3. Configure:
   - **Name**: `yoga-booking-db`
   - **Database**: `yoga_booking`
   - **Region**: Choose closest to your users
   - **Plan**: **Free** (256 MB RAM, good for small apps)
4. Click **"Create Database"**

**⏱️ Wait 2-3 minutes** for database to be created.

### Step 2.4: Get Database Connection URL

1. Once database is ready, click on it
2. Scroll down to **"Connections"** section
3. Copy the **"Internal Database URL"** (looks like: `postgres://username:password@host/database`)
4. **Save this URL** - you'll need it for import

---

## 📥 PHASE 3: Import Data to Render

### Step 3.1: Install PostgreSQL Driver (if not installed)

```bash
pip install psycopg2-binary
```

### Step 3.2: Run Import Script

```bash
python import_to_render.py
```

**You'll be prompted for**:
- Your Render DATABASE_URL (paste the Internal Database URL from Step 2.4)

**Expected output**:
```
🔌 Connecting to Render PostgreSQL...
   ✅ Connected successfully!

🔨 Creating database tables...
   ✅ Tables created with indexes

👥 Importing Users...
   ✅ Imported 25 users
🧘 Importing Yoga Classes...
   ✅ Imported 15 yoga classes
📅 Importing Bookings...
   ✅ Imported 50 bookings

✅ IMPORT COMPLETED SUCCESSFULLY!
```

**✅ Your data is now on Render!** Azure is still running unchanged.

---

## 🌐 PHASE 4: Deploy Web App to Render

### Step 4.1: Create Web Service

1. In Render Dashboard, click **"New +"** → **"Web Service"**
2. Select your GitHub repository
3. Configure:

   **Basic Settings**:
   - **Name**: `yoga-booking-system`
   - **Region**: Same as your database
   - **Branch**: `main`
   - **Root Directory**: (leave empty)
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`

   **Plan**:
   - Select **Free** (512 MB RAM, sleeps after 15 min inactivity)

4. Click **"Advanced"** to add environment variables

### Step 4.2: Add Environment Variables

Add these in the **Environment Variables** section:

| Key | Value | Notes |
|-----|-------|-------|
| `DATABASE_URL` | (Auto-filled if you link database) | Links to your PostgreSQL |
| `CORS_SECRET_KEY` | (Generate Random) | Click "Generate" button |
| `RESEND_API_KEY` | `re_your_key_here` | Your Resend API key |
| `PYTHON_VERSION` | `3.11.0` | Python version |

**To link database**:
- Find `DATABASE_URL` → Click **"Add from Database"**
- Select `yoga-booking-db`
- Select **"Internal Connection String"**

### Step 4.3: Deploy

1. Click **"Create Web Service"**
2. **Wait 5-10 minutes** for first deployment
3. Watch the logs - should see:
   ```
   Using postgresql database
   Initializing PostgreSQL connection pool...
   ✅ PostgreSQL connection pool initialized successfully!
   Database initialized successfully
   ```

### Step 4.4: Get Your Render URL

Once deployed, you'll see your URL at the top:
```
https://yoga-booking-system.onrender.com
```

**🎉 Your app is now live on Render!**

---

## 🔀 PHASE 5: Parallel Testing

Now you have **TWO systems running**:

### 🔵 Azure (Original)
- Your current URL/domain
- Original database
- Still serving your users

### 🟢 Render (New)
- `https://yoga-booking-system.onrender.com`
- New PostgreSQL database (with copied data)
- Ready for testing

### Testing Checklist

Test everything on your Render URL:

- [ ] **Login** with existing user
- [ ] **Register** new test user
- [ ] **Email verification** works
- [ ] **View yoga classes**
- [ ] **Book a class**
- [ ] **Cancel booking**
- [ ] **Password reset** (if you have it)
- [ ] **Admin functions** (if any)

### Performance Testing

- [ ] First load (will be slow if sleeping - 30-60 seconds)
- [ ] Subsequent loads (should be fast)
- [ ] Multiple users simultaneously
- [ ] Email delivery speed

**⚠️ Note**: Render free tier sleeps after 15 min inactivity. First visit after sleep takes 30-60 seconds to wake up.

---

## ✂️ PHASE 6: Cutover (Once Confident)

### Option A: Point Domain to Render

If you have a custom domain:

1. **In Render**:
   - Go to your web service → Settings → Custom Domains
   - Add your domain: `www.youryogasite.com`
   - Render will show you DNS records to add

2. **In your DNS provider** (GoDaddy, Namecheap, etc):
   - Update A/CNAME records to point to Render
   - Wait 10-60 minutes for DNS propagation

3. **Test**: Visit your domain - should now show Render version

### Option B: Use Render URL

Just share your Render URL with users:
```
https://yoga-booking-system.onrender.com
```

### Stop Paying for Azure

**Once Render is working perfectly for 1-2 weeks**:

1. **In Azure Portal**:
   - Go to your SQL Database
   - Click **"Delete"**
   - Go to your App Service (if you have one)
   - Click **"Delete"**

2. **Verify**: Check your Azure billing - should drop to $0

3. **Clean up .env**:
   ```env
   # Remove or comment out Azure credentials
   # DB_SERVER=...
   # DB_NAME=...
   # DB_USERNAME=...
   # DB_PASSWORD=...
   ```

---

## 💰 Cost Comparison

### Azure (Before)
- SQL Database: ~$5-15/month
- App Service: ~$0-55/month
- **Total**: $5-70/month

### Render (After)
- Web Service: **$0/month** (Free tier)
- PostgreSQL: **$0/month** (Free tier)
- **Total**: **$0/month** 🎉

---

## 🆘 Troubleshooting

### Export fails: "Can't connect to Azure"

**Solution**:
1. Check `.env` has correct Azure credentials
2. Check Azure firewall allows your IP:
   - Azure Portal → SQL Server → Firewalls
   - Add your current IP address

### Import fails: "Can't connect to PostgreSQL"

**Solution**:
1. Make sure you copied the **Internal Database URL** (not External)
2. URL should start with `postgres://` or `postgresql://`
3. Check Render database status is "Available"

### Render app shows error page

**Solution**:
1. Check Render logs: Dashboard → Your Service → Logs
2. Common issues:
   - Missing environment variable (add `DATABASE_URL`, `CORS_SECRET_KEY`)
   - Database not linked (link in environment variables)
   - Wrong Python version (set `PYTHON_VERSION=3.11.0`)

### First load is very slow (30-60 seconds)

**This is normal** on Render free tier:
- Service sleeps after 15 minutes of inactivity
- Wakes up on first request (takes 30-60 seconds)
- Subsequent requests are fast

**Solutions**:
- Upgrade to paid tier ($7/month) for always-on
- Use a uptime monitor to ping every 10 minutes (keeps it awake)
- Accept the cold start (most users won't mind)

### Emails not sending

**Solution**:
1. Check `RESEND_API_KEY` is set in Render environment variables
2. Verify API key is correct in Resend dashboard
3. Check Render logs for email errors

### Data is missing after import

**Solution**:
1. Re-run export from Azure (to get latest data)
2. Re-run import to Render
3. Check import script output for skipped records

---

## 📞 Need Help?

### Render Documentation
- [Render Docs](https://render.com/docs)
- [Free PostgreSQL Guide](https://render.com/docs/free)

### Common Commands

```bash
# Export from Azure
python export_azure_data.py

# Import to Render
python import_to_render.py

# Test locally with Render database
DATABASE_URL="postgres://..." python app.py

# View Render logs
# (In Render Dashboard → Your Service → Logs)
```

---

## ✅ Migration Complete!

**Congratulations!** You've successfully:
- ✅ Exported all data from Azure
- ✅ Set up free Render hosting
- ✅ Imported all user data (with passwords preserved)
- ✅ Deployed your web application
- ✅ Reduced hosting costs to $0/month

**Your users won't notice any difference** - all their accounts, bookings, and classes are preserved!

---

## 🎯 Next Steps

1. **Monitor**: Check Render logs daily for first week
2. **Test**: Have a few users test the Render version
3. **Optimize**: Consider paid tier if cold starts are annoying
4. **Backup**: Keep Azure running for 1-2 weeks as backup
5. **Delete Azure**: Once confident, delete Azure resources to stop charges

**Good luck with your migration! 🚀**

