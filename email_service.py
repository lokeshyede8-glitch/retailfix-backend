import os
import requests
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

BREVO_API_KEY = os.getenv("BREVO_API_KEY")
BREVO_SENDER_NAME = os.getenv("BREVO_SENDER_NAME", "RetailFix CRM")
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL")

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def send_otp_email(recipient_email: str, recipient_name: str, otp: str) -> bool:
    """Send password reset OTP email using Brevo Transactional Email API."""
    if not BREVO_API_KEY:
        logger.error("BREVO_API_KEY not configured in environment variables.")
        return False
    if not BREVO_SENDER_EMAIL:
        logger.error("BREVO_SENDER_EMAIL not configured in environment variables.")
        return False

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Reset Your Password - RetailFix CRM</title>
  <style>
    body {{
      font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
      background-color: #f3f4f6;
      margin: 0;
      padding: 0;
      -webkit-font-smoothing: antialiased;
    }}
    .wrapper {{
      width: 100%;
      background-color: #f3f4f6;
      padding: 40px 20px;
      box-sizing: border-box;
    }}
    .container {{
      max-width: 600px;
      margin: 0 auto;
      background-color: #ffffff;
      border-radius: 12px;
      overflow: hidden;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
    }}
    .header {{
      background: linear-gradient(135deg, #1e3a8a 0%, #2563eb 100%);
      padding: 30px 20px;
      text-align: center;
    }}
    .header h1 {{
      color: #ffffff;
      margin: 0;
      font-size: 24px;
      font-weight: 700;
      letter-spacing: 0.5px;
    }}
    .content {{
      padding: 40px 30px;
      color: #374151;
      line-height: 1.6;
    }}
    .content h2 {{
      font-size: 20px;
      color: #111827;
      margin-top: 0;
      margin-bottom: 20px;
    }}
    .otp-container {{
      background-color: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 8px;
      padding: 20px;
      margin: 30px 0;
      text-align: center;
    }}
    .otp-code {{
      font-size: 36px;
      font-weight: 800;
      letter-spacing: 6px;
      color: #2563eb;
      margin: 0;
    }}
    .expiry-text {{
      font-size: 14px;
      color: #6b7280;
      margin-top: 10px;
      margin-bottom: 0;
    }}
    .footer {{
      background-color: #f9fafb;
      padding: 20px;
      text-align: center;
      border-top: 1px solid #e5e7eb;
      font-size: 12px;
      color: #9ca3af;
    }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="container">
      <div class="header">
        <h1>RetailFix CRM</h1>
      </div>
      <div class="content">
        <h2>Password Reset Request</h2>
        <p>Hello {recipient_name},</p>
        <p>We received a request to reset the password for your RetailFix CRM account. Use the following One-Time Password (OTP) to proceed with your password reset:</p>
        <div class="otp-container">
          <div class="otp-code">{otp}</div>
          <p class="expiry-text">This OTP is valid for <strong>10 minutes</strong>. Do not share this code with anyone.</p>
        </div>
        <p>If you did not request a password reset, you can safely ignore this email. Your password will remain unchanged.</p>
        <p>Best regards,<br><strong>RetailFix Support Team</strong></p>
      </div>
      <div class="footer">
        <p>This is an automated email. Please do not reply directly to this message.</p>
        <p>&copy; 2026 RetailFix CRM. All rights reserved.</p>
      </div>
    </div>
  </div>
</body>
</html>
"""

    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json",
    }

    payload = {
        "sender": {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
        "to": [{"email": recipient_email, "name": recipient_name}],
        "subject": "Password Reset OTP - RetailFix CRM",
        "htmlContent": html_content,
    }

    try:
        response = requests.post(BREVO_API_URL, json=payload, headers=headers, timeout=15)
        if response.status_code in [200, 201, 202]:
            logger.info(f"Successfully sent OTP email to {recipient_email}")
            return True
        else:
            logger.error(
                f"Failed to send email to {recipient_email}. Status code: {response.status_code}, Response: {response.text}"
            )
            return False
    except Exception as e:
        logger.error(f"Error while calling Brevo API: {e}")
        return False
