# RoboSats Telegram Bridge

**Start the bridge on your computer, walk away, and buy bitcoin on RoboSats from your phone.** Use your own Telegram bot to take an offer and manage the trade all the way to your Lightning payout.

Before you leave, run the bridge on your Mac or Windows PC, choose **1. Browse offers on Telegram** in the terminal menu, and answer **yes** to enable trade chat and payout. Once the terminal says browsing is running, leave it open with the computer online and Tor connected. The bridge automatically prevents idle sleep using macOS `caffeinate` or the built-in Windows equivalent. You can lock the computer and let the screen turn off. Leave the lid open if closing it puts your laptop to sleep.

When you’re ready to buy, open your private bot chat on your phone and tap **Browse offers**. From Telegram, you can pick an offer, get the bond invoice, set your Lightning routing budget, submit your payout invoice, chat with the seller, confirm you’ve paid, and track the order through payout. Use your Lightning wallet and usual payment app on the same phone to make the payments. The seller releases escrow through RoboSats.

This independent project supports **mainnet BTC buy orders taken from the public book** on **Temple of Sats** and **The Big Lake**. You can also pick up a supported order you started on desktop. For a dispute or an uncertain payment or order status, open RoboSats to check the trade before retrying.

## 1. Install

Choose the guide for your computer:

| Computer | Setup guide | Start the bridge |
| --- | --- | --- |
| macOS | [macOS setup](SETUP-MACOS.md) | `bash start.sh` |
| Windows 10 or 11 | [Windows setup](SETUP-WINDOWS.md) | `.\start-windows.cmd` in PowerShell |

On both platforms, use Brave’s private Tor window, Tor Browser, or standalone Tor. The bridge finds Brave’s changing local port automatically. While you browse offers or monitor an order from Telegram, the bridge prevents idle sleep and lets the screen turn off. Keep the computer online with Tor connected. Leave the laptop lid open if closing it puts the computer to sleep.

## 2. Create and connect your Telegram bot

