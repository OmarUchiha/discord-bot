"""
Discord Translation Bot
=======================
A bot that automatically translates messages for each user
based on their preferred language.

Libraries used:
- discord.py     : connects to Discord and handles events
- deep-translator: free translation (uses Google Translate under the hood)
- langdetect     : detects what language a message is written in
- python-dotenv  : loads your secret token from a .env file
"""

import discord
from discord import app_commands
from discord.ext import commands
from deep_translator import GoogleTranslator
from langdetect import detect, LangDetectException
from dotenv import load_dotenv
import os
import json

# ─────────────────────────────────────────────
# SETUP
# ─────────────────────────────────────────────

# Load the token from your .env file so it's never hardcoded in the code
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# This file will store each user's preferred language on disk
# so preferences are remembered even if the bot restarts
PREFS_FILE = "user_prefs.json"

# This file stores recent messages from each user
# used to auto-detect their preferred language if they haven't set one
HISTORY_FILE = "user_history.json"


def load_json(filepath):
    """Load a JSON file from disk. Return empty dict if it doesn't exist yet."""
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            return json.load(f)
    return {}


def save_json(filepath, data):
    """Save a Python dictionary to disk as a JSON file."""
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


# Load saved preferences and message history into memory
user_prefs = load_json(PREFS_FILE)       # { "user_id": "ar" }
user_history = load_json(HISTORY_FILE)   # { "user_id": ["hello", "how are you"] }


# ─────────────────────────────────────────────
# BOT INITIALIZATION
# ─────────────────────────────────────────────

# Set up the bot with all necessary permissions (called "intents")
intents = discord.Intents.default()
intents.message_content = True   # Required to read message text
intents.members = True           # Required to look up server members

# Create the bot object
# commands.Bot gives us both prefix commands (!cmd) and slash commands (/cmd)
bot = commands.Bot(command_prefix="!", intents=intents)


# ─────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────

def get_user_language(user_id: str) -> str | None:
    """
    Get a user's preferred language.
    
    First checks if they manually set one with /setlang.
    If not, tries to detect it from their recent messages.
    Returns None if we don't have enough information.
    """
    # Check if they set a language manually
    if user_id in user_prefs:
        return user_prefs[user_id]

    # Try to detect from their message history
    if user_id in user_history and len(user_history[user_id]) >= 3:
        # Combine their last 5 messages and detect the language
        sample_text = " ".join(user_history[user_id][-5:])
        try:
            detected = detect(sample_text)
            return detected
        except LangDetectException:
            pass

    return None  # Not enough info yet


def translate_text(text: str, target_lang: str) -> str:
    """
    Translate text into the target language using Google Translate (free).
    
    Returns the translated text, or the original if translation fails.
    target_lang should be a language code like 'ar', 'fr', 'es', 'de', etc.
    """
    try:
        # Detect the source language automatically
        source_lang = detect(text)

        # No need to translate if it's already in the target language
        if source_lang == target_lang:
            return text

        # Perform the translation
        translated = GoogleTranslator(
            source=source_lang,
            target=target_lang
        ).translate(text)

        return translated if translated else text

    except Exception as e:
        # If anything goes wrong, return the original text
        print(f"Translation error: {e}")
        return text


def record_message(user_id: str, text: str):
    """
    Save a user's message to their history.
    We keep only the last 20 messages to avoid the file growing too large.
    This history is used for auto-detecting their language preference.
    """
    if user_id not in user_history:
        user_history[user_id] = []

    user_history[user_id].append(text)

    # Keep only the most recent 20 messages
    user_history[user_id] = user_history[user_id][-20:]

    save_json(HISTORY_FILE, user_history)


# ─────────────────────────────────────────────
# DISCORD UI: TRANSLATE BUTTON
# ─────────────────────────────────────────────

