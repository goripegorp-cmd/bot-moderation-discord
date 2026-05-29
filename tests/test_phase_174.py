"""Phase 174.2 : tests pour activity_rewards (rôles VIP temporaires)."""
import pytest

import activity_rewards


def test_api():
    for name in [
        "setup", "init_db", "compute_top_active", "run_weekly_rewards",
        "remove_expired", "weekly_reward_task",
        "REWARD_WEEKDAY", "REWARD_HOUR", "VIP_DURATION_DAYS",
        "TOP_MESSAGES", "TOP_VOICE", "MIN_MESSAGES", "MIN_VOICE_MINUTES",
    ]:
        assert hasattr(activity_rewards, name), f"manque : {name}"


def test_reward_schedule_sane():
    # Lundi (0) à une heure valide
    assert activity_rewards.REWARD_WEEKDAY == 0
    assert 0 <= activity_rewards.REWARD_HOUR <= 23


def test_vip_duration_is_temporary():
    """Le rôle est temporaire (1-2 semaines), conforme à la demande owner."""
    assert 7 <= activity_rewards.VIP_DURATION_DAYS <= 21


def test_thresholds_positive():
    """Seuils minimaux > 0 : on ne récompense pas une semaine morte."""
    assert activity_rewards.MIN_MESSAGES > 0
    assert activity_rewards.MIN_VOICE_MINUTES > 0


def test_top_counts_reasonable():
    """On récompense quelques membres, pas tout le serveur."""
    assert 1 <= activity_rewards.TOP_MESSAGES <= 10
    assert 1 <= activity_rewards.TOP_VOICE <= 10


def test_reward_task_is_loop():
    """weekly_reward_task est bien une tasks.loop."""
    from discord.ext import tasks
    assert isinstance(activity_rewards.weekly_reward_task, tasks.Loop)


def test_week_key_format():
    """_week_key renvoie un format année-semaine ISO."""
    key = activity_rewards._week_key()
    assert "-W" in key


def test_role_names_defined():
    """Les noms des rôles auto-créés sont définis."""
    assert activity_rewards.VIP_ROLE_NAME
    assert activity_rewards.VIP_PLUS_ROLE_NAME
    assert activity_rewards.VIP_ROLE_NAME != activity_rewards.VIP_PLUS_ROLE_NAME
