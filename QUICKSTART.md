# 🚀 Quick Start: Migrate to Render.com

**Want the fastest path to free hosting?** Follow these 3 steps:

---

## ⚡ 3-Step Migration

### 1️⃣ Export from Azure (2 minutes)

```bash
python export_azure_data.py
```

✅ Your data is now backed up locally in `azure_export_YYYYMMDD_HHMMSS/`

---

### 2️⃣ Create Render Services (10 minutes)

**a) Create Database**:
1. Go to [render.com](https://render.com/login) → Sign up/Login
2. Click **New +** → **PostgreSQL**
3. Name: `yoga-booking-db`, Plan: **Free**
4. Click **Create Database**
5. Copy the **Internal Database URL** when ready

**b) Import Your Data**:
```bash
python import_to_render.py
# Paste your DATABASE_URL when prompted
```

**c) Deploy Web App**:
1. Push code to GitHub (if not already)
2. Render Dashboard → **New +** → **Web Service**
3. Connect your GitHub repo
4. Settings:
   - **Build**: `pip install -r requirements.txt`
   - **Start**: `gunicorn app:app`
   - **Plan**: Free
5. **Environment Variables**:
   - `DATABASE_URL`: Add from database (auto-link)
   - `CORS_SECRET_KEY`: Generate
   - `RESEND_API_KEY`: Your Resend key
6. Click **Create Web Service**

---

### 3️⃣ Test Your New Site (5 minutes)

Visit: `https://your-app-name.onrender.com`

**Test**:
- ✅ Login with existing account
- ✅ View classes
- ✅ Book a class
- ✅ Register new user

---

## ✅ Both Systems Running

You now have:
- **Azure**: Still running (users not affected)
- **Render**: New free instance ready for testing

**When ready to switch**: Update your domain DNS or share Render URL

**Then delete Azure** to stop paying! 💰

---

## 📖 Need More Help?

See [MIGRATION_GUIDE.md](./MIGRATION_GUIDE.md) for detailed instructions.

