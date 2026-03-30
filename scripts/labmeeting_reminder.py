from utils import send_slack_message
from schedule_config import get_skip_info

import argparse
from datetime import datetime


# Main function
def main(token, channel, date):
    skip_info = get_skip_info(date)
    if skip_info:
        message = skip_info['message']
    else:
        message = "Remember to update today´s slides with your information :D"
    send_slack_message(token, channel, message)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Send a weekly reminder to Slack to update the slides.')
    parser.add_argument('--token', required=True, help='Slack API token')
    parser.add_argument('--channel', required=True, help='Slack channel ID')
    parser.add_argument(
        '--date',
        required=False,
        default=datetime.today().strftime('%Y-%m-%d'),
        help='Meeting date in YYYY-MM-DD format. Defaults to today.'
    )

    args = parser.parse_args()

    main(token=args.token, channel=args.channel, date=args.date)
