import datetime
from contextlib import nullcontext as does_not_raise
from http import HTTPStatus
from unittest.mock import Mock, patch

import pytest
from freezegun import freeze_time

from constants import LOGIN_ENDPOINT, book_endpoint
from exceptions import BoxClosed, NoBookingGoal
from main import get_booking_goal_time, get_class_to_book, main


class TestGetBookingGoalTime:
    @pytest.mark.parametrize(
        "day, booking_goals, expected_time, expectation",
        (
            (
                datetime.datetime(2022, 2, 28, tzinfo=datetime.UTC),
                {"0": {"time": "1700", "name": "foo"}},
                ("1700", "foo"),
                does_not_raise(),
            ),
            (
                datetime.datetime(2022, 2, 28, tzinfo=datetime.UTC),
                {},
                None,
                pytest.raises(NoBookingGoal),
            ),
        ),
    )
    def test_get_booking_goal_time(
        self, day, booking_goals, expected_time, expectation
    ):
        with expectation:
            assert get_booking_goal_time(day, booking_goals) == expected_time


class TestGetClassToBook:
    @pytest.mark.parametrize(
        "classes, target_time, class_name, expectation",
        (
            (
                [{"id": 123, "timeid": "1700_60", "className": "foo"}],
                "1700",
                "foo",
                does_not_raise(),
            ),
            (
                [
                    {"id": 123, "timeid": "1700_60", "className": "foo"},
                    {"id": 123, "timeid": "1700_60", "className": "foo"},
                ],
                "1700",
                "foo",
                does_not_raise(),
            ),
            (
                [{"id": 123, "timeid": "1700_60", "className": "foo"}],
                "1700",
                "FOO",
                does_not_raise(),
            ),
            (
                [{"id": 123, "timeid": "1100_60", "className": "foo"}],
                "1700",
                "foo",
                pytest.raises(NoBookingGoal),
            ),
            (
                [],
                "1700",
                "foo",
                pytest.raises(BoxClosed),
            ),
        ),
    )
    def test_get_class_to_book(self, classes, target_time, class_name, expectation):
        with expectation:
            assert get_class_to_book(classes, target_time, class_name) == {
                "id": 123,
                "timeid": "1700_60",
                "className": "foo",
            }


class TestMain:
    def mock_request_post(*args, **kwargs):
        if args[1] == LOGIN_ENDPOINT:
            return Mock(status_code=HTTPStatus.OK)
        elif args[1] == book_endpoint("foo"):
            return Mock(json=dict, status_code=HTTPStatus.OK)

    @freeze_time("2022-03-04")
    def test_main(self):
        with (
            patch("requests.Session.post") as m_post,
            patch("requests.Session.get") as m_get,
        ):
            m_post.side_effect = self.mock_request_post
            m_get.return_value.json.return_value = {
                "bookings": [
                    {
                        "id": 123,
                        "timeid": "1700_60",
                        "className": "Provenza",
                        "bookState": None,
                    }
                ]
            }
            main(
                email="foo",
                password="bar",
                booking_goals={"0": {"time": "1700", "name": "Provenza"}},
                box_name="foo",
                box_id=1,
                days_in_advance=3,
            )

    @freeze_time("2022-03-04")
    def test_main_retries_while_too_soon(self):
        with (
            patch("requests.Session.post") as m_post,
            patch("requests.Session.get") as m_get,
            patch("main.time.sleep") as m_sleep,
        ):
            book_responses = iter([{"bookState": -12}, {"bookState": -12}, {}])

            def post(url, **kwargs):
                if url == LOGIN_ENDPOINT:
                    return Mock(status_code=HTTPStatus.OK)
                return Mock(
                    json=lambda: next(book_responses), status_code=HTTPStatus.OK
                )

            m_post.side_effect = post
            m_get.return_value.json.return_value = {
                "bookings": [
                    {
                        "id": 123,
                        "timeid": "1700_60",
                        "className": "Provenza",
                        "bookState": None,
                    }
                ]
            }
            main(
                email="foo",
                password="bar",
                booking_goals={"0": {"time": "1700", "name": "Provenza"}},
                box_name="foo",
                box_id=1,
                days_in_advance=3,
            )
            assert m_sleep.call_count == 2
            assert next(book_responses, None) is None

    @freeze_time("2022-03-04 15:00:00")  # 16:00 Madrid (winter, UTC+1)
    def test_main_waits_until_book_at(self):
        with (
            patch("requests.Session.post") as m_post,
            patch("requests.Session.get") as m_get,
            patch("main.time.sleep") as m_sleep,
        ):
            m_post.side_effect = self.mock_request_post
            m_get.return_value.json.return_value = {
                "bookings": [
                    {
                        "id": 123,
                        "timeid": "1700_60",
                        "className": "Provenza",
                        "bookState": None,
                    }
                ]
            }
            main(
                email="foo",
                password="bar",
                booking_goals={"0": {"time": "1700", "name": "Provenza"}},
                box_name="foo",
                box_id=1,
                days_in_advance=3,
                book_at="18:15:00",
            )
            # 18:15 Madrid = 17:15 UTC: prepare a minute before, then fire on the dot
            assert [c.args[0] for c in m_sleep.call_args_list] == [8040, 8100]
