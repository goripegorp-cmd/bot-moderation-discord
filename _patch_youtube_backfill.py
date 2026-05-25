"""Patch YouTube feeds : backfill 7 jours + iter sur 5 entrees."""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import re
from pathlib import Path

src = Path("bot.py").read_text(encoding="utf-8")

# Find the block to replace
start_marker = "            entries = root.findall('atom:entry', ns)\n            if not entries:\n                continue\n            \n            entry = entries[0]"
end_marker = '            await asyncio.sleep(1)\n\n        except Exception as ex:\n            print(f"Erreur YouTube feed {feed}: {ex}")\n            continue'

i = src.find(start_marker)
if i == -1:
    print("Start marker not found")
    raise SystemExit(1)

# Find end_marker after start
j = src.find(end_marker, i)
if j == -1:
    print("End marker not found")
    raise SystemExit(1)

j_end = j + len(end_marker)

new_block = '''            entries = root.findall('atom:entry', ns)
            if not entries:
                continue

            # Phase 3.0j : iter sur 5 dernieres entrees pour backfill 7 jours
            posts_to_publish = []
            for entry in entries[:BACKFILL_MAX_POSTS_PER_FEED]:
                video_id_elem = entry.find('yt:videoId', ns)
                title_elem = entry.find('atom:title', ns)
                if video_id_elem is None or title_elem is None:
                    continue
                video_id = video_id_elem.text
                title = title_elem.text or ""
                published_elem = entry.find('atom:published', ns)
                published_at = published_elem.text if published_elem is not None else None

                if await tracking2026.was_posted(guild.id, "youtube", channel_id, video_id):
                    continue

                # Description nettoyee
                media_group = entry.find('media:group', ns)
                description = ""
                if media_group is not None:
                    desc_elem = media_group.find('media:description', ns)
                    if desc_elem is not None and desc_elem.text:
                        raw = desc_elem.text.strip()
                        clean_lines = []
                        for line in raw.split('\\n'):
                            line = line.strip()
                            if not line:
                                break
                            skip_words = ['abonne', 'subscribe', 'like', 'commentes', 'rejoins',
                                          'follow', 'clique', 'activer', 'merci de']
                            if any(sw in line.lower() for sw in skip_words):
                                continue
                            if len(line) < 5 or line.startswith('-') or line.startswith('='):
                                continue
                            clean_lines.append(line)
                            if len('\\n'.join(clean_lines)) >= 150:
                                break
                        description = '\\n'.join(clean_lines)[:150]
                        if len(description) < len('\\n'.join(clean_lines)):
                            description += "..."

                video_url = f"https://www.youtube.com/watch?v={video_id}"

                # Trop vieux -> record sans poster
                if published_at and not _is_recent_iso(published_at, BACKFILL_MAX_AGE_DAYS):
                    try:
                        await tracking2026.record_post(
                            guild.id, "youtube", channel_id, video_id,
                            channel_id=target_channel.id, message_id=0,
                            post_type="video", title=title, url=video_url,
                        )
                    except Exception:
                        pass
                    continue

                posts_to_publish.append((video_id, title, description, video_url))

            # Plus ancien en premier (le plus recent finit en bas du salon)
            posts_to_publish.reverse()

            cache_key = f"yt_{guild.id}_{channel_id}"
            yt_avatar = await fetch_avatar_url('youtube', channel_id, session)

            for video_id, title, description, video_url in posts_to_publish:
                posted_content[cache_key] = video_id

                e = discord.Embed(color=0xFF0000, url=video_url)
                e.set_author(name=f"YOUTUBE - {channel_name}",
                             url=f"https://www.youtube.com/channel/{channel_id}",
                             icon_url=_YT_ICON)
                e.title = f"YT  {title}"[:256]

                if description and len(description.strip()) > 10:
                    e.description = f"*{description}*\\n\\n[Regarder sur YouTube]({video_url})"
                else:
                    e.description = f"[Regarder sur YouTube]({video_url})"

                e.set_image(url=f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg")
                if yt_avatar:
                    e.set_thumbnail(url=yt_avatar)
                e.set_footer(text=f"YouTube - {channel_name}", icon_url=_YT_ICON)
                e.timestamp = now()

                _yt_msg = await webhook_send(target_channel, 'youtube', embed=e)
                try:
                    await tracking2026.record_post(
                        guild.id, "youtube", channel_id, video_id,
                        channel_id=target_channel.id,
                        message_id=getattr(_yt_msg, 'id', 0) or 0,
                        post_type="video", title=title, url=video_url,
                    )
                except Exception:
                    pass
                await asyncio.sleep(1)

        except Exception as ex:
            print(f"Erreur YouTube feed {feed}: {ex}")
            continue'''

new_src = src[:i] + new_block + src[j_end:]

# Restore the YT emoji and other emojis I had to escape in source
# (we want the actual emoji characters in the file, not escaped)
# Actually in the new_block I removed emojis to be safe in the script.
# Let me restore them with a post-processing step.

new_src = new_src.replace(
    '"YOUTUBE - {channel_name}"', '"YOUTUBE • {channel_name}"'
).replace(
    'f"YT  {title}"', 'f"▶️ {title}"'
).replace(
    '[Regarder sur YouTube]', '🔗 [**Regarder sur YouTube**]'
).replace(
    'YouTube - {channel_name}", icon', 'YouTube • {channel_name}", icon'
)

Path("bot.py").write_text(new_src, encoding="utf-8")
print("Patch applied. Bytes diff:", len(new_src) - len(src))
