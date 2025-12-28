"""
Personal Health SMS Bot - Flask Backend
========================================

TASKER CONFIGURATION FOR /android-webhook ENDPOINT:
====================================================
When configuring Tasker to forward incoming SMS to this webhook,
send a POST request with the following JSON structure:

    URL: https://your-render-app.onrender.com/android-webhook
    Method: POST
    Content-Type: application/json
    Body:
    {
        "sender": "%SMSRF",      <- Tasker variable for sender phone number
        "body": "%SMSRB"         <- Tasker variable for SMS body text
    }

Tasker Action: "HTTP Request"
    - Method: POST
    - URL: https://your-app.onrender.com/android-webhook
    - Headers: Content-Type: application/json
    - Body: {"sender": "%SMSRF", "body": "%SMSRB"}

EXPECTED INCOMING MESSAGE FORMATS:
==================================
1. Data Entry (symptoms):
   - Any message containing a number 1-10 will be parsed as urgency rating
   - Example: "Headache today, urgency 7" -> Logs with urgency 7

2. Retrieval Commands:
   - "Link" -> Responds with Google Sheet URL
   - "Summary" -> Responds with last 3 symptom entries

ENVIRONMENT VARIABLES REQUIRED:
===============================
- GOOGLE_CREDENTIALS: JSON string of Google service account credentials
- ANDROID_SEND_URL: Join/AutoRemote URL to trigger SMS send on Android
- CRON_SECRET: Secret token to authenticate cron trigger requests
- GOOGLE_SHEET_ID: The ID of your Google Sheet (from the URL)
"""

import os
import json
import re
from datetime import datetime
from urllib.parse import urlencode, quote

from flask import Flask, request, jsonify
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests

app = Flask(__name__)

# ==============================================================================
# CONFIGURATION
# ==============================================================================

GOOGLE_CREDENTIALS = os.environ.get("GOOGLE_CREDENTIALS")
ANDROID_SEND_URL = os.environ.get("ANDROID_SEND_URL")
CRON_SECRET = os.environ.get("CRON_SECRET")
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")

# ==============================================================================
# GOOGLE SHEETS SETUP
# ==============================================================================

def get_google_sheet():
    """
    Authenticate with Google Sheets API and return the active worksheet.
    
    This function handles the complete OAuth2 authentication flow with Google's
    Sheets API using service account credentials. It parses credentials from the
    GOOGLE_CREDENTIALS environment variable, establishes an authorized session,
    and returns the first worksheet of the configured spreadsheet.
    
    This is the central data access layer for the symptom logging system,
    called by both `append_symptom_log` for writes and `get_last_entries` for reads.
    
    Returns:
        gspread.Worksheet: The first worksheet of the configured Google Sheet,
            ready for read/write operations.
    
    Raises:
        ValueError: If GOOGLE_CREDENTIALS or GOOGLE_SHEET_ID environment
            variables are not set.
        json.JSONDecodeError: If GOOGLE_CREDENTIALS contains invalid JSON.
        gspread.exceptions.SpreadsheetNotFound: If the sheet ID doesn't exist
            or the service account lacks access.
    
    Key Technologies:
        - gspread: Google Sheets API client library
        - oauth2client: ServiceAccountCredentials for authentication
    """
    if not GOOGLE_CREDENTIALS:
        raise ValueError("GOOGLE_CREDENTIALS environment variable not set")
    
    if not GOOGLE_SHEET_ID:
        raise ValueError("GOOGLE_SHEET_ID environment variable not set")
    
    # Parse credentials from JSON string
    creds_dict = json.loads(GOOGLE_CREDENTIALS)
    
    # Define scope for Google Sheets API
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    # Authenticate
    credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(credentials)
    
    # Open sheet by ID and return first worksheet
    spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)
    return spreadsheet.sheet1


