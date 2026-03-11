#!/usr/bin/env python3
"""
HellGPT — Profanity, delivered straight from Hell.
Discord bot with culturally-aware swearing traditions.
"""

import discord
from discord import app_commands
import asyncio
import logging
import json
import os
import re
import sqlite3
import configparser
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BOT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BOT_DIR.parent
CONFIG_PATH = BOT_DIR / "hellgpt.ini"

TRADITIONS = [
    "norwegian", "british", "american", "quebecois",
    "german", "italian", "french", "shakespeare",
]

SURPRISE_ROUTING = {
    "code": "german",
    "debug": "german",
    "deploy": "german",
    "bug": "german",
    "compile": "german",
    "relationship": "italian",
    "love": "italian",
    "feelings": "italian",
    "heart": "italian",
    "date": "italian",
    "form": "quebecois",
    "bureaucracy": "quebecois",
    "compliance": "quebecois",
    "tax": "quebecois",
    "paperwork": "quebecois",
    "incompetent": "british",
    "meeting": "british",
    "manager": "british",
    "colleague": "british",
    "email": "british",
    "fire": "american",
    "production": "american",
    "outage": "american",
    "crash": "american",
    "down": "american",
    "exist": "norwegian",
    "meaning": "norwegian",
    "point": "norwegian",
    "why": "norwegian",
    "life": "norwegian",
    "family": "french",
    "parent": "french",
    "inherit": "french",
    "legacy": "french",
    "ancestor": "french",
    "thou": "shakespeare",
    "code review": "shakespeare",
    "insult": "shakespeare",
}

MAX_DISCORD_LENGTH = 2000

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def filter_thinking_tags(text: str) -> str:
    """Remove <thinking>/<reflection> blocks from LLM responses."""
    cleaned = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<reflection>.*?</reflection>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"\n\s*\n\s*\n", "\n\n", cleaned)
    return cleaned.strip()


# ---------------------------------------------------------------------------
# Session Manager (SQLite)
# ---------------------------------------------------------------------------


@dataclass
class UserSession:
    user_id: int
    tradition: str = "norwegian"
    history: list = field(default_factory=list)
    targets: list = field(default_factory=list)
    heat_level: int = 1


