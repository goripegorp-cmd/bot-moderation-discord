"""Smoke test des 4 fichiers de fondation Phase 0."""
import asyncio
import sys


def test_vocabulary():
    from vocabulary import Action, Status, Module, Message, UserRole, Time, Unit
    assert Action.SAVE == "Sauvegarder"
    assert Action.SAVE_ICON.startswith("💾")
    assert Status.ENABLED == "Active"
    assert Module.PROTECTION == "Protection"
    assert Message.NOT_PERMITTED.startswith("🚫")
    assert UserRole.OWNER == "Proprietaire du serveur"
    assert Time.PERMANENT == "Permanent"
    assert Unit.XP == "XP"
    print("[OK] vocabulary")


def test_help_system():
    from help_system import (
        Audience, AUDIENCE_LABELS, HelpEntry, help_registry,
        register_help, format_entry_short, format_entry_full,
    )
    # Verifie que les entrees de base sont la
    welcome = help_registry.get("welcome")
    assert welcome is not None
    assert Audience.NEWCOMER in welcome.audiences

    # Test for_audience
    newcomer_entries = help_registry.for_audience(Audience.NEWCOMER)
    assert len(newcomer_entries) >= 1
    assert any(e.key == "welcome" for e in newcomer_entries)

    host_entries = help_registry.for_audience(Audience.HOST)
    assert any(e.key == "moderation_intro" for e in host_entries)
    assert any(e.key == "permissions_intro" for e in host_entries)

    # Test register custom
    register_help(
        key="test_entry",
        title="Test",
        description="Description test",
        audiences=[Audience.ALL],
        category="test",
    )
    assert help_registry.get("test_entry") is not None

    # Test search
    results = help_registry.search("moderation")
    assert len(results) >= 1

    # Test categories
    cats = help_registry.categories()
    assert "onboarding" in cats
    assert "moderation" in cats

    # Test format helpers
    short = format_entry_short(welcome)
    assert "Bienvenue" in short
    full = format_entry_full(welcome)
    assert "Bienvenue" in full

    print("[OK] help_system")


def test_engagement():
    from engagement import (
        EngagementChannel, ConversationStarter, EngagementEvent,
        AttentionBudget, CONVERSATION_STARTERS, AMBIENT_EVENTS,
        can_use_channel, record_attention, pick_starter, attention_usage,
    )

    assert len(CONVERSATION_STARTERS) >= 5
    assert len(AMBIENT_EVENTS) >= 3

    # Test budget
    guild_id = 12345
    # Reaction toujours OK
    assert can_use_channel(guild_id, EngagementChannel.REACTION) is True

    # Subtle reply : 5/jour par defaut
    for _ in range(5):
        assert can_use_channel(guild_id, EngagementChannel.SUBTLE_REPLY) is True
        record_attention(guild_id, EngagementChannel.SUBTLE_REPLY)
    # 6eme : refuse
    assert can_use_channel(guild_id, EngagementChannel.SUBTLE_REPLY) is False

    # Channel ping : 1/semaine par defaut
    assert can_use_channel(guild_id, EngagementChannel.CHANNEL_PING) is True
    record_attention(guild_id, EngagementChannel.CHANNEL_PING)
    assert can_use_channel(guild_id, EngagementChannel.CHANNEL_PING) is False

    # Test usage stats
    usage = attention_usage(guild_id)
    assert usage[EngagementChannel.SUBTLE_REPLY] == 5
    assert usage[EngagementChannel.CHANNEL_PING] == 1

    # Test starter picking
    s = pick_starter(99999, category="general")
    assert s is not None
    assert s.category == "general"

    # Test starter unique pendant cooldown
    seen = {s.text}
    for _ in range(3):
        s2 = pick_starter(99999, category="general")
        if s2:
            assert s2.text not in seen
            seen.add(s2.text)

    print("[OK] engagement")


async def test_permissions():
    from permissions import (
        PermissionRule, SanctionableConfig, BypassConfig, PermissionsConfig,
        load_permissions, save_permissions, reload_permissions,
        get_command_categories, get_category_labels,
        list_commands_in_category, list_categories,
    )

    # Schema integrite
    cats = get_command_categories()
    assert "ban" in cats
    assert cats["ban"] == "moderation"
    assert "config" in cats
    assert "ticket_open" in cats

    labels = get_category_labels()
    assert "moderation" in labels
    assert "configuration" in labels

    mod_cmds = list_commands_in_category("moderation")
    assert "ban" in mod_cmds
    assert "kick" in mod_cmds
    assert "warn" in mod_cmds

    all_cats = list_categories()
    assert "moderation" in all_cats
    assert "tempvoice" in all_cats

    # Roundtrip serialization
    cfg = PermissionsConfig()
    cfg.commands["ban"] = PermissionRule(
        default="deny",
        allow_roles=[111, 222],
        deny_users=[333],
    )
    cfg.sanctionable.non_sanctionable_roles = [444]
    cfg.bypass["antiraid"] = BypassConfig(roles=[555])

    data = cfg.to_dict()
    cfg2 = PermissionsConfig.from_dict(data)
    assert cfg2.commands["ban"].default == "deny"
    assert cfg2.commands["ban"].allow_roles == [111, 222]
    assert cfg2.commands["ban"].deny_users == [333]
    assert cfg2.sanctionable.non_sanctionable_roles == [444]
    assert cfg2.bypass["antiraid"].roles == [555]

    # Persistance disque
    test_guild = 999999999
    await save_permissions(test_guild, cfg)
    loaded = await reload_permissions(test_guild)
    assert loaded.commands["ban"].default == "deny"
    assert loaded.bypass["antiraid"].roles == [555]

    # Cleanup
    from pathlib import Path
    p = Path("data") / "permissions" / f"{test_guild}.json"
    if p.exists():
        p.unlink()

    print("[OK] permissions")