def append_symptom_log(body: str, urgency: int) -> bool:
    """
    Append a symptom entry to the Google Sheets log.
    
    Creates a new row in the symptom tracking spreadsheet with the current
    timestamp and provided symptom data. This function is called from the
    `/android-webhook` endpoint when a user sends a symptom report via SMS.
    
    Args:
        body: The raw SMS message text containing the symptom description.
            This is stored as-is without modification.
        urgency: Urgency rating from 1 (mild) to 10 (severe), extracted
            from the user's SMS message.
    
    Returns:
        bool: True if the row was successfully appended.
    
    Raises:
        gspread.exceptions.APIError: If Google Sheets API request fails.
    
    Key Technologies:
        - gspread.Worksheet.append_row: Atomic row append operation
    """
    sheet = get_google_sheet()
    now = datetime.now()
    row = [
        now.strftime("%Y-%m-%d"),  # Date
        now.strftime("%H:%M:%S"),  # Time
        body,                       # Symptom description
        urgency                     # Urgency rating 1-10
    ]
    sheet.append_row(row)
    return True


def get_last_entries(count: int = 3) -> list[dict]:
    """
    Retrieve the most recent symptom entries from the log.
    
    Fetches all data from the Google Sheet and returns the last N entries.
    This function is called from the `/android-webhook` endpoint when a
    user sends the "Summary" command via SMS.
    
    Args:
        count: Number of recent entries to retrieve. Defaults to 3.
    
    Returns:
        list[dict]: A list of dictionaries, each containing:
            - "date" (str): Entry date in YYYY-MM-DD format
            - "time" (str): Entry time in HH:MM:SS format 
            - "body" (str): The symptom description text
            - "urgency" (str): The urgency rating as a string
            Returns empty list if no entries exist.
    
    Key Technologies:
        - gspread.Worksheet.get_all_values: Fetches entire sheet content
    """
    sheet = get_google_sheet()
    all_values = sheet.get_all_values()
    
    # Skip header row if present, get last N rows
    if len(all_values) <= 1:
        return []
    
    data_rows = all_values[1:]  # Skip header
    last_rows = data_rows[-count:] if len(data_rows) >= count else data_rows
    
    entries = []
    for row in last_rows:
        if len(row) >= 4:
            entries.append({
                "date": row[0],
                "time": row[1],
                "body": row[2],
                "urgency": row[3]
            })
    return entries


def get_sheet_url() -> str:
    """
    Generate the public URL for the Google Sheet.
    
    Constructs the direct link to the symptom tracking spreadsheet using
    the configured GOOGLE_SHEET_ID. Called when user sends "Link" command.
    
    Returns:
        str: The full Google Sheets URL for the configured spreadsheet.
    """
    return f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}"

# ==============================================================================
# SMS SENDING LOGIC
# ==============================================================================

def send_sms_via_android(message_text: str) -> bool:
    """
    Send SMS through Android phone via Join/AutoRemote push notification.
    
    Makes a GET request to ANDROID_SEND_URL with URL-encoded message.
    The URL should be a Join push URL or AutoRemote endpoint configured
    to trigger a Tasker task that sends the SMS. This is the gateway for
    all outbound SMS communication from the bot.
    
    Args:
        message_text: The SMS content to send. Will be URL-encoded
            automatically before transmission.
    
    Returns:
        bool: True if the push request succeeded (HTTP 2xx), False if
            ANDROID_SEND_URL is not configured or request failed.
    
    Key Technologies:
        - requests: HTTP library for the GET request
        - urllib.parse.quote: URL encoding for the message text
        - Join/AutoRemote: Cloud-to-device push notification services
    """
    if not ANDROID_SEND_URL:
        app.logger.error("ANDROID_SEND_URL not configured")
        return False
    
    try:
        # URL-encode the message and append to the base URL
        # Join URLs typically use ?text= parameter
        encoded_message = quote(message_text)
        
        # Check if URL already has query params
        separator = "&" if "?" in ANDROID_SEND_URL else "?"
        full_url = f"{ANDROID_SEND_URL}{separator}text={encoded_message}"
        
        response = requests.get(full_url, timeout=10)
        response.raise_for_status()
        
        app.logger.info(f"SMS sent successfully: {message_text[:50]}...")
        return True
        
    except requests.RequestException as e:
        app.logger.error(f"Failed to send SMS via Android: {e}")
        return False

# ==============================================================================
# ROUTES
# ==============================================================================

@app.route("/")
def index():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "service": "Personal Health SMS Bot",
        "endpoints": [
            "GET /trigger-daily-checkin?secret=YOUR_SECRET",
            "POST /android-webhook"
        ]
    })


