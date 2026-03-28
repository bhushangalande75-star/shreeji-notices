# 🚀 Deploy Society Notice App Online (Free)
## So all committee members can access from anywhere!

---

## What You'll Need
- A **GitHub** account → https://github.com (free)
- A **Render** account → https://render.com (free)
- Your `society_app` folder

---

## STEP 1 — Create GitHub Repository

1. Go to **https://github.com** → Sign up / Log in
2. Click the **"+"** button (top right) → **"New repository"**
3. Name it: `shreeji-notices`
4. Set to **Private** (so code is not public)
5. Click **"Create repository"**

---

## STEP 2 — Upload Your App Files to GitHub

1. On your new repository page, click **"uploading an existing file"**
2. Drag and drop ALL files from your `society_app` folder:
   ```
   app.py
   notice_generator.py
   requirements.txt
   Dockerfile
   render.yaml
   header.png
   templates/
      index.html
      login.html
   ```
3. Click **"Commit changes"**

---

## STEP 3 — Deploy on Render

1. Go to **https://render.com** → Sign up with your GitHub account
2. Click **"New +"** → **"Web Service"**
3. Click **"Connect"** next to your `shreeji-notices` repository
4. Fill in the settings:
   - **Name:** `shreeji-notices`
   - **Region:** Singapore (closest to India)
   - **Branch:** `main`
   - **Runtime:** `Docker` ← IMPORTANT
   - **Plan:** `Free`
5. Scroll down to **"Environment Variables"** → Add:
   - Key: `APP_PASSWORD`  
   - Value: `YourChosenPassword123`  ← Change this!
6. Click **"Create Web Service"**

---

## STEP 4 — Wait for Deployment (~5 minutes)

Render will:
- Install Python ✅
- Install LibreOffice ✅
- Start your app ✅

You'll see: **"Your service is live 🎉"**

Your app URL will be something like:
```
https://shreeji-notices.onrender.com
```

---

## STEP 5 — Share with Committee Members

Send them:
```
🏢 Shreeji Iconic CHS - Notice Generator

Link: https://shreeji-notices.onrender.com
Password: YourChosenPassword123

Steps:
1. Open the link in any browser
2. Enter the password
3. Upload the Excel defaulter sheet
4. Download ZIP + PDF notices
```

---

## ⚠️ Important Notes

| Topic | Detail |
|-------|--------|
| **Free plan sleep** | App sleeps after 15 min of no use. First load takes ~30 sec to wake up. Normal after that. |
| **Password** | Change `APP_PASSWORD` in Render dashboard anytime |
| **Update app** | Push new files to GitHub → Render auto-redeploys |
| **Storage** | Generated files are temporary, deleted after session |

---

## 🔄 How to Update App Later

1. Edit files in your `society_app` folder
2. Go to GitHub → your repository
3. Upload the changed file(s)
4. Render automatically detects changes and redeploys!

---

## ❓ Troubleshooting

| Problem | Solution |
|---------|----------|
| App not loading | Wait 30 sec — free tier wakes up slowly |
| Wrong password | Check `APP_PASSWORD` in Render dashboard |
| PDF not generating | LibreOffice is included in Docker — should work |
| Build failed | Check Render logs → share error with administrator |