async def test_backup():
    from backup_system import (
        create_backup, list_backups, load_backup, restore_backup,
        delete_backup, prune_old_backups, list_sources, list_critical_sources,
    )
    from permissions import PermissionsConfig, PermissionRule, save_permissions, load_permissions

    test_guild = 888888888

    # Cleanup pre-test
    for info in await list_backups(test_guild):
        await delete_backup(test_guild, info.backup_id)

    # Source "permissions" doit etre auto-enregistree
    sources = list_sources()
    assert any(s.key == "permissions" for s in sources)
    assert "permissions" in list_critical_sources()

    # Cree un etat initial
    cfg1 = PermissionsConfig()
    cfg1.commands["ban"] = PermissionRule(default="deny", allow_roles=[111])
    await save_permissions(test_guild, cfg1)

    # Cree une sauvegarde
    info = await create_backup(test_guild, label="Test initial")
    assert info.backup_id
    assert info.label == "Test initial"
    assert "permissions" in info.sources
    assert info.size_bytes > 0

    # Liste les backups
    backups = await list_backups(test_guild)
    assert len(backups) == 1
    assert backups[0].backup_id == info.backup_id

    # Modifie l'etat actuel
    cfg2 = PermissionsConfig()
    cfg2.commands["ban"] = PermissionRule(default="allow")
    await save_permissions(test_guild, cfg2)

    # Verifie que l'etat a change
    current = await load_permissions(test_guild)
    assert current.commands["ban"].default == "allow"

    # Restaure le backup
    report = await restore_backup(test_guild, info.backup_id, auto_backup_before=False)
    assert report.success, f"erreurs: {report.errors}"
    assert "permissions" in report.restored_modules

    # Verifie que l'etat est revenu
    restored = await load_permissions(test_guild)
    assert restored.commands["ban"].default == "deny"
    assert restored.commands["ban"].allow_roles == [111]

    # Test auto-backup-before
    report2 = await restore_backup(test_guild, info.backup_id, auto_backup_before=True)
    assert report2.pre_restore_backup_id is not None
    backups2 = await list_backups(test_guild)
    assert len(backups2) == 2  # original + auto-backup

    # Test load_backup
    payload = await load_backup(test_guild, info.backup_id)
    assert payload is not None
    assert payload["label"] == "Test initial"
    assert "permissions" in payload["data"]

    # Test delete
    deleted = await delete_backup(test_guild, info.backup_id)
    assert deleted is True
    backups3 = await list_backups(test_guild)
    assert info.backup_id not in [b.backup_id for b in backups3]

    # Cleanup
    for info in await list_backups(test_guild):
        await delete_backup(test_guild, info.backup_id)

    # Cleanup permissions test data
    from pathlib import Path
    p = Path("data") / "permissions" / f"{test_guild}.json"
    if p.exists():
        p.unlink()
    gdir = Path("data") / "backups" / str(test_guild)
    if gdir.exists() and not list(gdir.iterdir()):
        gdir.rmdir()

    print("[OK] backup_system")


