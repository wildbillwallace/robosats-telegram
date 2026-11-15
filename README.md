# RoboSats Telegram Bridge

Browse bitcoin buy offers, get order updates, and use RoboSats trade chat from your own private Telegram bot. The bridge runs on your computer and connects to RoboSats over Tor. This is an independent project for **mainnet BTC buy orders you take from the public book**. The bundled coordinators are **Temple of Sats** and **The Big Lake**.

## 1. Install on macOS

Install [Homebrew](https://brew.sh/) if needed. Open Terminal and run the following.

```sh
brew install python node tor gnupg
brew services start tor
git clone https://github.com/wildbillwallace/robosats-telegram.git
cd robosats-telegram
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
npm ci --ignore-scripts
```

Tor normally listens on port **9050** with this setup. You can also use an existing local Tor SOCKS listener and enter its port during setup. For mobile access, leave the computer connected, the lid open, and the script running. The script uses macOS `caffeinate` while monitoring or browsing.

## 2. Create and connect your Telegram bot

1. In Telegram, open [@BotFather](https://t.me/BotFather), send `/newbot`, and choose a display name and username. Copy the full token BotFather returns. It includes the numeric bot ID before the colon.
2. In the project folder, run `python robosats_monitor.py`. Paste the token into the hidden terminal prompt. Enter your numeric private **chat ID** if you know it, or press Enter so the script can discover it.
3. Follow the link shown in the terminal, tap **Start** in your private chat with your new bot, and send the one-time code shown in the terminal. Use the Telegram account you want to control the bot. The script verifies the bot ID and chat ID and sends a setup test message.
4. At the **Garage Key** prompt, choose whether to save it locally. It is the `robo1…` key from your RoboSats Garage. Paste it into the hidden terminal prompt when asked. You can save it later from **Settings** or enter it for a session.

Telegram has separate [bot creation instructions](https://core.telegram.org/bots/tutorial#obtain-your-bot-token). Use a dedicated bot for this bridge and run one listener at a time. The token, paired chat ID, and saved robot credentials are stored with owner-only permissions outside the checkout, under `~/Library/Application Support/RoboSatsTelegram/` on macOS. Saving the Garage Key stores it in plaintext in that local settings file. Enter credentials only in the local terminal.

## 3. Choose filters and use the bot

Run `python robosats_monitor.py` from the activated virtual environment. The terminal menu offers **Browse offers on Telegram**, **Monitor an existing order**, **Settings**, and **Send Telegram test**.

- **Change filters.** In **Settings → Offer filters**, enter a currency code such as EUR, GBP, or USD. Type `?` to list supported codes. Enter a payment method such as SEPA or USDT, or leave the method blank to see any method. The initial filter is USD with any payment method. Each listing shows the actual methods from the offer.
- **Take an offer on your phone.** First open your robot at the intended coordinator in RoboSats. In **Settings → Select robot for phone browsing**, select that coordinator and the robot's Garage slot, starting at 0, and repeat for any other coordinator you want to use. Choose **Browse offers on Telegram**, select and review an offer in Telegram, then explicitly confirm taking it. Pay the displayed bond invoice in your Lightning wallet, then tap **Continue order**.
- **Continue an order you started on desktop.** Choose **Monitor an existing order**, enter the order number, and select its coordinator. The script checks the saved robot and can look for the right Garage slot when needed. You can also use **Resume desktop order** from Telegram browsing if the correct robot is already selected.
- **Handle a payout and trade chat.** Enable two-way controls when the script asks. **Trade status** shows the current order. **Lightning payout** lets you choose a routing budget in sats or ppm. Generate the exact invoice shown in your own wallet, paste it into the bot chat, and confirm. When the trade chat opens, type normally to reply to the other trader. After you send the agreed payment in your payment app, use **Confirm Sent** and complete the follow-up confirmation. The bridge supports API chat and Nostr chat when the order exposes the relevant keys. Telegram receives readable chat messages.

Keep RoboSats available for the first live trade so you can cross-check the order. If Telegram is delayed or a trade action has an uncertain result, check the current state in RoboSats before retrying. Choose **Preview trade keyboard** from the Telegram browsing menu to try the controls without an order. **Send Telegram test** checks delivery without accessing an order.

## Restart and troubleshooting

Open Terminal in the same folder again and run:

```sh
source .venv/bin/activate
python robosats_monitor.py
```

Press **Ctrl+C** to stop. If Tor is unavailable, check that it is running and confirm the SOCKS port under **Settings**. If mobile actions or Nostr chat cannot start, check that `gpg --version` and `node --version` work and rerun `npm ci --ignore-scripts` in this folder.

For a read-only authenticated check, use `python robosats_monitor.py check --coordinator temple --order ORDER_NUMBER` after selecting a robot for that coordinator. Use `lake` for The Big Lake.

## Local tests

```sh
python -m unittest discover
npm test
```

These tests use mock services or a local WebSocket. They never take orders, pay invoices, or send live Telegram messages. The currency codes and coordinator addresses are based on the [RoboSats source](https://github.com/RoboSats/robosats). See the [RoboSats API documentation](https://learn.robosats.org/docs/api/) for the protocol.
