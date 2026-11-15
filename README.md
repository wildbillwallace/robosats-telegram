# RoboSats Telegram Bridge

Take a RoboSats buy offer from your phone through your own Telegram bot. Browse and take offers, get the Lightning bond invoice, submit a payout invoice, chat with the seller, mark your payment as sent, and get a final status alert.

**You pay the bond in your Lightning wallet and pay the seller in your usual payment app.** Telegram handles the RoboSats order controls. The bridge runs on your Mac and connects to RoboSats over Tor.

This independent project supports **mainnet BTC buy orders taken from the public book** on **Temple of Sats** and **The Big Lake**. You can also resume a supported order you started in RoboSats on desktop.

## 1. Install on macOS

Install [Homebrew](https://brew.sh/) if you don't already have it. In Terminal, install the required tools:

```sh
brew install python node gnupg
```

### Connect to Tor

- **Already using Brave?** Open **File → New Private Window with Tor**, wait for Tor to connect, and leave that window open. The bridge detects Brave's local Tor port and checks again if it changes. You can use this connection without installing standalone Tor.
- **Prefer Tor running in the background?** Run `brew install tor` and then `brew services start tor`. The bridge checks the default port, **9050**, automatically.
- **Already using another local Tor setup?** The bridge also checks **9150**. For a custom local SOCKS port, enter it at setup or change it later under **Settings**.

### Download and start the bridge

```sh
git clone https://github.com/wildbillwallace/robosats-telegram.git
cd robosats-telegram
bash start.sh
```

The launcher creates an isolated Python environment and installs the Python and chat libraries on the first run. It then opens the setup prompts. You can use the same command every time.

For mobile access, leave the Mac connected, its lid open, and the script running. If you're using Brave for Tor, keep its Tor window connected too. The script uses macOS `caffeinate` while monitoring or browsing.

## 2. Create and connect your Telegram bot

1. In Telegram, open [@BotFather](https://t.me/BotFather), send `/newbot`, and choose a display name and username. Copy the full token BotFather returns. It includes the numeric bot ID before the colon.
2. When `bash start.sh` opens setup, paste the token into the hidden terminal prompt. Enter your numeric private **chat ID** if you know it, or press Enter so the script can discover it. At the **Tor SOCKS port** prompt, press Enter to let the bridge detect your connection, including Brave.
3. Follow the link shown in the terminal, tap **Start** in your private chat with your new bot, and send the one-time code shown in the terminal. Use the Telegram account you want to control the bot. The script verifies the bot ID and chat ID and sends a setup test message.
4. At the **Garage Key** prompt, choose whether to save it locally. It is the `robo1…` key from your RoboSats Garage. Paste it into the hidden terminal prompt when asked. You can save it later from **Settings** or enter it for a session.

Telegram has separate [bot creation instructions](https://core.telegram.org/bots/tutorial#obtain-your-bot-token). Use a dedicated bot for this bridge and run one listener at a time. The token, paired chat ID, and saved robot credentials are stored with owner-only permissions outside the checkout, under `~/Library/Application Support/RoboSatsTelegram/` on macOS. Saving the Garage Key stores it in plaintext in that local settings file. Enter credentials only in the local terminal.

## 3. Choose filters and use the bot

Run `bash start.sh` in the project folder. The terminal menu offers **Browse offers on Telegram**, **Monitor an existing order**, **Settings**, and **Send Telegram test**.

- **Change filters.** In **Settings → Offer filters**, enter a currency code such as EUR, GBP, or USD. Type `?` to list supported codes. Enter a payment method such as SEPA or USDT, or leave the method blank to see any method. The initial filter is USD with any payment method. Each listing shows the actual methods from the offer.
- **Take an offer on your phone.** First open your robot at the intended coordinator in RoboSats. In **Settings → Select robot for phone browsing**, select that coordinator and the robot's Garage slot, starting at 0, and repeat for any other coordinator you want to use. Choose **Browse offers on Telegram**, select and review an offer in Telegram, then explicitly confirm taking it. Pay the displayed bond invoice in your Lightning wallet, then tap **Continue order**.
- **Continue an order you started on desktop.** Choose **Monitor an existing order**, enter the order number, and select its coordinator. The script checks the saved robot and can look for the right Garage slot when needed. You can also use **Resume desktop order** from Telegram browsing if the correct robot is already selected.
- **Handle a payout and trade chat.** Enable two-way controls when the script asks. **Trade status** shows the current order. **Lightning payout** lets you choose a routing budget in sats or ppm. Generate the exact invoice shown in your own wallet, paste it into the bot chat, and confirm. When the trade chat opens, type normally to reply to the other trader. After you send the agreed payment in your payment app, use **Confirm Sent** and complete the follow-up confirmation. The bridge supports API chat and Nostr chat when the order exposes the relevant keys. Telegram receives readable chat messages.

Keep RoboSats available for the first live trade so you can cross-check the order. If Telegram is delayed or a trade action has an uncertain result, check the current state in RoboSats before retrying. Choose **Preview trade keyboard** from the Telegram browsing menu to try the controls without an order. **Send Telegram test** checks delivery without accessing an order.

## Restart and troubleshooting

Open Terminal in the same folder again and run:

```sh
bash start.sh
```

Press **Ctrl+C** to stop. If Tor is unavailable, check that your Brave Tor window is connected or that your standalone Tor service is running. Use **Settings → Tor SOCKS port** if your local setup uses a custom port. If mobile actions or Nostr chat cannot start, check that `gpg --version` and `node --version` work. Run `bash start.sh` again after installing any missing tools.

For a read-only authenticated check, use `bash start.sh check --coordinator temple --order ORDER_NUMBER` after selecting a robot for that coordinator. Use `lake` for The Big Lake.

## Local tests

```sh
.venv/bin/python -m unittest discover
npm test
```

These tests use mock services or a local WebSocket. They never take orders, pay invoices, or send live Telegram messages. The currency codes and coordinator addresses are based on the [RoboSats source](https://github.com/RoboSats/robosats). See the [RoboSats API documentation](https://learn.robosats.org/docs/api/) for the protocol.
