# RoboSats Telegram Bridge

Take a RoboSats buy offer from your phone through your own Telegram bot. Browse and take offers, get the Lightning bond invoice, submit a payout invoice, chat with the seller, mark your payment as sent, and get a final status alert.

**You pay the bond in your Lightning wallet and pay the seller in your usual payment app.** Telegram handles the RoboSats order controls. The bridge runs on your computer and connects to RoboSats over Tor.

This independent project supports **mainnet BTC buy orders taken from the public book** on **Temple of Sats** and **The Big Lake**. You can also resume a supported order you started in RoboSats on desktop.

## 1. Install

Choose the guide for your computer:

| Computer | Setup guide | Start the bridge |
| --- | --- | --- |
| macOS | [macOS setup](SETUP-MACOS.md) | `bash start.sh` |
| Windows 10 or 11 | [Windows setup](SETUP-WINDOWS.md) | `.\start-windows.cmd` in PowerShell |

Keep the computer awake and online, with the bridge running. If the bridge uses a browser for Tor, leave that browser connected while using Telegram.

## 2. Create and connect your Telegram bot

1. In Telegram, open [@BotFather](https://t.me/BotFather), send `/newbot`, and choose a display name and username. Copy the full token BotFather returns. It includes the numeric bot ID before the colon.
2. When the bridge opens setup, paste the token into the hidden terminal prompt. Enter your numeric private **chat ID** if you know it, or press Enter so the script can discover it. At the **Tor SOCKS port** prompt, press Enter to use automatic detection. The Windows guide uses Tor Browser. The macOS guide also covers Brave and standalone Tor.
3. Follow the link shown in the terminal, tap **Start** in your private chat with your new bot, and send the one-time code shown in the terminal. Use the Telegram account you want to control the bot. The script verifies the bot ID and chat ID and sends a setup test message.
4. At the **Garage Key** prompt, use the `robo1…` key you backed up when you created your RoboSats Garage. If you are new to RoboSats, [create your Garage first](https://learn.robosats.org/read/en/) and back up its key. Choose whether to save the key on this computer. You can also enter it just for the current session.

Telegram has separate [bot creation instructions](https://core.telegram.org/bots/tutorial#obtain-your-bot-token). Use a dedicated bot for this bridge and run one listener at a time. Enter credentials only in the local terminal. The bridge stores them outside the project folder. On macOS, the settings file is under `~/Library/Application Support/RoboSatsTelegram/` with owner-only permissions. A Garage Key saved there is stored in plaintext. On Windows, settings are under `%LOCALAPPDATA%\RoboSatsTelegram\` and are encrypted for your Windows user with DPAPI.

## 3. Choose filters and use the bot

### Try it without a trade

Choose **Send Telegram test** in the Terminal menu. You should get a message from your bot. Then choose **Browse offers on Telegram** and tap **Preview trade keyboard** in Telegram to see the controls. Both checks work without taking an offer or paying a bond.

### Take a new buy offer from Telegram

1. Open the robot you want to use in RoboSats at **Temple of Sats** or **The Big Lake**. For a new trade, use the fresh robot RoboSats shows in the Garage. In the bridge's terminal menu, go to **Settings → Select robot for phone browsing**, choose that coordinator, and pick your robot by its RoboSats nickname. Press **Enter** to accept a single match. If the robot you want is missing, make sure you opened it at that coordinator and enter `/more` to search farther.
2. If you want to narrow the book, open **Settings → Offer filters**. Set a currency such as EUR, GBP, or USD, and optionally a payment method such as SEPA or USDT. The default is USD and any payment method.
3. Choose **Browse offers on Telegram** in Terminal and answer **yes** to enable **two-way trade chat and payout**. In Telegram, tap **Browse offers**, review an offer and its coordinator, then confirm if you want to take it. Pay the bond invoice shown by the bot in your Lightning wallet, then tap **Continue order** and **Continue on phone** when the order is ready.

### Resume a buy order from desktop

Choose **Monitor an existing order** in Terminal, enter the RoboSats order number, and select its coordinator. The bridge checks your saved robot and can look for the one with that active order. Enable Telegram chat when prompted if you want the two-way controls. If the right robot is already selected for phone browsing, you can also tap **Resume desktop order** in Telegram.

### Finish the trade

1. When **Trade status** shows that RoboSats needs your payout invoice, tap **Lightning payout**. Set your routing budget if needed, then create a Lightning invoice in your wallet for the **exact sat amount shown by the bot**. Paste it into your private bot chat and confirm.
2. Once trade chat opens, send a normal Telegram message to reply to the seller. The bridge uses RoboSats API or Nostr chat according to the keys available for the order. Your bridged messages are readable in Telegram.
3. When RoboSats is ready for the agreed payment, send it in your usual payment app. Then tap **Confirm Sent** and complete the follow-up confirmation in Telegram. Watch for the final order status and check the receiving wallet for your Lightning payout.

Keep the RoboSats order available for your first live trade. If Telegram is delayed or a trade action has an uncertain result, check the order in RoboSats before retrying.

## Restart and troubleshooting

Open your terminal in the same folder and run the launcher for your platform. If you use your own Python environment, activate it and run `python robosats_monitor.py`.

Press **Ctrl+C** to stop. If Tor is unavailable, check that your Tor Browser or Brave Tor window is connected, or that your standalone Tor service is running. Use **Settings → Tor SOCKS port** if your local setup uses a custom port. If mobile actions or Nostr chat cannot start, check that `gpg --version` and `node --version` work. Restart the bridge after installing any missing tools.

For a read-only authenticated check, add `check --coordinator temple --order ORDER_NUMBER` to your launch command after selecting a robot for that coordinator. Use `lake` for The Big Lake.

## Local tests

Run `npm test` and `python -m unittest discover` in your active environment. With the launcher-created environment, use `.venv/bin/python` on macOS or `.\.venv\Scripts\python.exe` on Windows for the Python command. These tests use mock services or a local WebSocket. They never take orders, pay invoices, or send live Telegram messages. The currency codes and coordinator addresses are based on the [RoboSats source](https://github.com/RoboSats/robosats). See the [RoboSats API documentation](https://learn.robosats.org/docs/api/) for the protocol.
