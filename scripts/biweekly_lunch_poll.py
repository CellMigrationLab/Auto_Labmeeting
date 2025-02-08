from utils import send_slack_message
import argparse

# Main function
def main(token, channel):
    message = """
                Would you like to go this Friday for a together lunch?
                :+1:  : Yes, count on me!
                :-1:  : Nah, not this time :(
            """
    send_slack_message(token, channel, message)

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Send a weekly reminder to Slack to update the slides.')
    parser.add_argument('--token', required=True, help='Slack API token')
    parser.add_argument('--channel', required=True, help='Slack channel ID')
    
    args = parser.parse_args()

    main(token=args.token, channel=args.channel)