import asyncio
from datetime import datetime
import os
import discord
from discord.ext import commands, tasks
from zoneinfo import ZoneInfo

# --- CONFIGURATION ---
BOT_TOKEN = TOKEN = os.getenv("DISCORD_TOKEN")

MUSIC_TEXT_CHANNEL_ID = os.getenv (DISCORD CHANNEL ID)
RADIO_VOICE_CHANNEL_ID = os.getenv (DISCORD CHANNEL ID)

# Define your UTC+5 timezone
TZ_OFFSET = ZoneInfo("Etc/GMT-5")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

playlist_queue = []
current_index = 0
MAX_QUEUE_SIZE = 30

FFMPEG_OPTIONS = {
    "before_options": (
        "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
    ),
    "options": "-vn",
}


async def scan_channel_history():
  """Scans past messages in the music text channel for audio files on startup."""
  global playlist_queue
  channel = bot.get_channel(MUSIC_TEXT_CHANNEL_ID)
  if not channel:
    return

  print(
      f"📜 Scanning Discord channel history for tracks in #{channel.name}..."
  )
  found_count = 0
  supported_extensions = (".mp3", ".wav", ".m4a", ".ogg", ".flac")

  # Read up to the last 100 messages in the text channel
  async for message in channel.history(limit=100):
    if message.attachments:
      for attachment in message.attachments:
        if attachment.filename.lower().endswith(supported_extensions):
          if attachment.url not in playlist_queue:
            if len(playlist_queue) < MAX_QUEUE_SIZE:
              # Insert at the beginning so chronological order is maintained
              playlist_queue.insert(0, attachment.url)
              found_count += 1

  print(f"✨ Loaded {found_count} tracks from channel history into queue.")


async def play_next(vc):
  global current_index
  if not playlist_queue:
    await asyncio.sleep(5)
    if vc and vc.is_connected():
      bot.loop.create_task(play_next(vc))
    return

  if current_index >= len(playlist_queue):
    current_index = 0  # Infinite loop back to start

  stream_url = playlist_queue[current_index]

  try:
    if vc and vc.is_connected() and not vc.is_playing():
      vc.play(
          discord.FFmpegPCMAudio(
              stream_url, executable="ffmpeg", **FFMPEG_OPTIONS
          ),
          after=lambda e: bot.loop.create_task(song_finished(vc)),
      )
      print(f"▶️ Now playing index {current_index}: {stream_url}")

  except Exception as e:
    print(f"\n❌ ERROR PLAYING TRACK: {e}\n")
    if len(playlist_queue) > 0:
      playlist_queue.pop(current_index)
    await asyncio.sleep(3)
    if vc and vc.is_connected():
      bot.loop.create_task(play_next(vc))


async def song_finished(vc):
  global current_index
  current_index += 1
  await play_next(vc)


@tasks.loop(minutes=2)
async def schedule_checker():
  vc = discord.utils.get(bot.voice_clients)
  if not vc or not vc.is_connected():
    channel = bot.get_channel(RADIO_VOICE_CHANNEL_ID)
    if channel:
      try:
        await channel.connect(timeout=60.0)
      except Exception:
        pass


@bot.event
async def on_ready():
  print(f"Logged in as {bot.user.name} - Radio is active!")

  # 1. Scan past channel messages for existing audio files
  await scan_channel_history()

  if not schedule_checker.is_running():
    schedule_checker.start()

  await asyncio.sleep(2)
  channel = bot.get_channel(RADIO_VOICE_CHANNEL_ID)
  if channel:
    vc = discord.utils.get(bot.voice_clients)
    if not vc or not vc.is_connected():
      print(f"🔌 Connecting to voice channel: {channel.name}...")
      vc = await channel.connect(timeout=60.0)
      print("✅ Connected successfully!")

    # 2. Auto-start playback if queue has tracks
    if playlist_queue and not vc.is_playing():
      bot.loop.create_task(play_next(vc))


@bot.event
async def on_message(message):
  if message.author == bot.user:
    return

  if message.channel.id == MUSIC_TEXT_CHANNEL_ID:
    target_url = None

    # Check for direct audio file attachments
    if message.attachments:
      for attachment in message.attachments:
        if attachment.filename.lower().endswith(
            (".mp3", ".wav", ".m4a", ".ogg", ".flac")
        ):
          target_url = attachment.url
          break
    elif "http://" in message.content or "https://" in message.content:
      target_url = message.content.strip()

    if target_url:
      # If queue is full (30 items), remove the oldest track to make room
      if len(playlist_queue) >= MAX_QUEUE_SIZE:
        removed = playlist_queue.pop(0)
        print(f"🗑️ Queue full ({MAX_QUEUE_SIZE}). Dropped oldest track: {removed}")

      playlist_queue.append(target_url)
      print(f"Added to community playlist: {target_url}")
      await message.add_reaction("🎵")

      vc = discord.utils.get(bot.voice_clients)
      if vc and vc.is_connected() and not vc.is_playing():
        bot.loop.create_task(play_next(vc))

  await bot.process_commands(message)


# ==========================================
# --- RADIO COMMANDS ---
# ==========================================


@bot.command(name="play")
async def play_on_request(ctx, *, query: str = None):
  if not ctx.author.voice:
    await ctx.send("❌ You need to be in a voice channel first!")
    return

  channel = ctx.author.voice.channel
  vc = ctx.voice_client

  if not vc or not vc.is_connected():
    vc = await channel.connect(timeout=60.0)

  if query:
    clean_query = query.strip()
    if len(playlist_queue) >= MAX_QUEUE_SIZE:
      playlist_queue.pop(0)
    playlist_queue.append(clean_query)
    await ctx.send(f"🎵 Added track to queue: `{clean_query}`")

  if not vc.is_playing() and playlist_queue:
    await ctx.send("▶️ Starting playback...")
    bot.loop.create_task(play_next(vc))
  else:
    await ctx.send("📻 Radio is already rolling or queue is empty!")


@bot.command()
async def stop(ctx):
  global playlist_queue, current_index
  playlist_queue.clear()
  current_index = 0

  if ctx.voice_client:
    ctx.voice_client.stop()
    await ctx.voice_client.disconnect()
    await ctx.send("🛑 Radio stopped, playlist cleared, and disconnected.")
  else:
    await ctx.send("I'm not in a voice channel right now!")


@bot.command()
async def skip(ctx):
  if ctx.voice_client and ctx.voice_client.is_playing():
    ctx.voice_client.stop()
    await ctx.send("⏭️ Skipped to the next track!")
  else:
    await ctx.send("Nothing is playing right now.")


@bot.command(aliases=["queue"])
async def q(ctx, action: str = None):
  if action == "list" or action is None:
    if not playlist_queue:
      await ctx.send("📭 The queue is currently empty.")
      return

    queue_text = f"**📻 Current Radio Queue ({len(playlist_queue)}/{MAX_QUEUE_SIZE} - Looping):**\n"
    for i, url in enumerate(playlist_queue):
      display_name = (
          url.split("/")[-1].split("?")[0]
          if "cdn.discordapp.com" in url
          else url
      )
      if i == current_index:
        queue_text += f"👉 **{i + 1}.** {display_name} *(Now Playing)*\n"
      else:
        queue_text += f"**{i + 1}.** {display_name}\n"

    await ctx.send(queue_text)


bot.run(BOT_TOKEN)