class TranslateButton(discord.ui.View):
    """
    A Discord UI View (a container for buttons/menus).
    
    This creates the "🌐 Translate" button that appears under every message.
    When a user clicks it, the bot privately sends them a translation
    in their preferred language.
    """

    def __init__(self, original_text: str):
        # timeout=None means the button never expires
        super().__init__(timeout=None)
        self.original_text = original_text

    @discord.ui.button(label="🌐 Translate", style=discord.ButtonStyle.secondary)
    async def translate_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        """
        This function runs when someone clicks the Translate button.
        
        interaction.user  = the person who clicked the button
        interaction       = the click event from Discord
        """
        user_id = str(interaction.user.id)
        target_lang = get_user_language(user_id)

        # If we don't know their preferred language yet, ask them to set it
        if target_lang is None:
            await interaction.response.send_message(
                "I don't know your preferred language yet! "
                "Use `/setlang` to set it — for example: `/setlang Arabic`\n\n"
                "I'll also learn it automatically after you send a few messages.",
                ephemeral=True  # ephemeral = only visible to the person who clicked
            )
            return

        # Translate the original message into their language
        translated = translate_text(self.original_text, target_lang)

        # Send the translation privately (only they can see it)
        await interaction.response.send_message(
            f"**Translation ({target_lang}):**\n{translated}",
            ephemeral=True
        )


# ─────────────────────────────────────────────
# SLASH COMMANDS
# ─────────────────────────────────────────────

@bot.tree.command(
    name="setlang",
    description="Set your preferred language for translations"
)
@app_commands.describe(language="Your preferred language (e.g. Arabic, French, Spanish)")
async def setlang(interaction: discord.Interaction, language: str):
    """
    Slash command: /setlang <language>
    
    Lets users tell the bot which language they want messages translated into.
    Supports full language names like 'Arabic', 'French', 'Spanish', etc.
    """
    user_id = str(interaction.user.id)

    # Convert language name to a language code
    # deep-translator accepts full names like "arabic" or codes like "ar"
    language_lower = language.lower().strip()

    # Map of common language names to their ISO 639-1 codes
    # This helps users type natural names instead of cryptic codes
    language_map = {
        "arabic": "ar",
        "english": "en",
        "french": "fr",
        "spanish": "es",
        "german": "de",
        "italian": "it",
        "portuguese": "pt",
        "russian": "ru",
        "japanese": "ja",
        "korean": "ko",
        "chinese": "zh-CN",
        "turkish": "tr",
        "dutch": "nl",
        "polish": "pl",
        "swedish": "sv",
        "norwegian": "no",
        "danish": "da",
        "finnish": "fi",
        "greek": "el",
        "hebrew": "he",
        "hindi": "hi",
        "indonesian": "id",
        "malay": "ms",
        "thai": "th",
        "vietnamese": "vi",
        "czech": "cs",
        "slovak": "sk",
        "hungarian": "hu",
        "romanian": "ro",
        "ukrainian": "uk",
        "persian": "fa",
        "urdu": "ur",
        "bengali": "bn",
    }

    # Check if they typed a known language name
    if language_lower in language_map:
        lang_code = language_map[language_lower]
    else:
        # Assume they typed an ISO code directly (like "ar" or "fr")
        lang_code = language_lower

    # Save their preference
    user_prefs[user_id] = lang_code
    save_json(PREFS_FILE, user_prefs)

    await interaction.response.send_message(
        f"✅ Got it! I'll now translate messages into **{language.title()}** for you.\n"
        f"All messages will be auto-translated, and you can also click "
        f"the **🌐 Translate** button on any message.",
        ephemeral=True  # Only the user who ran the command sees this
    )


@bot.tree.command(
    name="mylang",
    description="Check what your current preferred language is"
)
async def mylang(interaction: discord.Interaction):
    """Slash command: /mylang — shows the user their current language setting."""
    user_id = str(interaction.user.id)
    lang = get_user_language(user_id)

    if lang:
        await interaction.response.send_message(
            f"Your preferred language is set to: **{lang}**\n"
            f"Use `/setlang` to change it.",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "You haven't set a preferred language yet. "
            "Use `/setlang` — for example: `/setlang Arabic`",
            ephemeral=True
        )


@bot.tree.command(
    name="translate",
    description="Manually translate a message into your preferred language"
)
@app_commands.describe(text="The text you want to translate")
async def translate_command(interaction: discord.Interaction, text: str):
    """Slash command: /translate <text> — translates any text on demand."""
    user_id = str(interaction.user.id)
    target_lang = get_user_language(user_id)

    if not target_lang:
        await interaction.response.send_message(
            "Please set your preferred language first with `/setlang`.",
            ephemeral=True
        )
        return

    translated = translate_text(text, target_lang)
    await interaction.response.send_message(
        f"**Translation ({target_lang}):**\n{translated}",
        ephemeral=True
    )


# ─────────────────────────────────────────────
# EVENT: ON MESSAGE
# This is the core of the bot. It runs every time someone sends a message.
# ─────────────────────────────────────────────