1. **Use a bot you already own or create one.** You can reuse a bot if it has no webhook and the bridge will be the only app reading its messages. If your bot is still used by another app or automation, create a separate one. To create a bot, open [@BotFather](https://t.me/BotFather), send `/newbot`, and choose a display name and username. For either path, have the full bot token ready, including the numeric bot ID before the colon.
2. When the bridge opens setup, paste the token into the hidden terminal prompt and press Enter. The paste is invisible by design. At the private **chat ID** prompt, press Enter to discover it automatically, or enter your numeric private chat ID if you already know it. At the **Tor SOCKS port** prompt, press Enter for automatic detection.
3. Open the Telegram link shown in the terminal using the account you want to trade from. In your private chat with the bot, tap **Start** if Telegram shows it, then send the one-time code as a message.
4. When the terminal asks whether to save your **Garage Key**, type `y` to save it or press Enter to skip. If you save it, paste the `robo1…` key you backed up when you created your RoboSats Garage. If you skip, the bridge asks for the key when a feature needs it. If you are new to RoboSats, [create your Garage first](https://learn.robosats.org/read/en/) and back up its key. Setup is complete when the bot sends a test message and the terminal shows the main menu.

Telegram has separate [bot creation instructions](https://core.telegram.org/bots/tutorial#obtain-your-bot-token). Run one copy of the bridge per bot. Enter credentials only in the local terminal. The bridge stores them outside the project folder. On macOS, the settings file is under `~/Library/Application Support/RoboSatsTelegram/` with owner-only permissions. A Garage Key saved there is stored in plaintext. On Windows, settings are under `%LOCALAPPDATA%\RoboSatsTelegram\` and are encrypted for your Windows user with DPAPI.

## 3. Choose filters and use the bot

### Try it without a trade

Choose **4. Send Telegram test** in the bridge's terminal menu and wait for the message on your phone. Then choose **1. Browse offers on Telegram**, press Enter at the two-way chat prompt to skip it for the preview, and tap **Preview trade keyboard** in Telegram. These checks work without picking a robot, taking an offer, or paying a bond. Press **Ctrl+C** to stop the preview and run the start command again to return to the menu.

### Take a new buy offer from Telegram

1. Open the robot you want to use in RoboSats at **Temple of Sats** or **The Big Lake**. For a new trade, use the fresh robot RoboSats shows in the Garage. In the bridge's terminal menu, go to **Settings → Select robot for phone browsing**, choose that coordinator, and pick your robot by its RoboSats nickname. Press **Enter** to accept a single match. If the robot you want is missing, make sure you opened it at that coordinator and enter `/more` to search farther.
2. If you want to narrow the book, open **Settings → Offer filters**. Set a currency such as EUR, GBP, or USD, and optionally a payment method such as SEPA or USDT. The default is USD and any payment method.
3. Choose **Browse offers on Telegram** in Terminal and answer **yes** to enable **two-way trade chat and payout**. In Telegram, tap **Browse offers**, review an offer and its coordinator, then confirm if you want to take it. Pay the bond invoice shown by the bot in your Lightning wallet, then tap **Continue order** and **Continue on phone** when the order is ready.

### Resume a buy order from desktop

Choose **Monitor an existing order** in Terminal, enter the RoboSats order number, and select its coordinator. The bridge checks your saved robot and can look for the one with that active order. Enable Telegram chat when prompted if you want the two-way controls. If the right robot is already selected for phone browsing, you can also tap **Resume desktop order** in Telegram.

### Finish the trade

1. When **Trade status** shows that RoboSats needs your payout invoice, tap **Lightning payout**. To change the routing allowance, tap **Change budget in sats** or **Change budget in ppm**, then use Telegram’s **Reply** gesture on the bot’s prompt and enter a whole number. Once the budget is set, create a Lightning invoice for the **exact sat amount in the latest prompt**. Paste it into your private bot chat and confirm.
2. Once trade chat opens, send a normal Telegram message to reply to the seller. The bridge uses RoboSats API or Nostr chat according to the keys available for the order. Your bridged messages are readable in Telegram.
3. When RoboSats is ready for the agreed payment, send it in your usual payment app. Then tap **Confirm Sent** and complete the follow-up confirmation in Telegram. Watch for the final order status and check the receiving wallet for your Lightning payout.

Keep the RoboSats order available for your first live trade. If Telegram is delayed or a trade action has an uncertain result, check the order in RoboSats before retrying.

## Restart and troubleshooting

Open your terminal in the same folder and run the launcher for your platform. If you use your own Python environment, activate it and run `python robosats_monitor.py`.

- **Tor is unavailable.** Check that your Tor Browser or Brave Tor window says it is connected, or that your standalone Tor service is running. Keep the browser window open. Use **Settings → Tor SOCKS port** if your local setup uses a custom port. For automatic detection, the default saved value is `9050`. The bridge also checks `9150` and looks for Brave’s Tor process.
- **Pairing timed out or the bot is silent.** During setup, rerun the start command and send the new code from the private chat opened by the terminal link. After setup, make sure only one copy of the bridge is using that bot, then try **Send Telegram test**. To accept phone actions, the bridge must be browsing offers or monitoring an order.
- **A trade button is slow or unresponsive.** Send `/trade` in the private bot chat to request the current status. For a payout or payment confirmation, use Telegram’s **Reply** gesture on the latest confirmation message and type `CONFIRM`. If you already sent an invoice or payment and the result is unclear, check the order in RoboSats before retrying.
- **Mobile actions or chat cannot start.** Check `gpg --version` and `node --version`, then restart the bridge after installing any missing tools. On Windows, the bridge also searches the standard Gpg4win folders.

For a read-only authenticated check, add `check --coordinator temple --order ORDER_NUMBER` to your launch command after selecting a robot for that coordinator. Use `lake` for The Big Lake.

## Local tests

Run `npm test` and `python -m unittest discover` in your active environment. With the launcher-created environment, use `.venv/bin/python` on macOS or `.\.venv\Scripts\python.exe` on Windows for the Python command. These tests use mock services or a local WebSocket. They never take orders, pay invoices, or send live Telegram messages. The currency codes and coordinator addresses are based on the [RoboSats source](https://github.com/RoboSats/robosats). See the [RoboSats API documentation](https://learn.robosats.org/docs/api/) for the protocol.