async def test_social_media():
    from social_media import (
        Platform, PostType, SocialPost, Subscription, Announcement,
        ManualAdapter, SocialMediaManager,
        default_template, render_template,
    )

    # Adapter manuel
    tiktok = ManualAdapter(Platform.TIKTOK)
    assert tiktok.configured

    p1 = SocialPost(
        platform=Platform.TIKTOK,
        handle="someuser",
        post_id="vid_001",
        post_type=PostType.VIDEO,
        title="Premier Tiktok",
        url="https://tiktok.com/@someuser/video/vid_001",
    )
    tiktok.declare_post(p1)

    fetched = await tiktok.fetch_posts("someuser")
    assert len(fetched) == 1
    assert fetched[0].post_id == "vid_001"

    fetched_other = await tiktok.fetch_posts("nobody")
    assert fetched_other == []

    # Manager + callback mock
    posted_messages: list[tuple[str, int]] = []
    deleted_messages: list[int] = []
    next_message_id = [10000]

    async def post_cb(sub: Subscription, post: SocialPost):
        next_message_id[0] += 1
        msg_id = next_message_id[0]
        posted_messages.append((post.post_id, msg_id))
        return msg_id

    async def delete_cb(ann: Announcement):
        deleted_messages.append(ann.discord_message_id)
        return True

    mgr = SocialMediaManager(post_callback=post_cb, delete_callback=delete_cb)
    mgr.register_adapter(tiktok)

    test_guild = 777777777
    target_chan = 123456789

    # Add a subscription
    sub = await mgr.add_subscription(
        guild_id=test_guild,
        platform=Platform.TIKTOK,
        handle="someuser",
        target_channel_id=target_chan,
        display_name="Some User",
        track_videos=True,
    )
    assert sub.sub_id

    # Doublon : meme platform+handle+channel ne doit pas creer une 2eme sub
    sub2 = await mgr.add_subscription(
        guild_id=test_guild,
        platform=Platform.TIKTOK,
        handle="someuser",
        target_channel_id=target_chan,
    )
    assert sub2.sub_id == sub.sub_id

    subs = await mgr.list_subscriptions(test_guild)
    assert len(subs) == 1

    # First poll : doit creer une annonce
    created = await mgr.poll_subscription(sub)
    assert created == 1
    assert len(posted_messages) == 1
    assert posted_messages[0][0] == "vid_001"

    anns = await mgr.list_announcements(test_guild)
    assert len(anns) == 1
    assert anns[0].post_id == "vid_001"

    # Second poll : DEDUP, ne doit PAS recreer une annonce
    created2 = await mgr.poll_subscription(sub)
    assert created2 == 0
    assert len(posted_messages) == 1  # toujours 1, pas 2

    # On simule la suppression du post sur TikTok (l'owner declare retrait)
    tiktok.remove_post("someuser", "vid_001")

    # Cleanup : doit detecter et supprimer l'annonce Discord
    cleaned = await mgr.cleanup_all()
    assert cleaned[test_guild] == 1
    assert len(deleted_messages) == 1
    assert deleted_messages[0] == posted_messages[0][1]

    # L'annonce est marquee deleted
    anns2 = await mgr.list_announcements(test_guild)
    assert anns2[0].deleted is True

    # Persistance : nouveau manager, charge les memes donnees
    mgr2 = SocialMediaManager(post_callback=post_cb, delete_callback=delete_cb)
    mgr2.register_adapter(ManualAdapter(Platform.TIKTOK))
    subs_loaded = await mgr2.list_subscriptions(test_guild)
    assert len(subs_loaded) == 1
    assert subs_loaded[0].handle == "someuser"
    anns_loaded = await mgr2.list_announcements(test_guild)
    assert len(anns_loaded) == 1
    assert anns_loaded[0].deleted is True

    # Test add multi-platform + matching
    twitch_manual = ManualAdapter(Platform.TWITCH)
    mgr.register_adapter(twitch_manual)
    sub_twitch = await mgr.add_subscription(
        guild_id=test_guild,
        platform=Platform.TWITCH,
        handle="streamer",
        target_channel_id=target_chan,
        track_lives=True,
    )
    twitch_post = SocialPost(
        platform=Platform.TWITCH,
        handle="streamer",
        post_id="stream_42",
        post_type=PostType.LIVE,
        title="Live now",
        url="https://twitch.tv/streamer",
        is_live=True,
    )
    twitch_manual.declare_post(twitch_post)
    created3 = await mgr.poll_subscription(sub_twitch)
    assert created3 == 1

    # Update sub
    updated = await mgr.update_subscription(test_guild, sub_twitch.sub_id, enabled=False)
    assert updated.enabled is False

    # Sub disabled n'est plus poll
    twitch_post2 = SocialPost(
        platform=Platform.TWITCH,
        handle="streamer",
        post_id="stream_43",
        post_type=PostType.LIVE,
        title="Live again",
        url="https://twitch.tv/streamer",
        is_live=True,
    )
    twitch_manual.declare_post(twitch_post2)
    created4 = await mgr.poll_subscription(sub_twitch)
    assert created4 == 0  # disabled

    # Remove subscription
    removed = await mgr.remove_subscription(test_guild, sub_twitch.sub_id)
    assert removed is True
    final_subs = await mgr.list_subscriptions(test_guild)
    assert len(final_subs) == 1  # plus que tiktok

    # Template default + render
    tpl = default_template(Platform.TWITCH, PostType.LIVE)
    assert "Twitch" in tpl
    assert "live" in tpl.lower()

    fake_sub = Subscription(
        sub_id="x", guild_id=1, platform=Platform.YOUTUBE,
        handle="creator", display_name="Creator", target_channel_id=1,
    )
    fake_post = SocialPost(
        platform=Platform.YOUTUBE, handle="creator", post_id="vid",
        post_type=PostType.VIDEO, title="Ma video", url="https://yt/vid",
    )
    rendered = render_template(fake_sub, fake_post)
    assert "Creator" in rendered
    assert "Ma video" in rendered
    assert "https://yt/vid" in rendered

    # Cleanup files
    from pathlib import Path
    for f in (Path("data") / "social").glob(f"{test_guild}_*.json"):
        f.unlink()

    print("[OK] social_media")