@app.route("/trigger-daily-checkin", methods=["GET"])
def trigger_daily_checkin():
    """
    Cron-triggered endpoint to send daily check-in SMS.
    
    Security: Requires ?secret=CRON_SECRET query parameter.
    Action: Sends symptom check-in prompt to user via Android.
    
    Usage: Set up a cron job (e.g., cron-job.org) to hit this endpoint daily.
    """
    # Validate secret
    provided_secret = request.args.get("secret")
    
    if not CRON_SECRET:
        return jsonify({"error": "CRON_SECRET not configured on server"}), 500
    
    if provided_secret != CRON_SECRET:
        return jsonify({"error": "Invalid or missing secret"}), 403
    
    # Send the daily check-in prompt
    message = "How were your symptoms today? Rate urgency (1-10) and describe."
    success = send_sms_via_android(message)
    
    if success:
        return jsonify({
            "status": "success",
            "message": "Daily check-in sent"
        })
    else:
        return jsonify({
            "status": "error",
            "message": "Failed to send SMS"
        }), 500


@app.route("/android-webhook", methods=["POST"])
def android_webhook():
    """
    Webhook endpoint for receiving SMS forwarded from Android/Tasker.
    
    Expected JSON payload:
    {
        "sender": "PHONE_NUMBER",  <- The phone number that sent the SMS
        "body": "SMS_CONTENT"      <- The text content of the SMS
    }
    
    Logic Branches:
    A) Data Entry: If message contains symptom data with urgency (1-10),
       log to Google Sheets and confirm.
    B) Retrieval - "Link": Respond with Google Sheet URL.
    C) Retrieval - "Summary": Respond with last 3 symptom entries.
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "No JSON payload received"}), 400
        
        sender = data.get("sender", "unknown")
        body = data.get("body", "").strip()
        
        if not body:
            return jsonify({"error": "Empty message body"}), 400
        
        app.logger.info(f"Received SMS from {sender}: {body}")
        
        body_lower = body.lower()
        
        # ----- Branch B: Retrieval - Link -----
        if "link" in body_lower:
            sheet_url = get_sheet_url()
            send_sms_via_android(f"📊 Your symptom log: {sheet_url}")
            return jsonify({
                "status": "success",
                "action": "sent_link"
            })
        
        # ----- Branch B: Retrieval - Summary -----
        if "summary" in body_lower:
            entries = get_last_entries(3)
            
            if not entries:
                send_sms_via_android("No symptom entries recorded yet.")
            else:
                summary_lines = ["📋 Last 3 entries:"]
                for entry in entries:
                    summary_lines.append(
                        f"• {entry['date']}: {entry['body'][:30]}... (Urgency: {entry['urgency']})"
                    )
                summary_text = "\n".join(summary_lines)
                send_sms_via_android(summary_text)
            
            return jsonify({
                "status": "success",
                "action": "sent_summary",
                "entries_count": len(entries)
            })
        
        # ----- Branch A: Data Entry (Symptom Logging) -----
        # Look for urgency rating (1-10) in the message
        urgency_match = re.search(r'\b(10|[1-9])\b', body)
        
        if urgency_match:
            urgency = int(urgency_match.group(1))
            
            # Log to Google Sheets
            append_symptom_log(body, urgency)
            
            # Send confirmation
            send_sms_via_android("Logged. ✅")
            
            return jsonify({
                "status": "success",
                "action": "logged_symptom",
                "urgency": urgency
            })
        
        # ----- Fallback: Unrecognized command -----
        send_sms_via_android(
            "I didn't understand that. Send:\n"
            "• Symptoms with urgency 1-10 to log\n"
            "• 'Link' for spreadsheet URL\n"
            "• 'Summary' for recent entries"
        )
        
        return jsonify({
            "status": "success",
            "action": "sent_help"
        })
        
    except json.JSONDecodeError:
        return jsonify({"error": "Invalid JSON payload"}), 400
    except Exception as e:
        app.logger.error(f"Error processing webhook: {e}")
        return jsonify({"error": str(e)}), 500


# ==============================================================================
# ENTRY POINT
# ==============================================================================

if __name__ == "__main__":
    # Local development only - use gunicorn in production
    app.run(debug=True, host="0.0.0.0", port=5000)
