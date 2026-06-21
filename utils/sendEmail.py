import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os

async def send_confirmation_email(to_email: str, subject: str, content: str):
    try:
        smtp_user     = os.getenv("GMAIL_USER")     # monicaranganadane24@gmail.com
        smtp_password = os.getenv("GMAIL_PASSWORD") # mot de passe d'application Google

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = smtp_user
        msg["To"]      = to_email

        msg.attach(MIMEText(content, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, to_email, msg.as_string())

        print(f"✅ Mail envoyé à {to_email}")
        return True

    except Exception as e:
        print(f"⚠️ Erreur envoi mail : {e}")
        return False