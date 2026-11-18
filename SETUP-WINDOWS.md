# Windows setup

Use **Windows 10 or 11**. You can start the bridge from File Explorer.

## 1. Install the tools

Install only what you are missing:

- [Python for Windows](https://www.python.org/downloads/windows/) (3.10 or newer). If using the traditional installer, select **Add Python to PATH** and keep the Python launcher enabled.
- [Node.js LTS for Windows](https://nodejs.org/en/download) (22 or newer). The installer includes npm.
- [Gpg4win](https://www.gpg4win.org/download.html) for GnuPG. Use the installer defaults.

If the tools are already installed, open a **new PowerShell window** and check:

```powershell
py -3 --version
node --version
npm.cmd --version
gpg --version
```

If you installed Python without the `py` command, check `python --version` instead. If Gpg4win is installed and PowerShell cannot find `gpg`, the bridge also checks the standard Gpg4win install folders.

## 2. Connect to Tor

- **Brave:** Open **Menu → New Private Window with Tor**, wait for Tor to connect, and leave that window open. The bridge finds Brave’s local Tor port automatically and checks again if the port changes.
- **Tor Browser:** Open [Tor Browser for Windows](https://www.torproject.org/download/), click **Connect**, and leave it open. The bridge checks its usual port (**9150**) automatically.
- **Standalone Tor:** Start your local Tor service. The bridge checks the default port (**9050**) automatically.

At the **Tor SOCKS port** prompt, press **Enter** for automatic detection. If you use a custom standalone Tor port, enter it there. After pairing, you can change it by running `.\start-windows.cmd settings` in PowerShell from the project folder and selecting **Tor SOCKS port**.

## 3. Download and start the bridge

1. On the [GitHub project page](https://github.com/wildbillwallace/robosats-telegram), choose **Code → Download ZIP**. Right-click the downloaded ZIP and choose **Extract All**.
2. In the extracted folder, double-click **Start RoboSats Bridge.cmd**. It may appear as **Start RoboSats Bridge** if File Explorer hides extensions.
3. Follow the first-run prompts in the command window that opens. On later runs, double-click the same launcher and wait for **Bridge ready**.

The launcher creates `.venv` in the project folder and downloads the Python and chat libraries on the first run. Later runs reuse them and reinstall when the dependency files change. If you prefer PowerShell or cloned the repository with Git, run `.\start-windows.cmd` from the project folder.

### Use an existing Python environment

Activate the environment you want to use. In the project folder, run these commands and check that Python is 3.10 or newer:

```powershell
python --version
python -m pip install -r requirements.txt
npm.cmd ci --ignore-scripts
python robosats_monitor.py
```

On later runs, activate the environment and run only `python robosats_monitor.py`.

## 4. Pair your bot

Use a bot you own. Follow [the BotFather and pairing steps](README.md#2-create-and-connect-your-telegram-bot), then [try it without a trade](README.md#try-it-without-a-trade). Wait for **Bridge ready** before leaving the computer.

## 5. Leave the bridge running for your phone

Run the bridge and wait for **Bridge ready** before you leave. Keep the command window open, the PC online, and your Tor connection running. You can minimize the window, lock the PC, or let the screen turn off. The bridge asks Windows to prevent idle sleep while browsing or monitoring.

Leave the lid open if closing it sleeps or hibernates the laptop. If the PC goes to sleep or loses its connection, wake or reconnect it. Use **Menu → Show bridge controls** in your bot chat to check the order before retrying an action. Press **Ctrl+C** to stop the bridge and release the sleep request. To resume, start the bridge again and tap [Resume an order](README.md#resume-a-buy-order-from-desktop) if you already took an offer.

If a tool is missing from PowerShell after installation, open a fresh PowerShell window and repeat the version checks above. For Tor, pairing, or Telegram problems, see [Restart and troubleshooting](README.md#restart-and-troubleshooting).
