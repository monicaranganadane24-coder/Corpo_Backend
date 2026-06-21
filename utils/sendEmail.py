import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

def send_confirmation_email(to_email: str, subject: str, content: str):
    try:
        api_key      = os.getenv("SENDGRID_API_KEY")
        sender_email = os.getenv("SENDER_EMAIL")

        message = Mail(
            from_email=sender_email,
            to_emails=to_email,
            subject=subject,
            html_content=content
        )

        sg = SendGridAPIClient(api_key)
        response = sg.send(message)

        print(f"✅ Mail envoyé à {to_email} (status {response.status_code})")
        return True

    except Exception as e:
        print(f"⚠️ Erreur envoi mail : {e}")
        return False