async def test_protection():
    from protection_guards import (
        Action, AutoEventType, ACTION_SEVERITY,
        TrustScore, MemberContext, DetectionEvent, ActionDecision,
        ProtectionPolicy, load_policy, save_policy, reload_policy,
        decide_action, read_audit,
    )

    test_guild = 666666666

    # Cleanup pre-test
    from pathlib import Path
    pol_path = Path("data") / "protection" / f"{test_guild}_policy.json"
    if pol_path.exists():
        pol_path.unlink()
    aud_path = Path("data") / "protection" / "audit" / f"{test_guild}.jsonl"
    if aud_path.exists():
        aud_path.unlink()
    await reload_policy(test_guild)

    # Test 1: TrustScore calcul
    new_account = TrustScore(account_age_days=2, server_age_days=1, message_count=0)
    assert new_account.value <= 5  # tres faible

    veteran = TrustScore(
        account_age_days=400, server_age_days=200, message_count=2000,
        has_privileged_role=True, is_booster=True,
    )
    assert veteran.value >= 90  # quasi-immune

    # Test 2: scenario "giveaway legitime" - le membre poste un giveaway
    # avec emoji et keywords. Antiscam fired avec confidence 0.7. proposed=BAN.
    # Resultat attendu : LOG seulement (pattern giveaway match)
    ctx = MemberContext(
        user_id=1001, user_name="user_legit", role_ids=[],
        account_age_days=60, server_age_days=30, message_count=150,
    )
    event = DetectionEvent(
        event_type=AutoEventType.SCAM,
        confidence=0.7,
        evidence=["URL suspecte"],
        raw_content="🎁 GIVEAWAY 🎁 Je tire au sort un jeu pour le gagnant !",
    )
    decision = await decide_action(test_guild, ctx, event, Action.BAN)
    assert decision.final_action == Action.LOG, \
        f"Giveaway legitime devrait etre LOG, mais={decision.final_action} ({decision.reason})"
    assert "giveaway" in decision.reason.lower()

    # Test 3: scenario "image legitime" - le membre poste une image tenor
    # AutoMod link fired avec confidence 0.8. Resultat : LOG (whitelist domain)
    event_img = DetectionEvent(
        event_type=AutoEventType.LINK,
        confidence=0.8,
        evidence=["Lien externe"],
        raw_content="Regarde ce gif https://tenor.com/view/funny-cat-12345",
    )
    decision_img = await decide_action(test_guild, ctx, event_img, Action.MUTE)
    assert decision_img.final_action == Action.LOG, \
        f"Lien tenor devrait etre LOG, mais={decision_img.final_action}"
    assert "whiteliste" in decision_img.reason.lower()

    # Test 4: scenario "phishing reel" - URL non whitelistee, confidence haute
    # Veteran user (trust=100) -> downgrade ban a kick (trust_threshold_protected)
    event_phish = DetectionEvent(
        event_type=AutoEventType.PHISHING,
        confidence=0.95,
        evidence=["URL suspecte"],
        raw_content="Click here to claim your prize: https://discrod-nitro-free.scam/claim",
    )
    veteran_ctx = MemberContext(
        user_id=2002, user_name="veteran", role_ids=[],
        account_age_days=400, server_age_days=200, message_count=2000,
        has_privileged_role=True, is_booster=True,
    )
    decision_v = await decide_action(test_guild, veteran_ctx, event_phish, Action.BAN)
    # Veteran trust >= 90 (immune) -> LOG
    assert decision_v.final_action == Action.LOG, \
        f"Veteran immune devrait etre LOG, mais={decision_v.final_action} (trust={decision_v.trust_score})"

    # Test 5: scenario "phishing reel sur newcomer" - pas de protection
    newbie_ctx = MemberContext(
        user_id=3003, user_name="newbie", role_ids=[],
        account_age_days=1, server_age_days=0, message_count=0,
    )
    decision_n = await decide_action(test_guild, newbie_ctx, event_phish, Action.BAN)
    # Newbie pas protege, confidence elevee -> action proche du proposed
    assert decision_n.final_action == Action.BAN, \
        f"Newbie phishing devrait BAN, mais={decision_n.final_action}"

    # Test 6: trusted user (whitelist explicite) -> LOG meme sur scam
    policy = await load_policy(test_guild)
    policy.trusted_user_ids = [9999]
    await save_policy(test_guild, policy)

    trusted_ctx = MemberContext(
        user_id=9999, user_name="trusted_friend", role_ids=[],
        account_age_days=0, server_age_days=0, message_count=0,
    )
    decision_t = await decide_action(test_guild, trusted_ctx, event_phish, Action.BAN)
    assert decision_t.final_action == Action.LOG
    assert "whitelist" in decision_t.reason.lower() or "trust" in decision_t.reason.lower()

    # Test 7: SOFT MODE - tout est LOG meme sur high confidence
    policy.soft_mode = True
    policy.trusted_user_ids = []
    await save_policy(test_guild, policy)

    decision_soft = await decide_action(test_guild, newbie_ctx, event_phish, Action.BAN)
    assert decision_soft.final_action == Action.LOG, \
        f"Soft mode devrait etre LOG, mais={decision_soft.final_action}"
    assert decision_soft.audit_log_only is True
    assert decision_soft.notify_staff is True

    # Test 8: REVIEW MODE - actions au-dela de WARN deviennent LOG
    policy.soft_mode = False
    policy.review_mode = True
    await save_policy(test_guild, policy)

    decision_rev = await decide_action(test_guild, newbie_ctx, event_phish, Action.BAN)
    assert decision_rev.final_action == Action.LOG
    assert decision_rev.notify_staff is True

    # Test 9: confidence trop basse -> WARN au max meme avec proposed=BAN
    policy.review_mode = False
    await save_policy(test_guild, policy)

    low_conf_event = DetectionEvent(
        event_type=AutoEventType.SPAM,
        confidence=0.4,  # juste au-dessus de WARN (0.3) mais en-dessous de MUTE (0.5)
        evidence=["3 msg en 30s"],
        raw_content="hey hey hey",
    )
    decision_lc = await decide_action(test_guild, newbie_ctx, low_conf_event, Action.BAN)
    assert decision_lc.final_action == Action.WARN, \
        f"Low confidence devrait WARN, mais={decision_lc.final_action}"

    # Test 10: capping - proposed=MUTE meme si confidence permet BAN, on cap
    high_conf_event = DetectionEvent(
        event_type=AutoEventType.SPAM,
        confidence=0.99,  # permet BAN
        evidence=["50 msg en 10s"],
        raw_content="yo yo yo " * 50,
    )
    decision_cap = await decide_action(test_guild, newbie_ctx, high_conf_event, Action.MUTE)
    # Confidence permet BAN, mais proposed=MUTE -> capped a MUTE
    assert decision_cap.final_action == Action.MUTE, \
        f"Cap par proposed devrait etre MUTE, mais={decision_cap.final_action}"

    # Test 11: audit log persiste
    audits = await read_audit(test_guild, limit=100)
    assert len(audits) >= 8  # au moins toutes les decisions ci-dessus

    # Test 12: severite des actions ordonnee
    assert ACTION_SEVERITY[Action.NONE] < ACTION_SEVERITY[Action.LOG]
    assert ACTION_SEVERITY[Action.LOG] < ACTION_SEVERITY[Action.WARN]
    assert ACTION_SEVERITY[Action.WARN] < ACTION_SEVERITY[Action.MUTE]
    assert ACTION_SEVERITY[Action.MUTE] < ACTION_SEVERITY[Action.KICK]
    assert ACTION_SEVERITY[Action.KICK] < ACTION_SEVERITY[Action.BAN]

    # Cleanup
    if pol_path.exists():
        pol_path.unlink()
    if aud_path.exists():
        aud_path.unlink()

    print("[OK] protection_guards")


