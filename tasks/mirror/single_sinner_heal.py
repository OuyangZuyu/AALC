"""Opt-in single-sinner treatment; ordinary whole-party treatment is unchanged."""

from dataclasses import dataclass
from math import isfinite
from time import sleep

from module.my_error.my_error import userStopError

HEAL_ENTRY = "mirror/shop/heal_sinner/heal_sinner_assets.png"
SHOP = "mirror/shop/shop_coins_assets.png"


@dataclass(frozen=True)
class HealResult:
    completed: bool
    reason: str
    shop_ready: bool = True


def portrait_point(size, index):
    """Client-relative layout measured in the user's 2026-10-28 recording.

    The healing screen has its own portrait spacing, unlike the event screen.
    No desktop origin, title bar, or particular identity artwork is used.
    """
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < 12:
        raise ValueError("罪人编号必须为 0 到 11")
    width, height = size
    return round(width * (150 + 116 * index) / 1944), round(height * .91)


class SingleSinnerHeal:
    """A bounded inner action; cleanup failure propagates to its caller.

    Search misses (None/False/empty) never become coordinates. Three selection
    attempts are allowed, but a submitted payment is never repeated. The only
    success criterion is the expected before/after coin deduction.
    """

    def __init__(self, auto, read_money, restart_error, logger, *, pause=sleep):
        self.auto = auto
        self.read_money = read_money
        self.restart_error = restart_error
        self.log = logger
        self.pause = pause

    def _probe(self, operation, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except (userStopError, self.restart_error):
            raise
        except Exception as error:
            self.log.debug(f"单人治疗识别失败，按未命中处理：{error}")
            return None

    def _capture(self):
        # Never use the old auto.screenshot after a failed fresh capture.
        return self._probe(self.auto.take_screenshot) is not None

    def _money(self, in_heal):
        value = self._probe(self.read_money, in_heal=in_heal)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return value

    def _button(self, zh, en, *, bottom=False):
        width, height = self.auto.screenshot.size
        box = ((round(width * .78), round(height * .84), width, height) if bottom else
               (round(width * .63), round(height * .18), round(width * .97), round(height * .43)))
        point = self._probe(self.auto.find_language_text, zh, en, my_crop=box)
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            return None
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)
                   for value in point):
            return None
        x, y = point
        if not 0 <= x < box[2] - box[0] or not 0 <= y < box[3] - box[1]:
            return None
        return x + box[0], y + box[1]

    def _close(self, *, escape):
        try:
            self._return_to_shop(escape=escape)
        except (userStopError, self.restart_error):
            raise
        except Exception as error:
            # Cleanup itself is the shallow fallback. If its inputs fail, do
            # not leak an unrelated exception or resume on an unknown page.
            raise self.restart_error("单人治疗：退出治疗页面失败") from error

    def _return_to_shop(self, *, escape):
        if escape:
            self.auto.key_press("esc")
        for _ in range(6):
            if self._capture():
                leave = self._button("离开", "Leave", bottom=True)
                if leave is not None:
                    self.auto.mouse_click(*leave)
                    break
            self.pause(.2)
        else:
            raise self.restart_error("单人治疗：Esc 后未出现离开按钮" if escape else
                                     "单人治疗：未找到离开按钮")
        # Leaving the treatment panel must finish before ordinary shop actions.
        for _ in range(6):
            if self._capture() and self._probe(self.auto.find_element, SHOP):
                return
            self.pause(.2)
        raise self.restart_error("单人治疗：点击离开后未确认返回商店")

    def perform(self, sinner_index=1):
        portrait_point((1920, 1080), sinner_index)  # Validate before any input.
        for _ in range(3):
            if self._capture():
                before = self._money(False)
                if before is not None:
                    break
            self.pause(.2)
        else:
            return HealResult(False, "coins_unreadable")
        if before < 100:
            return HealResult(False, "insufficient_coins")

        entered = False
        for _ in range(3):
            if not self._capture():
                continue
            point = self._probe(self.auto.find_element, HEAL_ENTRY)
            if isinstance(point, (tuple, list)) and len(point) == 2:
                try:
                    self.auto.mouse_click(*point)
                except userStopError:
                    raise
                except Exception as error:
                    raise self.restart_error("单人治疗：进入治疗页面时输入失败") from error
                entered = True
                break
        if not entered:
            return HealResult(False, "entry_not_found")

        result = HealResult(False, "select_not_found")
        submitted = False
        target_clicked = False
        try:
            for _ in range(3):
                if self._capture():
                    option = self._button("治疗一名罪人", "Greatly heal a single Sinner")
                    if option is not None:
                        self.auto.mouse_click(*option)
                        if self._capture():
                            self.auto.mouse_click(*portrait_point(self.auto.screenshot.size, sinner_index))
                            target_clicked = True
                # Select slides into view; this wait must not be shortened by
                # the ordinary click/screenshot interval settings.
                self.pause(3)
                if not self._capture():
                    continue
                select = self._button("选择", "Select", bottom=True)
                if select is None or not target_clicked:
                    continue
                before = self._money(True)
                if before is None:
                    result = HealResult(False, "coins_unreadable")
                    break
                if before < 100:
                    result = HealResult(False, "insufficient_coins")
                    break
                # Mark submission BEFORE the input: an uncertain click outcome
                # must not cause another payment attempt.
                submitted = True
                self.auto.mouse_click(*select)
                for _ in range(6):
                    if self._capture():
                        after = self._money(True)
                        if after is not None and before - after == 100:
                            result = HealResult(True, "coins_spent")
                            break
                    self.pause(.2)
                else:
                    result = HealResult(False, "payment_unconfirmed")
                break
        except (userStopError, self.restart_error):
            raise
        except Exception as error:
            self.log.warning(f"单人治疗未完成，退出本次治疗：{error}")
            result = HealResult(False, "payment_unconfirmed" if submitted else "operation_failed")

        self._close(escape=not result.completed)
        return result