@bot.event
async def on_message(message: discord.Message):
    """
    Triggered every time a message is sent in any channel the bot can see.
    
    This does three things:
    1. Records the message for language auto-detection
    2. Adds a Translate button under the message (for manual translation)
    3. Sends private auto-translations to users who opted in
    """

    # Ignore messages from bots (including our own bot)
    # This prevents infinite loops where the bot translates its own messages
    if message.author.bot:
        return

    # Ignore very short messages (single words, emojis) — hard to translate reliably
    if len(message.content.strip()) < 1 or message.content.strip().replace(" ", "") == "" or all(char in "😀😁😂🤣😃😄😅😆😉😊😋😎😍😘🥰😗😙😚☺🙂🤗🤩🤔🤨😐😑😶🙄😏😣😥😮🤐😯😪😫🥱😴😌😛😜😝🤤😒😓😔😕🙃🤑😲☹🙁😖😞😟😤😢😭😦😧😨😩🤯😬😰😱🥵🥶😳🤪😵💫🤠🥸🥳🤡👹👺💀☠👻👽👾🤖" for char in message.content.strip()):
        return

    # Ignore messages that start with "/" (slash commands) or "!" (prefix commands)
    if message.content.startswith("/") or message.content.startswith("!"):
        await bot.process_commands(message)  # Still process any bot commands
        return

    user_id = str(message.author.id)
    original_text = message.content

    # ── Step 1: Record this message for language learning ──
    record_message(user_id, original_text)

    # ── Step 2: Add the Translate button under every message ──
    # We send a small follow-up message with just the button attached
    # The button stores the original text so it can translate it later
    view = TranslateButton(original_text=original_text)
    await message.reply(
        "*(click to translate)*",
        view=view,
        mention_author=False  # Don't ping the original author
    )

    # ── Step 3: Auto-translate for users who opted in ──
    # Loop through all members in the server to find who wants auto-translation
    guild = message.guild
    if guild is None:
        return  # Skip if the message is in a DM (no guild members)

    # Collect all unique language targets needed (to avoid duplicate translations)
    # Example: if 5 people all want Arabic, we only translate once
    lang_to_users: dict[str, list[discord.Member]] = {}

    for member in guild.members:
        # Skip bots and the message author (no need to translate your own message)
        if member.bot or member.id == message.author.id:
            continue

        member_id = str(member.id)
        target_lang = get_user_language(member_id)

        # Only auto-translate if this member has a preferred language set
        if target_lang is None:
            continue

        # Group members by their target language
        if target_lang not in lang_to_users:
            lang_to_users[target_lang] = []
        lang_to_users[target_lang].append(member)

    # Now translate once per unique language and DM each group
    for target_lang, members in lang_to_users.items():
        try:
            # Detect the source language of the message
            source_lang = detect(original_text)

            # Skip if the message is already in this target language
            if source_lang == target_lang:
                continue

            # Translate the message
            translated = translate_text(original_text, target_lang)

            # Send a private DM to each member who wants this language
            for member in members:
                try:
                    await member.send(
                        f"**Auto-translation of a message from "
                        f"{message.author.display_name} in "
                        f"#{message.channel.name}:**\n\n"
                        f"{translated}\n\n"
                        f"*(original: {message.jump_url})*"
                    )
                except discord.Forbidden:
                    # This means the user has DMs disabled — skip silently
                    pass

        except LangDetectException:
            # Can't detect language of this message — skip auto-translation
            pass

    # This line is important! It lets prefix commands (!cmd) still work
    await bot.process_commands(message)


# ─────────────────────────────────────────────
# EVENT: ON READY
# Runs once when the bot successfully connects to Discord
# ─────────────────────────────────────────────

@bot.event
async def on_ready():
    """Runs when the bot successfully logs in to Discord."""
    print(f"✅ Bot is online! Logged in as: {bot.user.name}")
    print(f"   Bot ID: {bot.user.id}")
    print(f"   Loaded preferences for {len(user_prefs)} users")
    print("─" * 40)

    # Sync all slash commands (/setlang, /translate, /mylang) with Discord
    # This makes them appear in the / menu for users
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} slash command(s)")
    except Exception as e:
        print(f"❌ Failed to sync commands: {e}")


# ─────────────────────────────────────────────
# START THE BOT
# ─────────────────────────────────────────────

# This is the last line — it starts the bot using your secret token
bot.run(TOKEN)