async def test_community_features():
    from community_features import (
        CommunityConfig, FeatureActionType, FeaturePayload, MemberActivity,
        WeeklyStats,
        load_config, save_config, reload_config,
        should_post_daily_conversation, select_member_spotlight,
        build_welcome_message, should_add_activity_reaction,
        should_nudge_inactive_channel, get_theme_for_today,
        build_weekly_digest,
    )
    from datetime import datetime, timezone, timedelta
    from pathlib import Path

    test_guild = 555555555

    # Cleanup pre-test
    for f in (Path("data") / "community").glob(f"{test_guild}_*.json"):
        f.unlink()
    await reload_config(test_guild)

    # === Test 1: daily conversation - off par defaut, doit retourner None ===
    cfg = await load_config(test_guild)
    assert cfg.daily_conversation_enabled is False
    res = await should_post_daily_conversation(test_guild)
    assert res is None

    # Active + configure heure pour declencher maintenant
    now = datetime.now(timezone.utc)
    cfg.daily_conversation_enabled = True
    cfg.daily_conversation_channel_id = 111
    cfg.daily_conversation_hour_utc = max(0, now.hour - 1)  # heure passee => doit declencher
    await save_config(test_guild, cfg)

    res = await should_post_daily_conversation(test_guild, now=now)
    assert res is not None
    assert res.action_type == FeatureActionType.POST_MESSAGE
    assert res.target_channel_id == 111
    assert "Question du jour" in res.content

    # 2eme appel le meme jour : doit retourner None (deja poste)
    res2 = await should_post_daily_conversation(test_guild, now=now)
    assert res2 is None

    # === Test 2: member spotlight ===
    cfg.member_spotlight_enabled = True
    cfg.member_spotlight_channel_id = 222
    cfg.member_spotlight_day_of_week = now.weekday()
    cfg.member_spotlight_hour_utc = max(0, now.hour - 1)
    await save_config(test_guild, cfg)

    activity = [
        MemberActivity(user_id=1, user_name="alice", message_count=200, voice_minutes=120, helpful_reactions=10),
        MemberActivity(user_id=2, user_name="bob", message_count=50, voice_minutes=0, helpful_reactions=2),
        MemberActivity(user_id=3, user_name="carol", message_count=100, voice_minutes=60, helpful_reactions=0),
    ]
    res = await select_member_spotlight(test_guild, activity, now=now)
    assert res is not None
    assert res.target_user_id == 1  # alice doit gagner (plus actif global)
    assert "<@1>" in res.content
    assert "Bravo" in res.content

    # === Test 3: welcome quickstart ===
    cfg.welcome_quickstart_enabled = True
    cfg.welcome_quickstart_channel_id = 333
    cfg.welcome_quickstart_rules_channel_id = 999
    cfg.welcome_quickstart_help_channel_id = 998
    await save_config(test_guild, cfg)

    res = await build_welcome_message(test_guild, member_id=42, member_name="Newbie", server_name="Test Server")
    assert res is not None
    assert res.action_type == FeatureActionType.POST_MESSAGE
    assert res.target_channel_id == 333
    assert "<@42>" in res.content
    assert "Test Server" in res.content
    assert "<#999>" in res.content   # rules channel
    assert "<#998>" in res.content   # help channel

    # Test welcome sans channel -> DM
    cfg.welcome_quickstart_channel_id = None
    await save_config(test_guild, cfg)
    res_dm = await build_welcome_message(test_guild, member_id=42, member_name="Newbie", server_name="Test Server")
    assert res_dm is not None
    assert res_dm.action_type == FeatureActionType.SEND_DM
    assert res_dm.target_user_id == 42

    # === Test 4: activity recognition ===
    cfg.activity_recognition_enabled = True
    cfg.activity_recognition_burst_threshold = 10
    cfg.activity_recognition_window_minutes = 5
    await save_config(test_guild, cfg)

    # Pas assez de messages -> None
    res = await should_add_activity_reaction(test_guild, channel_id=44, target_message_id=99, recent_message_count=5, window_minutes=5)
    assert res is None

    # Burst detecte -> emoji react
    res = await should_add_activity_reaction(test_guild, channel_id=44, target_message_id=99, recent_message_count=15, window_minutes=3)
    assert res is not None
    assert res.action_type == FeatureActionType.ADD_REACTION
    assert res.emoji == "🔥"
    assert res.target_channel_id == 44

    # 2eme burst dans le meme channel : cooldown -> None
    res2 = await should_add_activity_reaction(test_guild, channel_id=44, target_message_id=100, recent_message_count=20, window_minutes=2)
    assert res2 is None

    # === Test 5: inactivity nudge ===
    cfg.inactivity_nudge_enabled = True
    cfg.inactivity_nudge_channel_ids = [55]
    cfg.inactivity_nudge_threshold_hours = 24
    await save_config(test_guild, cfg)

    # Salon non liste -> None
    res = await should_nudge_inactive_channel(test_guild, channel_id=999, last_message_at=now - timedelta(hours=48), now=now)
    assert res is None

    # Salon liste mais pas assez silencieux -> None
    res = await should_nudge_inactive_channel(test_guild, channel_id=55, last_message_at=now - timedelta(hours=10), now=now)
    assert res is None

    # Silencieux suffisamment -> nudge
    res = await should_nudge_inactive_channel(test_guild, channel_id=55, last_message_at=now - timedelta(hours=48), now=now)
    assert res is not None
    assert res.action_type == FeatureActionType.POST_MESSAGE
    assert res.target_channel_id == 55

    # === Test 6: theme days ===
    cfg.theme_days_enabled = True
    cfg.theme_days = {now.weekday(): "Music Monday"}
    cfg.theme_days_channel_id = 66
    await save_config(test_guild, cfg)

    res = await get_theme_for_today(test_guild, now=now)
    assert res is not None
    assert "Music Monday" in res.content

    # 2eme appel meme jour -> None
    res2 = await get_theme_for_today(test_guild, now=now)
    assert res2 is None

    # === Test 7: weekly digest ===
    cfg.weekly_digest_enabled = True
    cfg.weekly_digest_channel_id = 77
    cfg.weekly_digest_day_of_week = now.weekday()
    cfg.weekly_digest_hour_utc = max(0, now.hour - 1)
    await save_config(test_guild, cfg)

    stats = WeeklyStats(
        new_members=12, total_messages=4500, voice_hours=85,
        most_active_channel=(123, 1200),
        top_contributors=[(1, 800), (2, 600), (3, 400)],
    )
    res = await build_weekly_digest(test_guild, stats, now=now)
    assert res is not None
    assert "12" in res.content
    assert "4500" in res.content
    assert "<@1>" in res.content
    assert "🥇" in res.content

    # 2eme appel meme semaine -> None
    res2 = await build_weekly_digest(test_guild, stats, now=now)
    assert res2 is None

    # Cleanup
    for f in (Path("data") / "community").glob(f"{test_guild}_*.json"):
        f.unlink()

    print("[OK] community_features")


