# Linux Microdia Fix

A simple fix for Microdia 2.4G USB dongles, such as those found with Ajazz AK820 Pro keyboards, stalling at random intervals on Linux.

## Installing

`Python3` is required for running this script. Most Linux distros already come with it preinstalled.

Clone the repo into the directory of your choosing and navigate to it with:

```
git clone https://github.com/goodguyartem/microdia-fix.git
cd microdia-fix.git
```

If you just want to test the fix out before installing, you can run the script with:

```
sudo python3 microdia-fix-daemon.py
```

The script will automatically detect device 0c45:fdfd (vendor:device) and will re-scan for it at regular intervals if it is lost (such as when it is unplugged). To specify a different vendor and device ID, use:

```
sudo python3 microdia-fix-daemon.py -v VENDOR -d DEVICE
```

For a full list of options, run:

```
python3 microdia-fix-daemon.py --help
```

To install it as a permanent fix that runs as a systemd service, an install script is provided:

```
# Grant execute permission:
chmod +x install

# Run installer:
sudo ./install
```

This will install and automatically start the service. It will also start with every reboot. To uninstall, run:

```
chmod +x uninstall
sudo ./uninstall
```
