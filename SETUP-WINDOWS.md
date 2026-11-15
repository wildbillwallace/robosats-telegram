# Windows setup

Use **Windows 10 or 11**, **PowerShell**, and **Tor Browser**. This guide runs the bridge directly on Windows.

## 1. Install the tools

Install only what you are missing:

- [Git for Windows](https://git-scm.com/install/windows) to download the repository.
- [Python for Windows](https://www.python.org/downloads/windows/) (3.10 or newer). If using the traditional installer, select **Add Python to PATH** and keep the Python launcher enabled.
- [Node.js LTS for Windows](https://nodejs.org/en/download) (22 or newer). The installer includes npm.
- [Gpg4win](https://www.gpg4win.org/download.html) for GnuPG. Use the installer defaults.
- [Tor Browser for Windows](https://www.torproject.org/download/) for the connection to RoboSats.

If the tools are already installed, open a **new PowerShell window** and check:

```powershell
git --version
py -3 --version
node --version
npm.cmd --version
gpg --version
```

If you installed Python without the `py` command, check `python --version` instead. If Gpg4win is installed and PowerShell cannot find `gpg`, the bridge also checks the standard Gpg4win install folders.

## 2. Connect to Tor

Open **Tor Browser**, click **Connect**, and leave it open. The bridge checks the usual local Tor ports (**9050** and **9150**). Press **Enter** when setup prompts for the Tor SOCKS port. A custom SOCKS port can be entered there or changed later in **Settings**.

## 3. Download and start the bridge

In PowerShell, run:

```powershell
git clone https://github.com/wildbillwallace/robosats-telegram.git
cd robosats-telegram
.\start-windows.cmd
```

The launcher prepares the Python environment and chat libraries on the first run, then opens the setup prompts. Run `.\start-windows.cmd` from the same folder on later runs.

### Use an existing Python environment

Activate the environment you want to use. In the project folder, run:

```powershell
python -m pip install -r requirements.txt
npm.cmd ci --ignore-scripts
python robosats_monitor.py
```

On later runs, activate the environment and run only `python robosats_monitor.py`.

## 4. Pair your bot

Continue with [Create and connect your Telegram bot](README.md#2-create-and-connect-your-telegram-bot). To use it from your phone, leave Windows awake and online, Tor Browser connected, and the bridge running. Press **Ctrl+C** in PowerShell when you want to stop it.