async def test_antiscam():
    from antiscam import (
        analyze_message, extract_urls, domain_of,
        is_known_phishing_domain, is_url_shortener, is_suspicious_tld,
        is_ip_url, has_suspicious_lookalike, find_scam_keywords,
        evaluate_and_decide, THREAT_THRESHOLD,
    )
    from protection_guards import (
        Action, AutoEventType, MemberContext,
        ProtectionPolicy, save_policy, reload_policy,
    )
    from pathlib import Path

    # Test extract_urls
    urls = extract_urls("Check this https://example.com/path and www.foo.bar/x")
    assert any("example.com" in u for u in urls)
    assert any("foo.bar" in u for u in urls)

    # Test domain_of
    assert domain_of("https://www.example.com/path") == "example.com"
    assert domain_of("http://sub.foo.com:8080/x") == "sub.foo.com"
    assert domain_of("https://discord-gift.com") == "discord-gift.com"

    # Test phishing detection
    assert is_known_phishing_domain("discord-gift.com")
    assert is_known_phishing_domain("dlscord.gift")
    assert not is_known_phishing_domain("discord.com")
    assert not is_known_phishing_domain("example.com")

    # Test shortener
    assert is_url_shortener("bit.ly")
    assert not is_url_shortener("youtube.com")

    # Test suspicious TLD
    assert is_suspicious_tld("foo.gift")
    assert not is_suspicious_tld("foo.com")

    # Test IP URL
    assert is_ip_url("http://192.168.1.1/")
    assert is_ip_url("https://8.8.8.8/path")
    assert not is_ip_url("https://example.com/")

    # Test lookalike
    assert has_suspicious_lookalike("d1scord.com")
    assert has_suspicious_lookalike("dlscord-nitro.com")
    assert has_suspicious_lookalike("disc0rd.gift")
    assert not has_suspicious_lookalike("discord.com")

    # Test keywords
    kws = find_scam_keywords("Hey check this out, free nitro for everyone, claim now!")
    assert "free nitro" in kws
    assert "claim now" in kws

    # === Test 1: message LEGITIME (pas de threat) ===
    res = await analyze_message("Hello les amis, comment allez-vous ?")
    assert res.is_threat is False
    assert res.confidence < THREAT_THRESHOLD

    # === Test 2: lien YouTube legitime (pas de threat) ===
    res = await analyze_message("Regardez cette video https://www.youtube.com/watch?v=abc")
    # Pas de domaine phishing, pas de keywords -> confidence 0
    assert res.is_threat is False
    assert res.confidence < THREAT_THRESHOLD

    # === Test 3: domaine phishing connu -> high confidence, BAN suggested ===
    res = await analyze_message("Click here for free nitro: https://discord-gift.com/claim")
    assert res.is_threat is True
    assert res.confidence >= 0.85
    assert res.event_type == AutoEventType.PHISHING
    assert res.suggested_action == Action.BAN
    assert any("discord-gift.com" in e.lower() for e in res.evidence)

    # === Test 4: typosquat lookalike -> high confidence ===
    res = await analyze_message("Verify your account: https://dlscord-nitro.com/verify")
    assert res.is_threat is True
    assert res.event_type == AutoEventType.PHISHING

    # === Test 5: free nitro keyword sans URL -> warning seulement ===
    res = await analyze_message("Y a-t-il moyen d'avoir du free nitro ?")
    # Juste 1 keyword -> confidence ~0.15, sous threshold de 0.3 generalement
    # Note: peut etre legit (membre demande) -> faible confidence
    assert res.confidence < 0.5

    # === Test 6: combo URL + multiple keywords -> medium-high ===
    res = await analyze_message("Free nitro!! Click here: https://random-site.io claim now your free discord nitro!")
    # Plusieurs kw + URL non whiteliste -> bonus combo
    assert res.confidence >= 0.4
    assert res.is_threat is True

    # === Test 7: IP URL -> suspect ===
    res = await analyze_message("Telecharge ici: http://192.168.1.50/file.exe")
    assert res.confidence >= 0.4
    assert any("ip nue" in e.lower() for e in res.evidence)

    # === Test 8: pipeline complet evaluate_and_decide ===
    # Newbie + phishing detecte -> BAN
    test_guild = 444444444
    pol_path = Path("data") / "protection" / f"{test_guild}_policy.json"
    if pol_path.exists():
        pol_path.unlink()
    aud_path = Path("data") / "protection" / "audit" / f"{test_guild}.jsonl"
    if aud_path.exists():
        aud_path.unlink()
    await reload_policy(test_guild)

    newbie = MemberContext(
        user_id=11111, user_name="newbie", role_ids=[],
        account_age_days=1, server_age_days=0, message_count=0,
    )
    analysis, decision = await evaluate_and_decide(
        "Free nitro: https://discord-gift.com/claim",
        test_guild, newbie,
    )
    assert analysis.is_threat
    assert decision is not None
    assert decision.final_action == Action.BAN, f"Newbie phishing should BAN: {decision.final_action}"

    # === Test 9: veteran + meme phishing -> LOG only (trust immune) ===
    veteran = MemberContext(
        user_id=22222, user_name="veteran", role_ids=[],
        account_age_days=400, server_age_days=200, message_count=2000,
        has_privileged_role=True, is_booster=True,
    )
    analysis, decision = await evaluate_and_decide(
        "Free nitro: https://discord-gift.com/claim",
        test_guild, veteran,
    )
    assert analysis.is_threat
    assert decision.final_action == Action.LOG, f"Veteran trust should LOG: {decision.final_action}"

    # === Test 10: giveaway legitime -> LOG (pattern whitelist) ===
    # Le message a "🎁" + "winner" + "giveaway" -> giveaway pattern detecte
    # par protection_guards, donc malgre l'analyse anti-scam, pas d'action.
    analysis, decision = await evaluate_and_decide(
        "🎁 GIVEAWAY 🎁 Tirage pour le winner ! Concours interne du serveur",
        test_guild, newbie,
    )
    # Soit l'analyse ne detecte rien (pas d'URL, pas de scam keyword),
    # soit la decision finale est LOG via le pattern giveaway whitelist
    if analysis.is_threat:
        assert decision.final_action == Action.LOG, "Giveaway legitime ne doit pas etre sanctionne"

    # Cleanup
    if pol_path.exists():
        pol_path.unlink()
    if aud_path.exists():
        aud_path.unlink()

    print("[OK] antiscam")


