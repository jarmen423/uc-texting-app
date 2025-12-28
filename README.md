# 📱 Personal Health SMS Bot

A Flask-based backend for a personal health symptom tracking bot that uses SMS as the interface. Your Android phone acts as **"The Mouth"** (sending/receiving SMS), while this Render-hosted backend serves as **"The Brain"** (processing logic and data storage).

---

## 🏗️ Architecture

```
┌─────────────────┐       SMS        ┌─────────────────┐
│   Your Phone    │<---------------->│   User's Phone  │
│   (Android)     │                  │                 │
└────────┬────────┘                  └─────────────────┘
         │
         │ HTTP (Tasker + Join)
         ▼
┌─────────────────┐                  ┌─────────────────┐
│  Flask Backend  │<---------------->│  Google Sheets  │
│   (Render)      │   gspread API    │   (Data Store)  │
└────────┬────────┘                  └─────────────────┘
         │
         │ Scheduled trigger
         ▼
┌─────────────────┐
│   Cron Service  │
│ (cron-job.org)  │
└─────────────────┘
```

---

## ✨ Features

| Command | Action |
|---------|--------|
| Any message with urgency `1-10` | Logs symptoms to Google Sheets |
| `Link` | Returns your Google Sheet URL |
| `Summary` | Returns last 3 symptom entries |

**Daily Check-in**: A cron job triggers a daily SMS prompt asking about your symptoms.

---

## 🚀 Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/YOUR_USERNAME/uc-texting-app.git
cd uc-texting-app
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Create a `.env` file or set these in your Render dashboard:

```env
GOOGLE_CREDENTIALS={"type":"service_account",...}  # Full JSON string
GOOGLE_SHEET_ID=your_sheet_id_from_url
ANDROID_SEND_URL=https://joinjoaomgcd.appspot.com/_ah/api/messaging/v1/sendPush?apikey=...
CRON_SECRET=your_random_secret_string
```

### 3. Run Locally

```bash
python app.py
```

Or with Gunicorn (production):

```bash
gunicorn app:app --bind 0.0.0.0:5000
```

---

## 📲 Tasker Configuration

Configure Tasker on your Android device to forward incoming SMS to the webhook:

### Trigger: Event → Phone → Received Text

### Action: HTTP Request

| Setting | Value |
|---------|-------|
| **Method** | `POST` |
| **URL** | `https://your-app.onrender.com/android-webhook` |
| **Headers** | `Content-Type: application/json` |
| **Body** | `{"sender": "%SMSRF", "body": "%SMSRB"}` |

> **Note**: `%SMSRF` = sender phone number, `%SMSRB` = SMS body text

---

## 🔗 API Endpoints

### `GET /`
Health check endpoint. Returns service status and available endpoints.

### `GET /trigger-daily-checkin?secret=CRON_SECRET`
Triggers the daily symptom check-in SMS. Protected by secret token.

### `POST /android-webhook`
Receives forwarded SMS from Tasker. Expects JSON:
```json
{
  "sender": "+1234567890",
  "body": "Headache today, urgency 7"
}
```

---

## 🔧 Google Sheets Setup

1. Create a Google Cloud project and enable the Google Sheets API
2. Create a service account and download the JSON credentials
3. Create a new Google Sheet with headers: `Date | Time | Body | Urgency`
4. Share the sheet with your service account email (found in credentials JSON)
5. Copy the Sheet ID from the URL: `https://docs.google.com/spreadsheets/d/[SHEET_ID]/edit`

---

## 📦 Dependencies

| Package | Purpose |
|---------|---------|
| `flask` | Web framework |
| `gspread` | Google Sheets API client |
| `oauth2client` | Google authentication |
| `requests` | HTTP client for Join/AutoRemote |
| `gunicorn` | Production WSGI server |

---

## 🚢 Deployment (Render)

1. Push to GitHub
2. Create new Web Service on [Render](https://render.com)
3. Connect your repository
4. Set environment variables in Render dashboard
5. Deploy!

**Build Command**: `pip install -r requirements.txt`  
**Start Command**: `gunicorn app:app`

---

## 📄 License

MIT License - Feel free to modify and use for your own health tracking needs!
