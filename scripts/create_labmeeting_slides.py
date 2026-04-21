from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from utils import send_slack_message, create_ppt_with_date_and_members, upload_to_drive, create_shareable_link
from schedule_config import get_presenters_for_date, get_skip_info

import argparse
import json
import os


def build_regular_message(link, date, presenters, zoom_link=''):
    message = f"Here is the link to next week's slides ({date}): {link}"
    message += "\nThe presenters for next week are:\n"
    for presenter in presenters:
        message += f"- {presenter}\n"
    if zoom_link:
        message += f"\nLink to the Zoom meeting: {zoom_link}"
    return message


# Main function
def main(token, channel, link, date, zoom_link='', presenters=None, custom_message=''):
    if custom_message:
        send_slack_message(token, channel, custom_message)
        return

    presenters = presenters or []
    message = build_regular_message(link=link, date=date, presenters=presenters, zoom_link=zoom_link)
    send_slack_message(token, channel, message)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Send a weekly reminder to Slack with a link to slides.')
    parser.add_argument('--token', required=True, help='Slack API token')
    parser.add_argument('--channel', required=True, help='Slack channel ID')
    parser.add_argument('--date', required=True, help='Date')
    parser.add_argument('--zoom', required=False, help='Link to Zoom meeting')
    parser.add_argument(
        '--schedule-config',
        required=False,
        default=None,
        help='Path to the JSON file that defines presenter rotation and skipped dates.'
    )

    args = parser.parse_args()
    date = args.date
    zoom_link = args.zoom or ''

    skip_info = get_skip_info(date, config_path=args.schedule_config)
    if skip_info:
        main(
            token=args.token,
            channel=args.channel,
            link='',
            date=date,
            zoom_link=zoom_link,
            presenters=[],
            custom_message=skip_info['message'],
        )
        raise SystemExit(0)

    lab_members = get_presenters_for_date(date, config_path=args.schedule_config)

    SCOPES = ['https://www.googleapis.com/auth/drive.file']

    creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise RuntimeError(
                "token.json is invalid and cannot be refreshed. Recreate it locally."
            )

    service = build("drive", "v3", credentials=creds)
    FOLDER_ID = os.getenv("FOLDER_ID")

    # Folder to temporary store the presentation
    save_path = "presentations/"
    os.makedirs(save_path, exist_ok=True)

    filename = f"{date}_Quick_Presentation.pptx"
    file_path = create_ppt_with_date_and_members(date, save_path, filename, lab_members)
    file_id = upload_to_drive(service, file_path, filename, FOLDER_ID)
    shareable_link = create_shareable_link(service, file_id)

    main(
        token=args.token,
        channel=args.channel,
        link=shareable_link,
        date=args.date,
        zoom_link=zoom_link,
        presenters=lab_members,
    )
