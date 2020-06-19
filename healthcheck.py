import requests
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime


def health_check(url):
    try:
        response = requests.get(url)
        print(response.status_code)
        if response.status_code == 200:
            return True
        else:
            return False
    except:
        return False


def send_alert(email, htmlPayload):
    # The mail addresses and password
    sender_address = "litecoin.notifier.bot@gmail.com"
    # TODO: Pass password as argument
    sender_pass = "password"
    receiver_address = email
    # Setup the MIME
    message = MIMEMultipart()
    message['From'] = sender_address
    message['To'] = receiver_address
    message['Subject'] = 'LitecoinNotifierBot alert'
    # The body and the attachments for the mail
    message.attach(MIMEText(htmlPayload, 'html'))
    # Create SMTP session for sending the mail
    session = smtplib.SMTP('smtp.gmail.com', 587)  # use gmail with port
    session.starttls()  # enable security
    session.login(sender_address, sender_pass)  # login with mail_id and password
    text = message.as_string()
    session.sendmail(sender_address, receiver_address, text)
    session.quit()


if __name__ == '__main__':
    litecoinNotifierURL = "http://localhost:8000"
    alertEmail = "davide.vezzani1@studenti.unipr.it"

    try:
        with open("last_status", "r") as f:
            previousStatus = f.read()
    except:
        previousStatus = "DOWN"

    with open("last_status", "w") as f:
        if not health_check(litecoinNotifierURL):
            print("Server is DOWN")
            # Sends down alert only if the server was previously up
            if previousStatus == "UP":
                print("Server was previously UP, sending alert...")
                message = """
                    <p style="color: red;">LitecoinNotifierBot is DOWN!</p>
                    I could not reach the server. The last attempt was made at %s.
                    """ % datetime.now().isoformat()
                send_alert(alertEmail, message)
            f.write("DOWN")
        else:
            print("Server is UP")
            # Sends down alert only if the server was previously up
            if previousStatus == "DOWN":
                print("Server was previously DOWN, sending alert...")
                message = """
                    <p style="color: green;">LitecoinNotifierBot is UP again!</p>
                    """
                send_alert(alertEmail, message)
            f.write("UP")

