# macOS setup

## 1. Check the Mac tools

Open **Terminal**. Run these commands to see which tools you already have:

```sh
python3 --version
node --version
npm --version
gpg --version
curl --version
```

You need **Python 3.10+**, **Node.js 22+** with npm, and **GnuPG**. Install only the missing tools. The launcher also checks for `curl`, which comes with macOS.

- **Individual installers:** Get the macOS installer from [Python.org](https://www.python.org/downloads/macos/) and the LTS macOS installer from [Node.js](https://nodejs.org/en/download). [GPG Suite](https://gpgtools.org/) provides the `gpg` command through MacGPG. Open a new Terminal window after installing tools and repeat the version checks.
- **Homebrew:** If you already use [Homebrew](https://brew.sh/), you can run `brew install python node gnupg` to install those tools.

## 2. Connect to Tor

- **Already using Brave?** Open **File → New Private Window with Tor**, wait for Tor to connect, and leave that window open. The bridge detects Brave's local Tor port and checks again if it changes. You can use this connection without installing standalone Tor.
- **Tor Browser:** Install [Tor Browser for macOS](https://www.torproject.org/download/), click **Connect**, and leave it open. The bridge checks port **9150** automatically.
- **Standalone Tor with Homebrew:** Run `brew install tor` and then `brew services start tor`. The bridge checks the default port, **9050**, automatically.

At the **Tor SOCKS port** prompt, press **Enter** for automatic detection. If you use a custom standalone Tor port, enter it there. After pairing, you can change it by running `bash start.sh settings` in the project folder and selecting **Tor SOCKS port**.

## 3. Download and start the bridge

1. On the [GitHub project page](https://github.com/wildbillwallace/robosats-telegram), choose **Code → Download ZIP**. Double-click the ZIP to extract it.
2. In the extracted folder, double-click **Start RoboSats Bridge.command**. It may appear as **Start RoboSats Bridge** if Finder hides extensions.
3. Follow the first-run prompts in the Terminal window that opens. On later runs, double-click the same launcher and wait for **Bridge ready**.

The launcher creates `.venv` in the project folder and downloads the Python and chat libraries on the first run. Later runs reuse them and reinstall when the dependency files change.

If Finder can’t open the launcher, open Terminal, type `bash` followed by a space, drag **start.sh** from the extracted folder into Terminal, and press Enter. This starts the same bridge. You can also use this command if you cloned the repository with Git.

### Use an existing Python environment

Activate it the way you normally do, then run the following in the project folder:

```sh
python --version
python -m pip install -r requirements.txt
npm ci --ignore-scripts
python robosats_monitor.py
```

Confirm the first line shows Python 3.10 or newer. The pip command installs Python dependencies into your active environment. The npm command installs the chat libraries in the project folder. On later runs, activate that environment and run only `python robosats_monitor.py` from the project folder. If that environment uses `python3`, use `python3` in these commands.

## 4. Pair your bot

Use a bot you own. Follow [the BotFather and pairing steps](README.md#2-create-and-connect-your-telegram-bot), then [try it without a trade](README.md#try-it-without-a-trade). Wait for **Bridge ready** before leaving the computer.

## 5. Leave the bridge running for your phone

Run the bridge and wait for **Bridge ready** before you leave. Keep the Terminal window open, the Mac online, and your Tor connection running. You can minimize Terminal, lock the Mac, or let the screen turn off. The bridge uses `caffeinate` to prevent idle sleep while browsing or monitoring.

Leave the lid open if closing it sleeps the Mac. If the Mac goes to sleep or loses its connection, wake or reconnect it. Use **Menu → Show bridge controls** in your bot chat to check the order before retrying an action. Press **Ctrl+C** to stop the bridge and release the sleep request. To resume, start the bridge again and tap [Resume an order](README.md#resume-a-buy-order-from-desktop) if you already took an offer.

If a tool is missing from Terminal after installation, open a fresh Terminal window and repeat the version checks above. For Tor, pairing, or Telegram problems, see [Restart and troubleshooting](README.md#restart-and-troubleshooting).

