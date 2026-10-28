"""Card identity, per-floor temporary weights and isolated Qt configuration."""

import os
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from test_pack_observation import CandidateAuto, OBSERVATION, PACKS, TextMatchResult, _selection_module
from utils.theme_pack_lock import temporary_theme_pack_weights


TARGET = {"key": "target", "name": "目标卡包", "is_hard": False,
          "keywords_zh": ["target"], "keywords_en": ["target-en"]}


class NamedAuto(CandidateAuto):
    def __init__(self, names, remaining=0):
        super().__init__([0] * len(names), remaining=remaining)
        self.names = names
        self.tables = []

    def find_language_text(self, chinese, english, crop):
        self.tables.append((dict(chinese), dict(english)))
        name = self.names[self.index % len(self.names)]
        self.index += 1
        return None if name is None else TextMatchResult(99, name)


def select(module, floor=2, targets=None, rules=None):
    return module.select_theme_pack(floor=floor, observation_rules=rules or [[floor, 2, 2]],
                                    observation_targets=targets if targets is not None else {floor: TARGET})


def test_weight_copy_is_exact_highest_lowest_and_original_is_unchanged():
    original = {"target": -8, "alias": 0, "other": 10, "unknown": 5}
    assert temporary_theme_pack_weights(original, ["target", "alias"]) == {
        "target": 10, "alias": 10, "other": -10, "unknown": -10}
    assert original == {"target": -8, "alias": 0, "other": 10, "unknown": 5}


def test_present_target_wins_without_refresh_despite_negative_threshold_and_saved_weights():
    auto = NamedAuto(["other", "other", "target", "other", "other"], remaining=3)
    original = {"target": -10, "other": 10, "unknown": 0}
    module = _selection_module(auto, original, threshold=-10)
    select(module)
    auto.mouse_drag_down.assert_called_once_with(*PACKS[2])
    auto.click_element.assert_not_called()
    assert auto.tables[0][0] == {"target": 10, "other": -10, "unknown": -10}
    assert original == {"target": -10, "other": 10, "unknown": 0}


def test_missing_target_refreshes_then_selects_target():
    auto = NamedAuto(["other"] * 5, remaining=1)
    module = _selection_module(auto, {"target": -10, "other": 10})

    def refresh(*args, **kwargs):
        auto.names[3] = "target"
        auto.remaining = 0
        return True

    auto.click_element.side_effect = refresh
    select(module)
    auto.click_element.assert_called_once_with("mirror/theme_pack/refresh_assets.png")
    auto.mouse_drag_down.assert_called_once_with(*PACKS[3])


def test_exhausted_refresh_uses_existing_observation_not_other_positive_saved_card():
    auto = NamedAuto(["other"] * 5)
    module = _selection_module(auto, {"target": -10, "other": 10}, threshold=-10)
    module.observe_and_select = Mock(return_value="observed")
    assert select(module) == "observed"
    module.observe_and_select.assert_called_once_with(
        auto, module.log, OBSERVATION.ObservationRule(2, 2, 2), PACKS[0], candidate_count=5)
    auto.mouse_drag_down.assert_not_called()
    auto.click_element.assert_not_called()


@pytest.mark.parametrize("remaining", [None, 0])
def test_unknown_counter_or_title_is_bounded_and_never_selects_other_card(remaining):
    auto = NamedAuto(["other", "other", None, "other", "other"], remaining=remaining)
    module = _selection_module(auto, {"target": 0, "other": 10})
    module.observe_and_select = Mock(side_effect=AssertionError("Unknown title isn't all negative"))
    with pytest.raises(OBSERVATION.PackObservationFailed, match="未回退选择其他卡包"):
        select(module)
    auto.mouse_drag_down.assert_not_called()
    auto.click_element.assert_not_called()


def test_fifth_floor_event_shortcuts_cannot_override_lock():
    auto = NamedAuto(["other", "other", "other", "target", "other"])
    module = _selection_module(auto, {"target": 0, "other": 10})
    module.cfg.select_event_pack = module.cfg.skip_event_pack = True
    select(module, floor=5)
    auto.mouse_drag_down.assert_called_once_with(*PACKS[3])


def test_disabled_or_other_floor_has_no_weight_overlay_or_observation():
    module = _selection_module(NamedAuto(["other"] * 5), {"target": 0, "other": 10})
    module._select_theme_pack_standard = Mock(return_value="original")
    module._select_theme_pack_observation = Mock(side_effect=AssertionError("Unexpected extension"))
    assert module.select_theme_pack(floor=2, observation_targets={2: TARGET}) == "original"
    assert select(module, floor=3, targets={2: TARGET}, rules=[[2, 2, 2]]) == "original"


def test_unavailable_identity_is_an_explicit_failure_not_another_pick():
    auto = NamedAuto(["other"] * 5)
    module = _selection_module(auto, {"other": 10})
    with pytest.raises(OBSERVATION.PackObservationFailed, match="不在当前难度"):
        select(module)
    auto.mouse_drag_down.assert_not_called()


