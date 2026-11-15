# macOS setup

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
- **Tor Browser:** Install [Tor Browser for macOS](https://www.torproject.org/download/), click **Connect**, and leave it open. The bridge checks port **9150** automatically.
- **Standalone Tor with Homebrew:** Run `brew install tor` and then `brew services start tor`. The bridge checks the default port, **9050**, automatically.

At the **Tor SOCKS port** prompt, press **Enter** for automatic detection. If you use a custom standalone Tor port, enter it there or change it later in **Settings**.

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

For mobile access, leave the Mac awake and connected, with the bridge running. If you use Brave or Tor Browser for Tor, leave that window connected. The bridge uses macOS `caffeinate` when it is available.

Continue with [Create and connect your Telegram bot](README.md#2-create-and-connect-your-telegram-bot).