class SessionManager:
    """Per-user session state backed by SQLite."""

    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self._init_db()

    def _init_db(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                user_id INTEGER PRIMARY KEY,
                tradition TEXT NOT NULL DEFAULT 'norwegian',
                history TEXT NOT NULL DEFAULT '[]',
                targets TEXT NOT NULL DEFAULT '[]',
                heat_level INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL DEFAULT ''
            )
        """)
        self.conn.commit()

    def get(self, user_id: int) -> UserSession:
        row = self.conn.execute(
            "SELECT user_id, tradition, history, targets, heat_level FROM sessions WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return UserSession(user_id=user_id)
        return UserSession(
            user_id=row[0],
            tradition=row[1],
            history=json.loads(row[2]),
            targets=json.loads(row[3]),
            heat_level=row[4],
        )

    def save(self, session: UserSession):
        self.conn.execute(
            """INSERT INTO sessions (user_id, tradition, history, targets, heat_level, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                   tradition=excluded.tradition,
                   history=excluded.history,
                   targets=excluded.targets,
                   heat_level=excluded.heat_level,
                   updated_at=excluded.updated_at""",
            (
                session.user_id,
                session.tradition,
                json.dumps(session.history[-6:]),  # Keep last 6 turns
                json.dumps(session.targets[-10:]),  # Keep last 10 targets
                session.heat_level,
                datetime.utcnow().isoformat(),
            ),
        )
        self.conn.commit()

    def reset(self, user_id: int):
        self.conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        self.conn.commit()


# ---------------------------------------------------------------------------
# Personality Loader
# ---------------------------------------------------------------------------


class PersonalityLoader:
    """Loads base personality + tradition overlays + data files."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.instructions_dir = project_root / "instructions"
        self.traditions_dir = self.instructions_dir / "traditions"
        self.data_dir = project_root / "data"

    def load_base_personality(self) -> str:
        """Load numbered instruction files from instructions/ in sort order."""
        files = sorted(self.instructions_dir.glob("[0-9][0-9]-*.md"))
        parts = []
        for f in files:
            try:
                parts.append(f.read_text(encoding="utf-8"))
            except Exception as e:
                logging.error(f"Failed reading personality file {f}: {e}")
        if not parts:
            return "You are HellGPT, a grumpy Norwegian freight clerk. Be helpful. Swear sparingly."
        return "\n\n---\n\n".join(parts)

    def load_tradition_overlay(self, tradition: str) -> str:
        """Load tradition-specific instruction overlay."""
        path = self.traditions_dir / f"{tradition}.md"
        if path.exists():
            try:
                return path.read_text(encoding="utf-8")
            except Exception as e:
                logging.error(f"Failed reading tradition overlay {path}: {e}")
        return ""

    def load_examples(self, tradition: str) -> str:
        """Load example conversations for a tradition."""
        path = self.data_dir / "examples" / f"{tradition}.md"
        if path.exists():
            try:
                return path.read_text(encoding="utf-8")
            except Exception as e:
                logging.error(f"Failed reading examples {path}: {e}")
        return ""

    def load_tradition_data(self, tradition: str) -> str:
        """Load YAML lexicon data if available."""
        path = self.data_dir / "traditions" / f"{tradition}.yaml"
        if path.exists():
            try:
                return path.read_text(encoding="utf-8")
            except Exception as e:
                logging.error(f"Failed reading tradition data {path}: {e}")
        return ""

    def load_pattern_data(self, tradition: str) -> str:
        """Load pattern/construction files if available."""
        # Check for tradition-specific patterns (any naming convention)
        patterns_dir = self.data_dir / "patterns"
        if not patterns_dir.exists():
            return ""
        matches = list(patterns_dir.glob(f"{tradition}*"))
        parts = []
        for path in sorted(matches):
            try:
                parts.append(path.read_text(encoding="utf-8"))
            except Exception as e:
                logging.error(f"Failed reading pattern data {path}: {e}")
        return "\n\n".join(parts)

    def build_system_prompt(self, session: UserSession) -> str:
        """Assemble the full system prompt for a user session."""
        parts = []

        # Layer 1: Base personality (identity, format, etc.)
        parts.append(self.load_base_personality())

        # Layer 2: Tradition overlay
        tradition = session.tradition
        overlay = self.load_tradition_overlay(tradition)
        if overlay:
            parts.append(overlay)

        # Layer 3: Tradition data (vocabulary, patterns)
        tradition_data = self.load_tradition_data(tradition)
        if tradition_data:
            parts.append(f"# Tradition Vocabulary Reference\n\n{tradition_data}")

        pattern_data = self.load_pattern_data(tradition)
        if pattern_data:
            parts.append(f"# Construction Patterns\n\n{pattern_data}")

        # Layer 4: Example conversations (most important — overrides rules)
        examples = self.load_examples(tradition)
        if examples:
            parts.append(f"# Example Exchanges (follow this register)\n\n{examples}")

        # Session context
        context_lines = [
            f"\n# Current Session State",
            f"- Active tradition: {tradition}",
            f"- Heat level: {session.heat_level}/5",
        ]
        if session.targets:
            context_lines.append(f"- Named targets: {', '.join(session.targets)}")
        context_lines.append("")
        context_lines.append(
            "You remain genuinely helpful. Profanity marks important moments — "
            "bad code, real frustration, actual insight. If you swear at everything "
            "equally, it means nothing."
        )
        parts.append("\n".join(context_lines))

        return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# LLM Client (Ollama Cloud via ollama SDK)
# ---------------------------------------------------------------------------


class LLMClient:
    """Thin wrapper around the Ollama SDK for chat completions."""

    def __init__(self, model: str, host: str, api_key: str, timeout: int = 180):
        from ollama import Client as OllamaClient

        self.model = model
        self.timeout = timeout
        headers = {"Authorization": f"Bearer {api_key}"}
        self.client = OllamaClient(host=host, headers=headers, timeout=timeout)
        logging.info(f"LLM client initialized: {model} @ {host}")

    def chat(self, system_prompt: str, messages: list[dict]) -> str:
        """Send a chat request. Returns the assistant response text."""
        prompt_messages = [{"role": "system", "content": system_prompt}]
        prompt_messages.extend(messages)

        try:
            response = self.client.chat(
                self.model,
                messages=prompt_messages,
                stream=False,
            )
        except Exception as e:
            logging.error(f"LLM request failed: {e}")
            raise

        # Ollama SDK returns an object, not a dict
        try:
            text = response.message.content or ""
        except AttributeError:
            # Fallback for older SDK versions that return dicts
            message = response.get("message", {})
            text = message.get("content", "")
        return filter_thinking_tags(text)


# ---------------------------------------------------------------------------
# Surprise Me Router
# ---------------------------------------------------------------------------


SURPRISE_REASONS = {
    "german": "Engineering disappointment detected",
    "italian": "Cosmic theatrical grievance required",
    "quebecois": "Sacred objects must be weaponized",
    "british": "Devastating understatement called for",
    "american": "Volume appropriate to situation",
    "norwegian": "Existential resignation warranted",
    "french": "Genealogical investigation needed",
    "shakespeare": "Elizabethan artillery required",
}


def route_surprise(user_message: str) -> tuple[str, str]:
    """Pick the best tradition for a message by scoring all keyword matches."""
    lower = user_message.lower()
    scores: dict[str, int] = {}
    for keyword, tradition in SURPRISE_ROUTING.items():
        if keyword in lower:
            scores[tradition] = scores.get(tradition, 0) + 1

    if not scores:
        return "norwegian", "Default — Hell is always a reasonable destination"

    best = max(scores, key=scores.get)
    return best, SURPRISE_REASONS.get(best, "Tradition selected")


# ---------------------------------------------------------------------------
# Discord Bot
# ---------------------------------------------------------------------------


class HellGPTBot:
    """The main HellGPT Discord bot."""

    def __init__(self, config_path: Path = CONFIG_PATH):
        self.config = self._load_config(config_path)
        self.personality = PersonalityLoader(PROJECT_ROOT)
        self.sessions = SessionManager(
            str(PROJECT_ROOT / "data" / "sessions.db")
        )

        # LLM
        self.llm = self._setup_llm()

        # Allowed channels
        channels_str = self.config.get("discord", "allowed_channels", fallback="hellgpt,bot-testing")
        self.allowed_channels = {c.strip().lower() for c in channels_str.split(",")}

        # Guild restriction
        self.guild_id = self.config.getint("discord", "guild_id", fallback=0) or None

        # Discord client
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        self.bot = discord.Client(intents=intents)
        self.tree = app_commands.CommandTree(self.bot)

        self._register_commands()
        self._register_events()

        logging.info("HellGPTBot initialized")

    def _load_config(self, config_path: Path) -> configparser.ConfigParser:
        cfg = configparser.ConfigParser()
        if not config_path.exists():
            logging.info(f"Config {config_path} missing; generating defaults.")
            self._autogen_config(config_path)
        cfg.read(config_path)
        return cfg

    def _autogen_config(self, config_path: Path):
        config_path.parent.mkdir(parents=True, exist_ok=True)
        default = """[discord]
# Token from environment: HELLGPT_DISCORD_TOKEN
allowed_channels = hellgpt,bot-testing
guild_id = 1403107950012141638

[llm]
provider = ollama_cloud
model = nemotron-3-nano:30b-cloud
host = https://ollama.com
api_key_env = OLLAMA_API_KEY
timeout = 180
temperature = 0.6

[logging]
log_file = logs/hellgpt.log
log_level = INFO
"""
        config_path.write_text(default, encoding="utf-8")

    def _setup_llm(self) -> Optional[LLMClient]:
        try:
            model = self.config.get("llm", "model", fallback="nemotron-3-nano:30b-cloud")
            host = self.config.get("llm", "host", fallback="https://ollama.com")
            api_key_env = self.config.get("llm", "api_key_env", fallback="OLLAMA_API_KEY")
            api_key = os.environ.get(api_key_env)
            if not api_key:
                logging.error(f"Environment variable {api_key_env} not set")
                return None
            timeout = self.config.getint("llm", "timeout", fallback=180)
            return LLMClient(model=model, host=host, api_key=api_key, timeout=timeout)
        except Exception as e:
            logging.error(f"Failed to initialize LLM: {e}", exc_info=True)
            return None

    # -------------------------------------------------------------------
    # Slash commands
    # -------------------------------------------------------------------

    def _register_commands(self):
        hell_group = app_commands.Group(
            name="hell",
            description="HellGPT — Profanity, delivered straight from Hell",
        )

        tradition_choices = [
            app_commands.Choice(name=t.capitalize(), value=t) for t in TRADITIONS
        ] + [app_commands.Choice(name="Surprise Me", value="surprise")]

        @hell_group.command(name="tradition", description="Select a swearing tradition")
        @app_commands.describe(style="The cultural tradition for your profanity")
        @app_commands.choices(style=tradition_choices)
        async def tradition_cmd(interaction: discord.Interaction, style: app_commands.Choice[str]):
            session = self.sessions.get(interaction.user.id)
            chosen = style.value

            if chosen == "surprise":
                # Will be routed per-message; set flag
                session.tradition = "surprise"
                self.sessions.save(session)
                await interaction.response.send_message(
                    "**Surprise Me** activated. I'll pick the tradition that fits each message.\n"
                    "Your shipment from Hell is being prepared.",
                    ephemeral=True,
                )
                return

            session.tradition = chosen
            session.heat_level = 1  # Reset heat on tradition change
            session.history = []    # Clear history so old style doesn't bleed through
            self.sessions.save(session)

            await interaction.response.send_message(
                f"Tradition set to **{chosen.capitalize()}**. Heat level reset to 1.\n"
                f"Your shipment from Hell is being processed.",
                ephemeral=True,
            )

        @hell_group.command(name="reset", description="Reset your session (tradition, heat, history)")
        async def reset_cmd(interaction: discord.Interaction):
            self.sessions.reset(interaction.user.id)
            await interaction.response.send_message(
                "Session reset. Back to Norwegian, heat level 1. As if nothing happened.\n"
                "Though in Hell, something always happened.",
                ephemeral=True,
            )

        @hell_group.command(name="who", description="Show your active tradition and heat level")
        async def who_cmd(interaction: discord.Interaction):
            session = self.sessions.get(interaction.user.id)
            targets_str = ", ".join(session.targets) if session.targets else "None"

            embed = discord.Embed(
                title="Your HellGPT Session",
                color=self._heat_color(session.heat_level),
            )
            embed.add_field(name="Tradition", value=session.tradition.capitalize(), inline=True)
            embed.add_field(name="Heat Level", value=f"{'🔥' * session.heat_level} ({session.heat_level}/5)", inline=True)
            embed.add_field(name="Named Targets", value=targets_str, inline=False)
            embed.set_footer(text="Gods Expedition, Hell, Norway")

            await interaction.response.send_message(embed=embed, ephemeral=True)

        self.tree.add_command(hell_group)

    # -------------------------------------------------------------------
    # Event handlers
    # -------------------------------------------------------------------

    def _register_events(self):
        @self.bot.event
        async def on_ready():
            logging.info(f"HellGPT connected as {self.bot.user}")
            logging.info(f"Guilds: {[g.name for g in self.bot.guilds]}")

            # Sync slash commands
            if self.guild_id:
                guild_obj = discord.Object(id=self.guild_id)
                self.tree.copy_global_to(guild=guild_obj)
                await self.tree.sync(guild=guild_obj)
                logging.info(f"Slash commands synced to guild {self.guild_id}")
            else:
                await self.tree.sync()
                logging.info("Slash commands synced globally")

        @self.bot.event
        async def on_message(message: discord.Message):
            # Ignore self
            if message.author == self.bot.user:
                return
            # Ignore bots
            if message.author.bot:
                return

            channel_name = getattr(message.channel, "name", "(DM)")
            logging.debug(
                f"Message from {message.author} in #{channel_name}: {message.content[:80]!r}"
            )

            # Respond if mentioned OR in an allowed channel
            mentioned = self.bot.user in message.mentions
            in_thread = isinstance(message.channel, discord.Thread)
            in_allowed_channel = False

            if in_thread:
                parent = message.channel.parent
                in_allowed_channel = (
                    hasattr(parent, "name")
                    and parent.name.lower() in self.allowed_channels
                )
            else:
                in_allowed_channel = (
                    hasattr(message.channel, "name")
                    and message.channel.name.lower() in self.allowed_channels
                )

            if not mentioned and not in_allowed_channel:
                logging.debug(
                    f"Skipping: mentioned={mentioned}, channel={channel_name}, "
                    f"allowed={self.allowed_channels}"
                )
                return

            logging.info(f"Handling message from {message.author} in #{channel_name}")
            await self._handle_chat(message)

    # -------------------------------------------------------------------
    # Chat handler
    # -------------------------------------------------------------------

    async def _handle_chat(self, message: discord.Message):
        if self.llm is None:
            await message.reply(self._get_downtime_message())
            return

        session = self.sessions.get(message.author.id)
        user_text = message.content

        # Strip the bot mention from the message
        if self.bot.user:
            user_text = user_text.replace(f"<@{self.bot.user.id}>", "").strip()
            user_text = user_text.replace(f"<@!{self.bot.user.id}>", "").strip()

        if not user_text:
            await message.reply("You mentioned me but said nothing. Even in Hell, we need words to work with.")
            return

        # Determine reply target: create thread in allowed channels, inline otherwise
        in_thread = isinstance(message.channel, discord.Thread)
        in_allowed_channel = False
        if in_thread:
            parent = message.channel.parent
            in_allowed_channel = (
                hasattr(parent, "name")
                and parent.name.lower() in self.allowed_channels
            )
        else:
            in_allowed_channel = (
                hasattr(message.channel, "name")
                and message.channel.name.lower() in self.allowed_channels
            )

        # In allowed channels: create a new thread for the conversation
        # In existing threads or @mentions: reply inline
        reply_target = message
        if in_allowed_channel and not in_thread:
            try:
                thread_name = message.author.display_name
                thread = await message.create_thread(name=thread_name)
                reply_target = thread
            except discord.HTTPException as e:
                logging.warning(f"Could not create thread: {e}")

        # Handle surprise routing
        surprise_notice = ""
        active_tradition = session.tradition
        if session.tradition == "surprise":
            active_tradition, reason = route_surprise(user_text)
            surprise_notice = f"*[{active_tradition.capitalize()} tradition selected — {reason}]*\n\n"
            # Temporarily set tradition for prompt building
            original_tradition = session.tradition
            session.tradition = active_tradition

        # Build system prompt
        system_prompt = self.personality.build_system_prompt(session)

        # Restore surprise flag
        if surprise_notice:
            session.tradition = original_tradition

        # Build conversation history for context
        chat_messages = []
        for turn in session.history:
            chat_messages.append({"role": "user", "content": turn.get("user", "")})
            chat_messages.append({"role": "assistant", "content": turn.get("assistant", "")})
        chat_messages.append({"role": "user", "content": user_text})

        try:
            typing_target = reply_target if reply_target != message else message.channel
            async with typing_target.typing():
                logging.debug(f"Calling LLM with {len(chat_messages)} messages, "
                              f"system prompt {len(system_prompt)} chars")
                loop = asyncio.get_event_loop()
                response_text = await loop.run_in_executor(
                    None,
                    lambda: self.llm.chat(system_prompt, chat_messages),
                )
                logging.debug(f"LLM returned {len(response_text) if response_text else 0} chars")

            if not response_text:
                await self._send_reply(reply_target, message,
                    "The freight office produced nothing. Try again — even Hell has off days.")
                return

            # Build embed response
            full_response = f"{surprise_notice}{response_text}" if surprise_notice else response_text

            # Split if too long for Discord
            chunks = self._split_message(full_response)

            for i, chunk in enumerate(chunks):
                embed = discord.Embed(
                    description=chunk,
                    color=self._heat_color(session.heat_level),
                )
                await self._send_reply(reply_target, message, embed=embed)

            # Update session
            session.history.append({"user": user_text, "assistant": response_text[:500]})
            session.history = session.history[-6:]

            # Naive heat tracking based on message indicators
            session.heat_level = self._estimate_heat(user_text, session.heat_level)

            # Extract potential named targets (simple heuristic: capitalized words
            # that appear as direct objects of frustration)
            self._extract_targets(user_text, session)

            self.sessions.save(session)

        except Exception as e:
            logging.error(f"Chat error for user {message.author.id}: {e}", exc_info=True)
            error_text = str(e).lower()
            if any(k in error_text for k in ["timeout", "connection", "refused", "unreachable"]):
                await self._send_reply(reply_target, message, self._get_downtime_message())
            else:
                await self._send_reply(reply_target, message,
                    "*stares at the broken freight scale*\n\n"
                    "Something went wrong in the back office. The machinery sputters sometimes. "
                    "Try again shortly.\n\n— HellGPT"
                )

    # -------------------------------------------------------------------
    # Utilities
    # -------------------------------------------------------------------

    async def _send_reply(self, target, message: discord.Message,
                          content: str = None, *, embed: discord.Embed = None):
        """Send to thread if available, fall back to original message reply."""
        try:
            if isinstance(target, discord.Thread):
                if embed:
                    await target.send(embed=embed)
                else:
                    await target.send(content)
                return
        except discord.NotFound:
            logging.warning("Thread gone, falling back to message reply")

        try:
            if embed:
                await message.reply(embed=embed, mention_author=False)
            else:
                await message.reply(content)
        except discord.NotFound:
            logging.warning("Original message/channel gone, reply dropped")

    def _estimate_heat(self, user_text: str, current_heat: int) -> int:
        """Rough heuristic for heat level adjustment."""
        lower = user_text.lower()
        escalation_signals = [
            "fuck", "shit", "damn", "hell", "broken", "again",
            "hours", "waste", "hate", "kill", "die", "worst",
            "impossible", "stupid", "three hours", "all day",
            "!!", "!!!", "HELP", "WTF", "FFS",
        ]
        caps_ratio = sum(1 for c in user_text if c.isupper()) / max(len(user_text), 1)

        score = sum(1 for signal in escalation_signals if signal in lower)
        if caps_ratio > 0.5 and len(user_text) > 10:
            score += 2

        if score >= 3:
            return min(current_heat + 1, 5)
        elif score >= 1:
            return min(current_heat + 1, 4) if current_heat < 3 else current_heat
        else:
            # Cool down slowly
            return max(current_heat - 1, 1) if current_heat > 1 else 1

    def _extract_targets(self, user_text: str, session: UserSession):
        """Simple heuristic to detect named targets from user frustration."""
        # Look for patterns like "X is broken", "X keeps", "damn X", "stupid X"
        patterns = [
            r"(\b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)\s+(?:is|are|keeps?|won't|can't|doesn't)",
            r"(?:damn|stupid|fucking|bloody|cursed|jævla)\s+(\b[A-Z][a-zA-Z]+)",
        ]
        for pattern in patterns:
            matches = re.findall(pattern, user_text)
            for match in matches:
                name = match.strip()
                # Skip common non-target words
                if name.lower() in {"i", "it", "the", "my", "this", "that", "he", "she", "they", "we", "you"}:
                    continue
                if name and name not in session.targets:
                    session.targets.append(name)

    def _heat_color(self, heat: int) -> int:
        """Map heat level to embed color."""
        colors = {
            1: 0x4A90D9,   # Cool blue
            2: 0xF5A623,   # Warm amber
            3: 0xE8601C,   # Hot orange
            4: 0xD0021B,   # Red
            5: 0x8B0000,   # Dark red
        }
        return colors.get(heat, 0x4A90D9)

    def _split_message(self, text: str, limit: int = 4000) -> list[str]:
        """Split text into chunks that fit in Discord embed descriptions."""
        if len(text) <= limit:
            return [text]
        chunks = []
        while text:
            if len(text) <= limit:
                chunks.append(text)
                break
            # Find a natural break point
            split_at = text.rfind("\n\n", 0, limit)
            if split_at == -1:
                split_at = text.rfind("\n", 0, limit)
            if split_at == -1:
                split_at = text.rfind(" ", 0, limit)
            if split_at == -1:
                split_at = limit
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip()
        return chunks

    def _get_downtime_message(self) -> str:
        """Load a downtime message from instructions."""
        path = PROJECT_ROOT / "instructions" / "03-downtime.md"
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8")
                blocks = content.split("---")
                if blocks:
                    return blocks[0].strip()
            except Exception:
                pass
        return (
            "*stares out the window at the frozen platform*\n\n"
            "The freight office is temporarily closed. Check back shortly.\n\n"
            "— HellGPT, Gods Expedition"
        )

    def run(self):
        token = os.getenv("HELLGPT_DISCORD_TOKEN")
        if not token:
            raise ValueError(
                "HELLGPT_DISCORD_TOKEN environment variable not set. "
                "Create a Discord application at https://discord.com/developers and set the token."
            )
        logging.info("Starting HellGPT Discord bot...")
        self.bot.run(token, log_handler=None)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    os.makedirs(PROJECT_ROOT / "logs", exist_ok=True)

    # Read log level from config if it exists
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH)
    level_name = cfg.get("logging", "log_level", fallback="INFO").upper()
    log_level = getattr(logging, level_name, logging.INFO)
    log_file = PROJECT_ROOT / "logs" / "hellgpt.log"

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(),
        ],
    )

    bot = HellGPTBot()
    bot.run()


if __name__ == "__main__":
    main()
