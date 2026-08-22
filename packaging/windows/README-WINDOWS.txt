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
Configuration, group approvals, and Telegram API state live under data\. Never
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