def test_picker_reuses_all_known_cards_and_has_no_weight_editor_or_save():
    from app.theme_pack_setting_interface import (
        THEME_PACK_HARD_IMAGE_MAP, THEME_PACK_IMAGE_MAP, ThemePackSelectionDialog,
    )
    app = QApplication.instance() or QApplication([])
    dialog = ThemePackSelectionDialog()
    try:
        while dialog._pending_cards:
            dialog._load_batch()
        assert len(dialog.cards) == len(THEME_PACK_IMAGE_MAP) + len(THEME_PACK_HARD_IMAGE_MAP) - 1
        assert all(card.weight_spinbox.isHidden() for card in dialog.cards)
        assert all(card.image_label.pixmap() is not None and not card.image_label.pixmap().isNull()
                   for card in dialog.cards)
        dialog._choose("chick", False)
        assert dialog.selected_target["keywords_zh"] == ["地狱鸡"]
        assert dialog.selected_target["keywords_en"] == ["chick"]
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_rule_roundtrip_moves_target_with_floor_and_removes_it_with_rule():
    from app.rabbit_options import ThemeObservationOptions
    from app.theme_pack_setting_interface import observation_target_for_card
    from module.config.config_typing import TeamSetting

    app = QApplication.instance() or QApplication([])
    widget = ThemeObservationOptions()
    original = TeamSetting(rabbit_observe_enabled=True, rabbit_observe_rules=[[2, 2, 2]])
    changes = []
    widget.changed.connect(changes.append)
    try:
        widget.load_settings(original)
        row = widget.rule_rows[0]
        assert row.target_button.text() == "选择卡面"
        assert row.layout().indexOf(row.target_button) == row.layout().indexOf(row.floor) + 1
        target = observation_target_for_card("chick")
        row.set_target(target)
        assert row.target_button.text() == target["name"]
        assert widget.settings()["rabbit_observe_targets"][2]["key"] == "chick"
        restored = TeamSetting.model_validate_json(TeamSetting(**widget.settings()).model_dump_json())
        widget.load_settings(restored)
        assert widget.rule_rows[0].target_button.text() == target["name"]
        widget.rule_rows[0].floor.setValue(3)
        assert set(widget.observation_targets()) == {3}
        widget.remove_rule(widget.rule_rows[0])
        assert widget.observation_targets() == {}
        assert original.rabbit_observe_targets == {}
    finally:
        widget.close()
        widget.deleteLater()
        app.processEvents()


def test_schema_keeps_old_rules_and_rejects_invalid_lock_floor():
    from module.config.config_typing import TeamSetting
    from pydantic import ValidationError

    assert TeamSetting(rabbit_observe_rules=[[2, 2, 2]]).rabbit_observe_targets == {}
    with pytest.raises(ValidationError):
        TeamSetting(rabbit_observe_targets={6: TARGET})


def test_row_picker_accept_cancel_and_clear_keep_changes_local():
    from app.rabbit_options import ObservePackRuleRow
    from app.theme_pack_setting_interface import observation_target_for_card
    from module.config import cfg, theme_list

    app = QApplication.instance() or QApplication([])
    row = ObservePackRuleRow([2, 2, 2], allow_target=True)
    target = observation_target_for_card("chick")
    try:
        with patch.object(cfg, "set_value") as save_config, patch.object(theme_list, "save_config") as save_weights:
            with patch("app.theme_pack_setting_interface.ThemePackSelectionDialog") as factory:
                dialog = factory.return_value
                dialog.exec.return_value = 1
                dialog.selected_target = target
                row._choose_target()
                assert row.target == target
                dialog.exec.return_value = 0
                dialog.selected_target = None
                row._choose_target()
                assert row.target == target
                dialog.exec.return_value = 1
                dialog.selected_target = {}
                row._choose_target()
                assert row.target is None
                assert row.target_button.text() == "选择卡面"
            save_config.assert_not_called()
            save_weights.assert_not_called()
    finally:
        row.close()
        row.deleteLater()
        app.processEvents()


def test_actual_team_editor_receives_both_fields_saves_and_reopens_target():
    from app.team_setting_card import TeamSettingCard
    from app.theme_pack_setting_interface import observation_target_for_card
    from module.config import cfg
    from module.config.config_typing import TeamSetting, ThemePackObservationTarget

    app = QApplication.instance() or QApplication([])
    editor = TeamSettingCard(1)
    try:
        editor.team_setting = TeamSetting(rabbit_observe_enabled=True, rabbit_observe_rules=[[2, 2, 2]])
        editor.read_settings()
        widget = editor.theme_observation_module
        row = widget.rule_rows[0]
        row.set_target(observation_target_for_card("chick"))
        assert isinstance(editor.team_setting.rabbit_observe_targets[2], ThemePackObservationTarget)
        row.floor.setValue(3)
        assert editor.team_setting.rabbit_observe_rules == [[3, 2, 2]]
        assert set(editor.team_setting.rabbit_observe_targets) == {3}
        with patch.object(cfg, "set_value") as save:
            editor.save_team_setting()
            saved = save.call_args.args[1]
            assert saved.rabbit_observe_targets[3].key == "chick"
        restored = TeamSetting.model_validate_json(saved.model_dump_json())
        editor.team_setting = restored
        editor.read_settings()
        assert editor.theme_observation_module.rule_rows[0].target["key"] == "chick"
    finally:
        editor.disconnect_mediator()
        editor.close()
        editor.deleteLater()
        app.processEvents()
