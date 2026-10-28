"""Pure policy checks: no screenshots, game input, application or user config."""

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


policy = load("faust_five_floor_policy", "developer/faust_five_floor_profile.py")
schema = load("faust_profile_team_schema", "module/config/config_typing.py")


def test_profile_clones_example_without_restricting_team_usage_or_editing_original():
    source = schema.TeamSetting(team_number=22, fixed_team_use=True, mirror_floor_limit=3,
                                normal_to_hard_floor=0, chosen_sinners=[0, 1] + [0] * 10)
    before = source.model_dump()
    result = policy.PROFILE.clone_team(source)
    assert result.mirror_floor_limit == 5
    assert result.normal_to_hard_floor == 5
    assert result.fixed_team_use is False
    assert result.team_number == 22
    assert result.chosen_sinners == source.chosen_sinners
    assert source.model_dump() == before


@pytest.mark.parametrize("floor", [1, 2, 3])
def test_first_three_floors_corrosion_only_on_turn_one(floor):
    actions = policy.PROFILE.ego_actions(floor)
    assert [(action.turn, action.name, action.mode) for action in actions] == [(1, "空洞(le trou)", 1)]


@pytest.mark.parametrize("floor", [4, 5])
def test_final_two_floors_awaken_on_turn_one_and_two(floor):
    actions = policy.PROFILE.ego_actions(floor)
    assert [(action.turn, action.mode) for action in actions] == [(1, 0), (2, 0)]
    assert policy.PROFILE.hard_mode(floor) == (floor == 5)


def test_unknown_floor_has_no_ego_plan():
    assert policy.PROFILE.ego_actions(0) == ()


def test_railway_weights_are_local_and_include_the_negative_target_line_two():
    source = {"Line 1": 0, "Line 2": 4, "Section #3": 0, "Section #4": 0,
              "1号线": 0, "2号线": 4, "4号线 - 第3区段": 0, "绝望": 7}
    result = policy.PROFILE.theme_weights(source)
    assert result == {key: 7 if key == "绝望" else -5 for key in source}
    assert source["Line 2"] == 4
    assert policy.PROFILE.observation_target(4).name_zh == "憎恶与绝望"
    assert policy.PROFILE.observation_target(5).selection_key_en == "Line 2"


def test_template_identity_must_be_unique_and_not_a_substring_guess():
    team = schema.TeamSetting(remark_name="3层兔子洞（示例）")
    assert policy.PROFILE.find_template({"8": team}) == ("8", team)
    with pytest.raises(ValueError):
        policy.PROFILE.find_template({"8": team, "9": team})
    with pytest.raises(ValueError):
        policy.PROFILE.find_template({"8": schema.TeamSetting(remark_name="兔子洞的其他队伍")})


def test_each_floor_heal_is_marked_only_by_confirmed_completed_set():
    assert policy.PROFILE.needs_priority_heal(4, set())
    assert policy.PROFILE.needs_priority_heal(5, {4})
    assert not policy.PROFILE.needs_priority_heal(4, {4})
    assert not policy.PROFILE.needs_priority_heal(3, set())


def test_targeted_heal_skips_completed_floor_and_marks_only_success():
    shop = SimpleNamespace(heal_single_sinner=Mock(return_value=SimpleNamespace(completed=False)))
    completed = set()
    assert policy.PROFILE.heal_in_shop(shop, 3, completed) is None
    shop.heal_single_sinner.assert_not_called()
    policy.PROFILE.heal_in_shop(shop, 4, completed)
    assert not completed
    shop.heal_single_sinner.return_value = SimpleNamespace(completed=True)
    policy.PROFILE.heal_in_shop(shop, 4, completed)
    assert completed == {4}
    assert policy.PROFILE.heal_in_shop(shop, 4, completed) is None
    assert shop.heal_single_sinner.call_count == 2
    shop.heal_single_sinner.assert_called_with(1)


def test_failed_cleanup_escalates_to_game_recovery_without_consuming_completion():
    class RestartGame(Exception):
        pass

    shop = SimpleNamespace(RestartGame=RestartGame,
                           heal_single_sinner=Mock(side_effect=RestartGame("cleanup failed")))
    completed = set()
    recover = Mock()
    result = policy.PROFILE.heal_in_shop(shop, 4, completed, recover=recover)
    recover.assert_called_once_with()
    assert not result.completed and not result.shop_ready
    assert result.reason == "game_restarted"
    assert completed == set()


def test_failed_game_recovery_does_not_recursively_restart_or_resume_shop():
    class RestartGame(Exception):
        pass

    shop = SimpleNamespace(RestartGame=RestartGame,
                           heal_single_sinner=Mock(side_effect=RestartGame("cleanup failed")))
    recover = Mock(side_effect=RuntimeError("cannot restart"))
    with pytest.raises(RuntimeError, match="cannot restart"):
        policy.PROFILE.heal_in_shop(shop, 5, set(), recover=recover)
    recover.assert_called_once_with()
