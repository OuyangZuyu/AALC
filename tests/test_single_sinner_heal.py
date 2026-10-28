"""Targeted-heal recovery and payment contracts; never operate the game."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from module.my_error.my_error import userStopError
from tasks.mirror.single_sinner_heal import HEAL_ENTRY, SHOP, SingleSinnerHeal, portrait_point


class RestartGame(Exception):
    pass


class HealAuto:
    def __init__(self, *, language="en", select_after=1, coins=508, charge=100):
        self.screenshot = SimpleNamespace(size=(1920, 1080))
        self.state = "shop"
        self.language = language
        self.select_after = select_after
        self.attempts = 0
        self.coins = coins
        self.charge = charge
        self.clicks = []
        self.keys = []
        self.payment_count = 0
        self.esc_works = True
        self.capture_count = 0
        self.leave_works = True
        self.lookups = []

    def take_screenshot(self):
        self.capture_count += 1
        assert self.capture_count < 80
        return self.screenshot

    def find_element(self, target):
        assert target in (HEAL_ENTRY, SHOP)
        if target == HEAL_ENTRY and self.state == "shop":
            return 200, 500
        if target == SHOP and self.state == "shop":
            return 1300, 100
        return None

    def find_language_text(self, zh, en, *, my_crop):
        self.lookups.append((zh, en))
        label = zh if self.language == "zh_cn" else en
        options = {"治疗一名罪人", "Greatly heal a single Sinner"}
        select = {"选择", "Select"}
        leave = {"离开", "Leave"}
        if label in options and self.state in {"options", "pick"}:
            point = (1500, 330)
        elif label in select and self.state == "pick" and self.attempts >= self.select_after:
            point = (1700, 990)
        elif label in leave and self.state in {"result", "back"}:
            point = (1700, 990)
        else:
            return None
        return point[0] - my_crop[0], point[1] - my_crop[1]

    def mouse_click(self, x, y):
        self.clicks.append((x, y))
        if (x, y) == (200, 500):
            self.state = "options"
        elif (x, y) == (1500, 330):
            self.state = "pick"
        elif (x, y) == portrait_point(self.screenshot.size, 1):
            self.attempts += 1
        elif (x, y) == (1700, 990):
            if self.state == "pick":
                self.payment_count += 1
                self.coins -= self.charge
                self.state = "result"
            elif self.state in {"result", "back"}:
                if self.leave_works:
                    self.state = "shop"
            else:
                raise AssertionError("Unexpected payment/exit input")
        else:
            raise AssertionError((x, y))

    def key_press(self, key):
        self.keys.append(key)
        if self.esc_works:
            self.state = "back"

    def money(self, *, in_heal):
        assert in_heal == (self.state != "shop")
        return self.coins


def controller(auto, read_money=None):
    pauses = []
    return SingleSinnerHeal(auto, read_money or auto.money, RestartGame, Mock(), pause=pauses.append), pauses


@pytest.mark.parametrize("language", ["en", "zh_cn"])
def test_coin_deduction_is_the_only_completion_check_and_language_is_delegated(language):
    auto = HealAuto(language=language)
    action, pauses = controller(auto)
    result = action.perform()
    assert result.completed
    assert auto.coins == 408 and auto.payment_count == 1
    assert auto.state == "shop" and auto.keys == []
    assert pauses.count(3) == 1
    assert ("选择", "Select") in auto.lookups
    assert all("45" not in zh + en and "Faust" not in zh + en for zh, en in auto.lookups)


def test_below_100_coins_skips_without_opening_heal_or_reading_buttons():
    auto = HealAuto(coins=99)
    result = controller(auto)[0].perform()
    assert result.reason == "insufficient_coins" and not result.completed
    assert auto.clicks == [] and auto.keys == [] and auto.lookups == []


@pytest.mark.parametrize("missing", [None, -1, False])
def test_unknown_money_has_bounded_reads_and_does_not_enter(missing):
    auto = HealAuto()
    reader = Mock(return_value=missing)
    result = controller(auto, reader)[0].perform()
    assert result.reason == "coins_unreadable" and reader.call_count == 3
    assert auto.clicks == [] and auto.keys == []


def test_select_not_seen_repeats_selection_three_times_then_esc_leave():
    auto = HealAuto(select_after=4)
    action, pauses = controller(auto)
    result = action.perform()
    assert not result.completed and result.reason == "select_not_found"
    assert auto.attempts == 3 and pauses.count(3) == 3
    assert auto.payment_count == 0 and auto.keys == ["esc"] and auto.state == "shop"


def test_select_on_third_attempt_pays_only_once():
    auto = HealAuto(select_after=3)
    assert controller(auto)[0].perform().completed
    assert auto.attempts == 3 and auto.payment_count == 1


@pytest.mark.parametrize("charge", [0, 50, 200])
def test_unexpected_or_missing_deduction_does_not_retry_payment(charge):
    auto = HealAuto(charge=charge)
    result = controller(auto)[0].perform()
    assert not result.completed and result.reason == "payment_unconfirmed"
    assert auto.payment_count == 1 and auto.keys == ["esc"] and auto.state == "shop"


def test_money_not_read_after_submission_never_becomes_zero_or_another_payment():
    auto = HealAuto()
    action, _ = controller(auto, lambda **kwargs: None if auto.payment_count else auto.money(**kwargs))
    result = action.perform()
    assert not result.completed and result.reason == "payment_unconfirmed"
    assert auto.payment_count == 1 and auto.state == "shop"


def test_slow_coin_animation_can_be_observed_without_clicking_again():
    auto = HealAuto()
    reads = iter([508, 508, None, 508, 408])
    assert controller(auto, lambda **_: next(reads))[0].perform().completed
    assert auto.payment_count == 1


def test_esc_failure_raises_to_caller_instead_of_resuming_shopping():
    auto = HealAuto(select_after=4)
    auto.esc_works = False
    with pytest.raises(RestartGame, match="Esc"):
        controller(auto)[0].perform()
    assert auto.keys == ["esc"] and auto.payment_count == 0


def test_leave_without_confirmed_shop_raises_to_caller():
    auto = HealAuto()
    auto.leave_works = False
    with pytest.raises(RestartGame, match="返回商店"):
        controller(auto)[0].perform()
    assert auto.payment_count == 1


def test_none_capture_never_reuses_stale_frame_or_waits_forever():
    auto = HealAuto()
    auto.take_screenshot = Mock(return_value=None)
    result = controller(auto)[0].perform()
    assert result.reason == "coins_unreadable"
    assert auto.take_screenshot.call_count == 3 and auto.clicks == []


def test_capture_failure_after_entry_is_bounded_and_recovery_escalates():
    auto = HealAuto()
    auto.take_screenshot = lambda: auto.screenshot if auto.state == "shop" else None
    with pytest.raises(RestartGame, match="Esc"):
        controller(auto)[0].perform()
    assert auto.keys == ["esc"] and auto.payment_count == 0


def test_search_none_is_a_miss_not_an_unpack_exception():
    auto = HealAuto()
    auto.find_language_text = Mock(return_value=None)
    with pytest.raises(RestartGame):  # All lookups fail, including escape's Leave.
        controller(auto)[0].perform()
    assert auto.payment_count == 0 and auto.keys == ["esc"]


def test_user_stop_is_never_treated_as_a_miss_or_restart():
    auto = HealAuto()
    auto.find_language_text = Mock(side_effect=userStopError("stop"))
    with pytest.raises(userStopError):
        controller(auto)[0].perform()
    assert auto.keys == [] and auto.payment_count == 0


def test_input_failure_in_shallow_cleanup_becomes_restart_request():
    auto = HealAuto(select_after=4)
    auto.key_press = Mock(side_effect=OSError("input unavailable"))
    with pytest.raises(RestartGame, match="退出治疗页面失败"):
        controller(auto)[0].perform()
    assert auto.payment_count == 0