async def test_activity_tracker():
    from activity_tracker import (
        track_message, track_voice_join, track_voice_leave,
        track_helpful_reaction, get_user_stats, get_top_contributors,
        get_guild_stats, get_member_activity, prune_old_data,
        is_helpful_reaction, HELPFUL_EMOJIS,
    )
    from datetime import datetime, timezone, timedelta
    from pathlib import Path

    test_guild = 333333333

    # Cleanup pre-test
    gdir = Path("data") / "activity" / str(test_guild)
    if gdir.exists():
        for f in gdir.glob("*.json"):
            f.unlink()

    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)
    week_ago = now - timedelta(days=6)

    # === Test 1: track messages ===
    await track_message(test_guild, user_id=1, channel_id=100, dt=now)
    await track_message(test_guild, user_id=1, channel_id=100, dt=now)
    await track_message(test_guild, user_id=1, channel_id=200, dt=now)
    await track_message(test_guild, user_id=2, channel_id=100, dt=now)
    await track_message(test_guild, user_id=1, channel_id=100, dt=yesterday)

    stats = await get_user_stats(test_guild, user_id=1, days=7)
    # 3 today + 1 yesterday = 4 total messages
    assert stats.message_count == 4, f"Expected 4, got {stats.message_count}"
    assert stats.channels_active == 2  # channels 100 and 200

    stats2 = await get_user_stats(test_guild, user_id=2, days=7)
    assert stats2.message_count == 1

    stats3 = await get_user_stats(test_guild, user_id=999, days=7)
    assert stats3.message_count == 0

    # === Test 2: voice tracking ===
    voice_join_t = now - timedelta(minutes=45)
    await track_voice_join(test_guild, user_id=1, dt=voice_join_t)
    await track_voice_leave(test_guild, user_id=1, dt=now)

    stats_v = await get_user_stats(test_guild, user_id=1, days=7)
    assert stats_v.voice_minutes >= 40, f"Expected ~45min, got {stats_v.voice_minutes}"

    # Voice leave sans join : ne plante pas, pas d'effet
    await track_voice_leave(test_guild, user_id=99, dt=now)

    # === Test 3: helpful reactions ===
    await track_helpful_reaction(test_guild, message_author_id=1, dt=now)
    await track_helpful_reaction(test_guild, message_author_id=1, dt=now)
    await track_helpful_reaction(test_guild, message_author_id=2, dt=now)

    stats_r = await get_user_stats(test_guild, user_id=1, days=7)
    assert stats_r.helpful_reactions == 2

    # === Test 4: top contributors ===
    top = await get_top_contributors(test_guild, days=7, limit=10)
    assert len(top) == 2  # users 1 and 2
    assert top[0].user_id == 1  # user 1 has more messages
    assert top[0].message_count == 4
    assert top[1].user_id == 2

    # === Test 5: guild stats ===
    gstats = await get_guild_stats(test_guild, days=7)
    assert gstats.total_messages == 5
    assert gstats.voice_hours == 0  # 45min < 60min => 0h
    assert gstats.most_active_channel is not None
    assert gstats.most_active_channel[0] == 100  # channel 100 has 4 messages
    assert gstats.most_active_channel[1] == 4
    assert len(gstats.top_contributors) == 2

    # === Test 6: get_member_activity (for spotlight) ===
    activity = await get_member_activity(test_guild, days=7, limit=10)
    assert len(activity) == 2
    assert activity[0].user_id == 1
    assert activity[0].message_count == 4

    # === Test 7: helpful reaction emoji check ===
    assert is_helpful_reaction("👍")
    assert is_helpful_reaction("❤️")
    assert is_helpful_reaction("🌟")
    assert not is_helpful_reaction("😈")
    assert not is_helpful_reaction("💩")

    # === Test 8: prune old data ===
    # Cree un faux fichier > 90j
    old_path = gdir / "2020-01-01.json"
    old_path.write_text("{}", encoding="utf-8")
    deleted = await prune_old_data(test_guild, max_age_days=90)
    assert deleted >= 1
    assert not old_path.exists()

    # Cleanup
    if gdir.exists():
        for f in gdir.glob("*.json"):
            f.unlink()
        try:
            gdir.rmdir()
        except OSError:
            pass

    print("[OK] activity_tracker")


