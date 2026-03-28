# 🏢 Shreeji Iconic CHS – Notice Generator App

A simple local web app to generate maintenance notices from your Excel sheet.

---

## 📁 Folder Structure

```
society_app/
├── app.py                  ← Main app (run this)
├── notice_generator.py     ← Notice creation logic
├── requirements.txt        ← Python libraries needed
├── header.png              ← ⚠️ Society letterhead image (YOU MUST ADD THIS)
├── templates/
│   └── index.html          ← Web page UI
```

---

## ⚠️ IMPORTANT: Add Your Header Image

Before running the app, copy your society letterhead image into this folder and name it:

```
header.png
```

---

## 🚀 Setup Steps (Do this ONCE)

### Step 1 — Open Terminal in VS Code
- Open VS Code
- Open the `society_app` folder: **File → Open Folder**
- Open terminal: **Terminal → New Terminal**

### Step 2 — Install Python Libraries
Paste this command and press Enter:

```
pip install flask pandas openpyxl python-docx
```

Wait for it to finish (takes 1-2 minutes).

---

## ▶️ Running the App (Every Time)

### Step 1 — Start the App
In VS Code terminal, run:

```
python app.py
```

You should see:
```
✅ Society Notice App running at http://localhost:5000
```

### Step 2 — Open in Browser
Open your browser and go to:
```
http://localhost:5000
```

### Step 3 — Generate Notices
1. Upload your Excel sheet (Defaulter_List.xlsx)
2. Click **⚡ Generate Notices**
3. ZIP file downloads automatically!

### Step 4 — Stop the App
Press **Ctrl + C** in the terminal when done.

---

## 📋 Excel Format Expected

The app reads the Excel in this column order (same as your current sheet):

| Column | Content |
|--------|---------|
| C (col 2) | Flat No |
| E (col 4) | Ref No |
| F (col 5) | Member Name |
| H (col 7) | Amount |

Row 1 is treated as header and skipped automatically.

---

## ❓ Troubleshooting

| Problem | Solution |
|---------|----------|
| `pip` not found | Use `pip3` instead of `pip` |
| Port already in use | Change `5000` to `5001` in app.py |
| Header image missing | Add `header.png` to the folder |
| Excel not reading | Make sure it's `.xlsx` format |
