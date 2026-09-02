W BOT - PORTABLE WINDOWS PACKAGE
================================

REQUIREMENTS
Windows 10 or Windows 11 on a 64-bit PC, plus an internet connection.
Docker, Python, FFmpeg, Visual Studio, and port forwarding are not required.

FIRST SETUP
1. Extract the entire W-Bot folder to a normal local folder. Avoid OneDrive or
   another synchronized folder because the bot writes temporary videos locally.
2. Double-click Setup Bot.cmd.
3. Enter the bot token, Telegram API ID, Telegram API hash, and owner Telegram
   user ID when prompted. The token and API hash are not displayed as you type.
4. Setup creates or refreshes four Desktop shortcuts.

TELEGRAM GROUP SETUP
1. In BotFather, run /setprivacy, select this bot, and choose Disable. This is
   required so Telegram delivers ordinary link messages instead of commands only.
2. In BotFather /setcommands, add approve, revoke, social_off, social_on,
   figures_off, and figures_on as listed in the project README.
3. Add the bot to the desired groups as an ordinary member, never as an admin.
4. The owner sends /approve once in each approved group. Use /revoke to disable it.

PER-GROUP MEDIA SWITCHES
Both categories begin enabled. Only the configured owner can use these commands:
- /social_off and /social_on control TikTok, Facebook, and X.
- /figures_off and /figures_on control AmiAmi and Nin-Nin Game.
Links from a disabled category are silently ignored. The choices persist across
restarts and upgrades. Revoking and later reapproving a group resets both to enabled.

Members use the bot by sending one supported HTTPS link by itself. The bot silently
ignores ordinary conversation, unsupported links, unapproved groups, and messages
containing more than one link. It does not log message text.

DAILY USE
- Start W Bot: starts the bot and local Telegram API in the background.
- Stop W Bot: safely stops both background services.
- W Bot Status: shows whether the bot is running, stopped, partially running,
  or still needs setup.
- W Bot Logs: shows recent diagnostic logs. Closing the log window does not stop
  the bot.

The PC must remain awake, online, and logged in while the bot is needed. Windows
sleep, shutdown, a lost connection, or signing out makes the bot unavailable.
The service listens only on 127.0.0.1, so no router changes or public inbound port
are needed.

FIRST START
The first Start moves the bot from Telegram's cloud Bot API to the local Bot API.
If it fails, read the short error, check the internet connection, and try Start
again. Later starts reuse the completed handover.

FILES, MOVES, AND UPGRADES
Configuration, group approvals, media switches, and Telegram API state live under data\. Never
share data\settings.json. Its secrets are protected for the current Windows user
with DPAPI, so another Windows account or computer cannot decrypt them.

To move the bot on this PC, stop it, move the whole W-Bot folder, then run Create
Desktop Shortcuts.cmd. To move to another computer or Windows user, run setup
again there.

For an upgrade, stop the bot, back up data\, extract the new package separately,
then copy the old data\ folder into the new stopped package. Do not copy logs\ or
temp\. Deleting data\ loses setup and approved-group information.

Temporary downloads are placed under temp\ and removed after each request. The
Telegram Local Bot API keeps persistent working data under data\telegram-api\.
Use Show Bot Logs.cmd for local diagnostics.