async def test_tracking_layer():
    import tracking_layer
    from tracking_layer import (
        was_posted, has_active_announcement, record_post,
        list_announcements, mark_deleted, remove_record,
        prune_old, cleanup_deleted_sources,
    )
    from pathlib import Path

    test_guild = 222222222

    # Cleanup pre-test
    p = tracking_layer.DATA_DIR / f"{test_guild}.json"
    if p.exists():
        p.unlink()
    tracking_layer._cache.pop(test_guild, None)
    tracking_layer._loaded_guilds.discard(test_guild)

    # === Test 1: was_posted vide initialement ===
    assert await was_posted(test_guild, "twitter", "elonmusk", "tweet_123") is False

    # === Test 2: record + was_posted ===
    await record_post(
        test_guild, "twitter", "elonmusk", "tweet_123",
        channel_id=999, message_id=10001,
        post_type="tweet", title="Hello world", url="https://twitter.com/elonmusk/status/tweet_123",
    )
    assert await was_posted(test_guild, "twitter", "elonmusk", "tweet_123") is True

    # Case insensitive sur username
    assert await was_posted(test_guild, "twitter", "ELONMUSK", "tweet_123") is True

    # Mais pas un autre post_id
    assert await was_posted(test_guild, "twitter", "elonmusk", "tweet_999") is False

    # === Test 3: persistance (clear cache, re-check) ===
    tracking_layer._cache.pop(test_guild, None)
    tracking_layer._loaded_guilds.discard(test_guild)
    assert await was_posted(test_guild, "twitter", "elonmusk", "tweet_123") is True

    # === Test 4: list_announcements avec filtres ===
    await record_post(
        test_guild, "youtube", "MrBeast", "vid_42",
        channel_id=999, message_id=10002,
        post_type="video", title="Beast Video",
    )
    await record_post(
        test_guild, "twitter", "jack", "tweet_777",
        channel_id=999, message_id=10003,
        post_type="tweet",
    )

    all_anns = await list_announcements(test_guild)
    assert len(all_anns) == 3

    twitter_anns = await list_announcements(test_guild, platform="twitter")
    assert len(twitter_anns) == 2

    elon_anns = await list_announcements(test_guild, username="elonmusk")
    assert len(elon_anns) == 1

    # === Test 5: mark_deleted + has_active_announcement ===
    assert await has_active_announcement(test_guild, "twitter", "elonmusk", "tweet_123") is True
    await mark_deleted(test_guild, "twitter", "elonmusk", "tweet_123")
    assert await has_active_announcement(test_guild, "twitter", "elonmusk", "tweet_123") is False
    # was_posted reste True (empeche re-post)
    assert await was_posted(test_guild, "twitter", "elonmusk", "tweet_123") is True

    active_anns = await list_announcements(test_guild, only_active=True)
    assert len(active_anns) == 2  # MrBeast + jack
    all_anns2 = await list_announcements(test_guild, only_active=False)
    assert len(all_anns2) == 3

    # === Test 6: cleanup_deleted_sources avec mock ===
    class FakeChannel:
        def __init__(self, cid):
            self.id = cid
            self.deleted_messages = []

        async def fetch_message(self, mid):
            class FakeMsg:
                async def delete(_self):
                    pass
            return FakeMsg()

    class FakeGuild:
        def __init__(self):
            self.id = test_guild
            self.channels = {999: FakeChannel(999)}

        def get_channel(self, cid):
            return self.channels.get(cid)

    g = FakeGuild()

    # Liveness callback : MrBeast vid_42 considere mort, jack tweet_777 vivant
    async def liveness_cb(tp):
        if tp.platform == "youtube" and tp.post_id == "vid_42":
            return False  # source supprimee
        return True

    report = await cleanup_deleted_sources(g, liveness_cb)
    assert report["deleted"] == 1
    assert report["checked"] >= 1

    # MrBeast est marque deleted
    assert await has_active_announcement(test_guild, "youtube", "MrBeast", "vid_42") is False
    # Mais jack est toujours actif
    assert await has_active_announcement(test_guild, "twitter", "jack", "tweet_777") is True

    # === Test 7: remove_record (cas owner supprime un compte tracke) ===
    ok = await remove_record(test_guild, "twitter", "jack", "tweet_777")
    assert ok is True
    anns = await list_announcements(test_guild, only_active=False)
    assert not any(a.username == "jack" for a in anns)

    # === Test 8: prune_old ===
    # Force un timestamp ancien sur un record
    cache = tracking_layer._cache[test_guild]
    for tp in cache.values():
        if tp.deleted:
            tp.posted_at = 0  # tres vieux
    pruned = await prune_old(test_guild, max_days=180)
    assert pruned >= 1

    # Cleanup
    if p.exists():
        p.unlink()
    tracking_layer._cache.pop(test_guild, None)
    tracking_layer._loaded_guilds.discard(test_guild)

    print("[OK] tracking_layer")


async def main():
    test_vocabulary()
    test_help_system()
    test_engagement()
    await test_permissions()
    await test_backup()
    await test_social_media()
    await test_protection()
    await test_community_features()
    await test_antiscam()
    await test_activity_tracker()
    await test_tracking_layer()
    print()
    print("======================================")
    print("Tous les tests passent : 11/11")
    print("Phase 0 + 1.1 a 1.8 (tracking layer) OK")
    print("======================================")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"[FAIL] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
