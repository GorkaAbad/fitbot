import argparse
import json
import time
from datetime import UTC, datetime, timedelta
from datetime import time as day_time
from zoneinfo import ZoneInfo

from client import AimHarderClient
from exceptions import (
    MESSAGE_BOX_IS_CLOSED,
    BookingFailed,
    BoxClosed,
    NoBookingGoal,
    TooSoonToBook,
)
from logger import logger

# Booking may open a few seconds after we fire (clock skew, server lag), so keep trying.
RETRY_TOO_SOON_FOR_SECONDS = 600
RETRY_INTERVAL_SECONDS = 2
# Log in and load classes this long before --book-at, so only the booking request is left.
PREPARE_SECONDS_BEFORE = 60
MADRID = ZoneInfo("Europe/Madrid")


def sleep_until(moment: datetime):
    time.sleep(max(0, (moment - datetime.now(tz=UTC)).total_seconds()))


def get_booking_goal_time(day: datetime, booking_goals):
    """Get the booking goal that satisfies the given day of the week"""
    try:
        return (
            booking_goals[str(day.weekday())]["time"],
            booking_goals[str(day.weekday())]["name"],
        )
    except KeyError:  # did not find a matching booking goal
        raise NoBookingGoal(
            f"There is no booking-goal for {day.strftime('%A, %Y-%m-%d')}."
        )


def get_class_to_book(classes: list[dict], target_time: str, class_name: str):
    if not classes or len(classes) == 0:
        raise BoxClosed(MESSAGE_BOX_IS_CLOSED)

    classes = list(filter(lambda _class: target_time in _class["timeid"], classes))
    _class = list(
        filter(
            lambda _class: class_name.lower() in _class["className"].lower(), classes
        )
    )
    if len(_class) == 0:
        raise NoBookingGoal(
            f"No class with the text `{class_name}` in its name at time `{target_time}`"
        )
    return _class[0]


def main(
    email,
    password,
    booking_goals,
    box_name,
    box_id,
    days_in_advance,
    family_id=None,
    proxy=None,
    book_at=None,
):
    target_day = datetime.now(tz=UTC) + timedelta(days=days_in_advance)
    try:
        target_time, target_name = get_booking_goal_time(target_day, booking_goals)
    except NoBookingGoal as e:
        logger.info(str(e))
        return
    if book_at:
        book_at = datetime.combine(
            datetime.now(tz=MADRID).date(), day_time.fromisoformat(book_at), MADRID
        )
        logger.info(f"Waiting to book at {book_at.isoformat()}")
        sleep_until(book_at - timedelta(seconds=PREPARE_SECONDS_BEFORE))
    client = AimHarderClient(
        email=email, password=password, box_id=box_id, box_name=box_name, proxy=proxy
    )
    classes = client.get_classes(target_day, family_id)
    _class = get_class_to_book(classes, target_time, target_name)
    if _class["bookState"] == 1:
        logger.info("Class already booked. Nothing to do")
        return
    if book_at:
        sleep_until(book_at)
    start = time.monotonic()
    retry_until = time.monotonic() + RETRY_TOO_SOON_FOR_SECONDS
    while True:
        try:
            client.book_class(target_day, _class["id"], family_id)
            break
        except TooSoonToBook as e:
            if time.monotonic() > retry_until:
                logger.error(str(e))
                return
            time.sleep(RETRY_INTERVAL_SECONDS)
        except BookingFailed as e:
            logger.error(str(e))
            return
    logger.info(f"Class booked successfully in {time.monotonic() - start:.2f}s")


if __name__ == "__main__":
    """
    python src/main.py
     --email your.email@mail.com
     --password 1234
     --box-name lahuellacrossfit
     --box-id 3984
     --booking-goal '{"0":{"time": "1815", "name": "Provenza"}}'
     --family-id 123456
     --proxy socks5://89.58.45.94:34472
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True, type=str)
    parser.add_argument("--password", required=True, type=str)
    parser.add_argument("--booking-goals", required=True, type=json.loads)
    parser.add_argument("--box-name", required=True, type=str)
    parser.add_argument("--box-id", required=True, type=int)
    parser.add_argument("--days-in-advance", required=True, type=int, default=3)
    parser.add_argument(
        "--book-at",
        required=False,
        type=str,
        default=None,
        help="Madrid time (HH:MM:SS) to fire the booking at, e.g. 18:15:00 (optional)",
    )
    parser.add_argument("--proxy", required=False, type=str, default=None)
    parser.add_argument(
        "--family-id",
        required=False,
        type=int,
        default=None,
        help="ID of the family member (optional)",
    )
    args = parser.parse_args()
    input = {key: value for key, value in args.__dict__.items() if value != ""}
    main(**input)
