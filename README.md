# RoboSats Telegram Bridge

Take a RoboSats buy offer from your phone through your own Telegram bot. Browse and take offers, get the Lightning bond invoice, submit a payout invoice, chat with the seller, mark your payment as sent, and get a final status alert.

**You pay the bond in your Lightning wallet and pay the seller in your usual payment app.** Telegram handles the RoboSats order controls. The bridge runs on your Mac and connects to RoboSats over Tor.

This independent project supports **mainnet BTC buy orders taken from the public book** on **Temple of Sats** and **The Big Lake**. You can also resume a supported order you started in RoboSats on desktop.

## 1. Install on macOS

### Check the Mac tools

Open **Terminal**. Run these commands to see which tools you already have:

```sh
git --version
python3 --version
node --version
npm --version
gpg --version
```

You need Git, **Python 3.10+**, **Node.js 22+** with npm, and **GnuPG**. Install only the missing tools.

- **Individual installers:** Get the macOS installer from [Python.org](https://www.python.org/downloads/macos/) and the LTS macOS installer from [Node.js](https://nodejs.org/en/download). [GPG Suite](https://gpgtools.org/) provides the `gpg` command through MacGPG. If Git is missing, run `xcode-select --install` and follow the macOS prompt. Open a new Terminal window after installing tools and repeat the version checks.
- **Homebrew:** If you already use [Homebrew](https://brew.sh/), you can run `brew install python node gnupg` to install those tools.

### Connect to Tor

- **Already using Brave?** Open **File → New Private Window with Tor**, wait for Tor to connect, and leave that window open. The bridge detects Brave's local Tor port and checks again if it changes. You can use this connection without installing standalone Tor.
- **Use standalone Tor with Homebrew:** Run `brew install tor` and then `brew services start tor`. The bridge checks the default port, **9050**, automatically.
- **Already using another local Tor setup?** The bridge also checks **9150**. For a custom local SOCKS port, enter it at setup or change it later under **Settings**.

### Download and start the bridge

```sh
git clone https://github.com/wildbillwallace/robosats-telegram.git
cd robosats-telegram
```

Choose one way to start:

**Automatic setup** is the simplest option. Run `bash start.sh`. It creates a project-local Python environment, installs the libraries, and starts the bridge. Use that same command on later runs.

**Use an existing Python environment.** Activate it the way you normally do, then run the following in the project folder:

```sh
python --version
python -m pip install -r requirements.txt
npm ci --ignore-scripts
python robosats_monitor.py
```

Confirm the first line shows Python 3.10 or newer. The install command adds the Python dependencies to your active environment. On later runs, activate that environment and run only `python robosats_monitor.py` from the project folder. If that environment uses `python3`, use `python3` in these commands.

For mobile access, leave the Mac connected, its lid open, and the script running. If you're using Brave for Tor, keep its Tor window connected too. The script uses macOS `caffeinate` while monitoring or browsing.

## 2. Create and connect your Telegram bot

1. In Telegram, open [@BotFather](https://t.me/BotFather), send `/newbot`, and choose a display name and username. Copy the full token BotFather returns. It includes the numeric bot ID before the colon.
2. When the bridge opens setup, paste the token into the hidden terminal prompt. Enter your numeric private **chat ID** if you know it, or press Enter so the script can discover it. At the **Tor SOCKS port** prompt, press Enter to let the bridge detect your connection, including Brave.
3. Follow the link shown in the terminal, tap **Start** in your private chat with your new bot, and send the one-time code shown in the terminal. Use the Telegram account you want to control the bot. The script verifies the bot ID and chat ID and sends a setup test message.
4. At the **Garage Key** prompt, use the `robo1…` key you backed up when you created your RoboSats Garage. If you are new to RoboSats, [create your Garage first](https://learn.robosats.org/read/en/) and back up its key. Choose whether to save the key on this Mac. You can also enter it just for the current session.

Telegram has separate [bot creation instructions](https://core.telegram.org/bots/tutorial#obtain-your-bot-token). Use a dedicated bot for this bridge and run one listener at a time. The token, paired chat ID, and saved robot credentials are stored with owner-only permissions outside the checkout, under `~/Library/Application Support/RoboSatsTelegram/` on macOS. Saving the Garage Key stores it in plaintext in that local settings file. Enter credentials only in the local terminal.

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

Open Terminal in the same folder. Run `bash start.sh` for automatic setup, or activate your existing environment and run `python robosats_monitor.py`.

Press **Ctrl+C** to stop. If Tor is unavailable, check that your Brave Tor window is connected or that your standalone Tor service is running. Use **Settings → Tor SOCKS port** if your local setup uses a custom port. If mobile actions or Nostr chat cannot start, check that `gpg --version` and `node --version` work. Restart the bridge after installing any missing tools.

For a read-only authenticated check, add `check --coordinator temple --order ORDER_NUMBER` to your launch command after selecting a robot for that coordinator. Use `lake` for The Big Lake.

## Local tests

```sh
.venv/bin/python -m unittest discover
npm test
```

If using your own active environment, run `python -m unittest discover` instead of the first command. These tests use mock services or a local WebSocket. They never take orders, pay invoices, or send live Telegram messages. The currency codes and coordinator addresses are based on the [RoboSats source](https://github.com/RoboSats/robosats). See the [RoboSats API documentation](https://learn.robosats.org/docs/api/) for the protocol.
