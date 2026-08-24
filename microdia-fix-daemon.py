#!/usr/bin/env python3

"""
Microdia Fix for Linux
https://www.github.com/goodguyartem/microdia-fix

Microdia 2.4G USB dongles, especially those found with Ajazz AK820 pro keyboards, have been known to randomly stall on Linux
while working fine on Windows. Based on captured USB data from both Windows and Linux, it seems like Windows opens every 
interface a composite HID device exposes, while Linux only submits interrupt IN URBs on interfaces that were already 
opened by something. This results in the RF link silently dropping at random intervals.

This script simply detects, opens, and reads from the device's vendor-specific HID interfaces so interrupt IN URBs keep 
being submitted. Run it in the background from your terminal with sudo or as a systemd service. This should also fix
other keyboards with the same issue; run microdia-fix-daemon.py --help for usage instructions.

Written by goodguyartem <3 <https://www.github.com/goodguyartem>
"""

import os
import time
import select
import argparse
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class Connection:
    slot: str
    path: str
    fd: int

def find_hidraws(vendor, device, interfaces=None, min_endpoints=2):
    """
    Looks for a given vendor:device in /sys/class/hidraw. Because we want the vendor-specific IN+OUT 
    interfaces rather than the single-endpoint keyboard report interfaces, this filters interfaces that
    expose at least min_endpoints.

    Returns a dict of {interface_num (string): "/dev/hidrawN"}
    """
    vendor = vendor.lower()
    device = device.lower()
    hidraws = {}

    try:
        entries = sorted(os.listdir("/sys/class/hidraw"))
    except OSError:
        return hidraws

    for entry in entries:
        device_path = f"/sys/class/hidraw/{entry}/device"
        try:
            real_path = os.path.realpath(device_path)
        except OSError:
            continue
        
        # Path looks like .../1-3/1-3:1.3/0003:0C45:FDFD.0015
        hid_id = os.path.basename(real_path)
        # Split it up into individual components.
        parts = hid_id.split(":")
        if len(parts) < 3:
            continue

        vid = parts[1].lower()
        pid = parts[2].split(".")[0].lower()
        if vid != vendor or pid != device:
            continue

        interface_dir = os.path.dirname(real_path)       # Full interface dir name (such as .../1-3:1.3).
        interface_name = os.path.basename(interface_dir) # Just the base name (such as 1-3:1.3). 
        if ":" not in interface_name or "." not in interface_name:
            continue
        interface_num = interface_name.rsplit(".", 1)[-1]   # Just the number (such as 3).

        if interfaces and interface_num not in interfaces:
            continue

        try:
            endpoint_count = sum(
                name.startswith("ep_")
                for name in os.listdir(interface_dir)
            )
        except OSError:
            continue

        if endpoint_count >= min_endpoints:
            hidraws[interface_num] = f"/dev/{entry}"

    return hidraws

def open_connection(slot, path, connections, missing):
    """Opens a hidraw device and adds it to the active connections."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError as e:
        logger.info("Could not open %s: %s. Will retry.", path, e)
        return False

    connections[slot] = Connection(slot, path, fd)
    missing.discard(slot)

    logger.info("Opened %s (fd=%d)", path, fd)
    return True

def close_connection(slot, connections):
    """Close and remove a connection."""
    con = connections.pop(slot)
    try:
        os.close(con.fd)
    except OSError:
        pass

def main():
    parser = argparse.ArgumentParser(
        description=__doc__, 
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
  
    parser.add_argument(
        "paths", 
        nargs="*", 
        help="Specify an explicit /dev/hidrawN instead of auto-detecting."
    )
    parser.add_argument(
        "-v", 
        "--vendor", 
        default="0c45", 
        help="USB vendor ID in hex (default: 0c45)."
    )
    parser.add_argument(
        "-d", 
        "--device", 
        default="fdfd", 
        help="USB device ID in hex (default: fdfd)."
    )
    parser.add_argument(
        "-i", 
        "--interfaces", 
        default=None,
        help='Comma-separated interface numbers to restrict to (e.g. "3,4"). '
        'Default: auto-detect all multi-endpoint interfaces.'
    )
    parser.add_argument(
        "-m", 
        "--min-endpoints", 
        type=int, 
        default=2, 
        help="Minimum endpoint count for auto-detection (default: 2)."
    )
    parser.add_argument(
        "-r", 
        "--rescan-interval", 
        type=float, 
        default=5.0, 
        help="Seconds between device rescans (default: 5)."
    )
    parser.add_argument(
        "-s", 
        "--silent", 
        action="store_true", 
        help="Output only critical messages to stdout."
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.CRITICAL if args.silent else logging.INFO,
        format="[%(asctime)s] %(message)s",
        datefmt="%I:%M:%S %p"
    )

    interfaces = (
        {interface.strip() for interface in args.interfaces.split(",")}
        if args.interfaces
        else None
    )
    
    auto_detect = not args.paths
    connections = {}
    missing = set()

    def rescan():
        if auto_detect:
            found = find_hidraws(args.vendor, args.device, interfaces, args.min_endpoints)
            for interface_num, path in found.items():
                if interface_num in connections:
                    continue
                open_connection(interface_num, path, connections, missing)
        else:
            for path in list(missing):
                open_connection(path, path, connections, missing)

    if auto_detect:
        logger.info(
            "Auto-detecting %s:%s interfaces with minimum %d endpoints%s...",
            args.vendor,
            args.device,
            args.min_endpoints,
            f", restricted to {sorted(interfaces)}" if interfaces else ""
        )
        rescan()

        if not connections:
            logger.info("No interfaces found, will retry every %gs.", args.rescan_interval)
    else:
        logger.info("Watching explicit paths: %s", ", ".join(args.paths))
        missing.update(args.paths)
        rescan()

    next_rescan = time.monotonic() + args.rescan_interval

    try:
        while True:
            now = time.monotonic()
            timeout = max(0, next_rescan - now)

            fds = [con.fd for con in connections.values()]
            if fds:
                readable, _, _ = select.select(fds, [], [], timeout)
            else:
                time.sleep(timeout)
                readable = []
            
            for fd in readable:
                con = next(
                    con 
                    for con in connections.values() 
                    if con.fd == fd
                )

                try:
                    data = os.read(fd, 64)
                    if data:
                        logger.info("%s: %s", con.path, data.hex())
                except OSError as e:
                    logger.info("Lost %s: %s. Will retry.", con.path, e)
                    close_connection(con.slot, connections)
                    missing.add(con.slot)

            now = time.monotonic() # Update possibly-stale time
            if now >= next_rescan:
                rescan()
                next_rescan = now + args.rescan_interval

    except KeyboardInterrupt:
        logger.info("Stopping...")
    
    finally:
        for slot in list(connections):
            close_connection(slot, connections)

if __name__ == "__main__":
    main()