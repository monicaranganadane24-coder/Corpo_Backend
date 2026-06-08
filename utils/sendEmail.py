import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

async def send_confirmation_email(to_email: str, subject: str, content: str):
    try:
        sg = SendGridAPIClient(os.getenv("SENDGRID_API_KEY"))
        from_email = os.getenv("MAIL_FROM")

        message = Mail(
            from_email=from_email,
            to_emails=to_email,
            subject=subject,
            html_content=content
        )

        response = sg.send(message)
        print("SendGrid status:", response.status_code)

        return response.status_code == 202

    except Exception as e:
        print("Erreur SendGrid:", e)
        return False
