from google.oauth2 import service_account
from googleapiclient.discovery import build

from utils import send_slack_message, create_ppt_with_date_and_members, upload_to_drive, create_shareable_link

import argparse
import os

# Main function
def main(token, channel, link, date):
    message = f"Here is the link to next week's slides ({date}): {link}"
    send_slack_message(token, channel, message)

if __name__ == "__main__":
    import argparse
    import random
    import json
    
    parser = argparse.ArgumentParser(description='Send a weekly reminder to Slack with a link to slides.')
    parser.add_argument('--token', required=True, help='Slack API token')
    parser.add_argument('--channel', required=True, help='Slack channel ID')
    parser.add_argument('--date', required=True, help='Date')
    
    args = parser.parse_args()
    date = args.date

    # List of lab members
    lab_members = ["Guillaume", "Gautier", "Jaakko", "Ana", "Sujan", "Sarah", "Monika", "Marcela", "Iván", "Daniil", "Helene", "Hiba", "Marjaana", "Christine", "Adan"]

    # Randomly rotate the order of the lab members
    random.shuffle(lab_members)

    # Get the values for the connection with Google Drive´s API
    SCOPES = ['https://www.googleapis.com/auth/drive.file']
    SERVICE_ACCOUNT_JSON = os.getenv('SERVICE_ACCOUNT_JSON')
    FOLDER_ID = os.getenv('FOLDER_ID')

    # # Get the credentials from Google Drive´s API
    credentials = service_account.Credentials.from_service_account_info(json.loads(SERVICE_ACCOUNT_JSON), scopes=SCOPES)
    service = build('drive', 'v3', credentials=credentials)

    # Folder to temporary store the presentaiton
    save_path = "presentations/"
    os.makedirs(save_path, exist_ok=True)

    # Dictionary to store dates and links
    links_dict = {}

    filename = f"{date}_5min_Presentation.pptx"
    file_path = create_ppt_with_date_and_members(date, save_path, filename, lab_members)
    file_id = upload_to_drive(service, file_path, filename, FOLDER_ID)
    shareable_link = create_shareable_link(service, file_id)

    main(token=args.token, channel=args.channel, link=shareable_link, date=args.date)
