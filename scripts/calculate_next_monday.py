from datetime import datetime, timedelta


def calculate_next_monday():
    today = datetime.today()
    days_until_monday = (7 - today.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 7
    next_monday = today + timedelta(days=days_until_monday)
    print(next_monday.strftime('%Y-%m-%d'))


if __name__ == "__main__":
    calculate_next_monday()
