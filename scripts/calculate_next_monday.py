from datetime import datetime, timedelta

# Calculate the date of next monday
def calculate_next_monday():
    today = datetime.today()
    # Calculate the number of days until next Monday
    days_until_monday = (7 - today.weekday() + 0) % 7
    if days_until_monday == 0:
        days_until_monday = 7
    next_monday = today + timedelta(days=days_until_monday)
    next_date = next_monday.strftime('%Y-%m-%d')
    print(next_date)

if __name__ == "__main__":
    calculate_next_monday()