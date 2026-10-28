"""Developer-only Faust five-floor policy. Importing never starts game input.

This module describes the independent flow; game execution must reuse the
existing mirror, EGO, observation and shop controllers. It is not a launcher.
"""

from dataclasses import dataclass
import unicodedata


@dataclass(frozen=True)
class PackTarget:
    floor: int
    name_zh: str
    name_en: str
    selection_key_zh: str
    selection_key_en: str


@dataclass(frozen=True)
class EgoAction:
    turn: int
    name: str
    mode: int  # Original schema: 0 awakening, 1 corrosion.


@dataclass(frozen=True)
class FaustFiveFloorProfile:
    source_remarks: tuple[str, ...] = ("3层兔子洞(示例)", "兔子洞(示例)")
    floor_limit: int = 5
    hard_from_floor: int = 5
    ego_name: str = "空洞(le trou)"
    railway_weight: int = -5
    heal_sinner_index: int = 1  # Original zero-based sinner order: Faust.
    heal_floors: tuple[int, ...] = (4, 5)
    # Timing of the requested targeted heal remains to be confirmed.
    heal_once_per_floor: bool = True

    def clone_team(self, template):
        values = template.model_dump()
        values.update(mirror_floor_limit=self.floor_limit,
                      normal_to_hard_floor=self.hard_from_floor,
                      fixed_team_use=False)
        return type(template).model_validate(values)

    def find_template(self, teams):
        expected = {self._remark(name) for name in self.source_remarks}
        matches = [(key, team) for key, team in teams.items()
                   if self._remark(team.remark_name or "") in expected]
        if len(matches) != 1:
            raise ValueError("必须找到且仅找到一支兔子洞（示例）队伍，不能猜测其他编队")
        return matches[0]

    @staticmethod
    def _remark(name):
        return "".join(unicodedata.normalize("NFKC", name).split())

    def ego_actions(self, floor):
        if floor in (1, 2, 3):
            return (EgoAction(1, self.ego_name, 1),)
        if floor in (4, 5):
            return tuple(EgoAction(turn, self.ego_name, 0) for turn in (1, 2))
        return ()

    def hard_mode(self, floor):
        return self.hard_from_floor <= floor <= self.floor_limit

    def observation_target(self, floor):
        return {
            # User's "绝望与憎恶" refers to the existing Hatred and Despair card.
            4: PackTarget(4, "憎恶与绝望", "Hatred and Despair", "绝望", "Hatred"),
            5: PackTarget(5, "2号线", "Line 2", "2号线", "Line 2"),
        }.get(floor)

    def theme_weights(self, original):
        railways = {"line", "line1", "line2", "line3", "section#3", "section#4", "line5",
                    "号线", "1号线", "2号线", "3号线", "4号线-第3区段", "4号线-第4区段", "5号线"}
        return {key: self.railway_weight if "".join(str(key).split()).casefold() in railways else value
                for key, value in original.items()}

    def needs_priority_heal(self, floor, completed_floors):
        return floor in self.heal_floors and (not self.heal_once_per_floor or floor not in completed_floors)

    def heal_in_shop(self, shop, floor, completed_floors, *, recover=None):
        """Inner cleanup -> original game recovery -> return to outer runner.

        A miss/skip never consumes a floor's completion marker. After a restart
        the runner must re-detect its entry, not continue shop actions. Recovery
        failure and user stop propagate instead of causing recursive restarts.
        """
        if not self.needs_priority_heal(floor, completed_floors):
            return None
        try:
            result = shop.heal_single_sinner(self.heal_sinner_index)
        except shop.RestartGame:
            from tasks.mirror.single_sinner_heal import HealResult

            if recover is None:
                from tasks.base.retry import kill_game, restart_game

                kill_game()
                restart_game()
            else:
                recover()
            return HealResult(False, "game_restarted", shop_ready=False)
        if result.completed:
            completed_floors.add(floor)
        return result


PROFILE = FaustFiveFloorProfile()
