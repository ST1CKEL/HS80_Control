"""Linux sysfs discovery for the HS80 receiver's control interface."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
from typing import Iterable

from .protocol import (
    CONTROL_INTERFACE,
    RECEIVER_PRODUCT_ID,
    USB_HEADSET_PRODUCT_ID,
    VENDOR_ID,
    WIRED_HEADSET_PRODUCT_ID,
)


@dataclass(frozen=True, slots=True)
class HidNode:
    path: Path
    sysfs_path: Path
    interface: int
    vendor_id: int
    product_id: int
    serial: str
    product: str
    readable: bool
    writable: bool

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["path"] = str(self.path)
        data["sysfs_path"] = str(self.sysfs_path)
        return data


def _read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, PermissionError, OSError):
        return default


def _find_parent_with(path: Path, attribute: str) -> Path | None:
    for candidate in (path, *path.parents):
        if (candidate / attribute).exists():
            return candidate
    return None


def inspect_hidraw_node(class_entry: Path, dev_root: Path = Path("/dev")) -> HidNode | None:
    device_link = class_entry / "device"
    try:
        hid_device = device_link.resolve(strict=True)
    except (FileNotFoundError, OSError):
        return None

    interface_parent = _find_parent_with(hid_device, "bInterfaceNumber")
    usb_parent = _find_parent_with(hid_device, "idVendor")
    if interface_parent is None or usb_parent is None:
        return None

    try:
        interface = int(_read_text(interface_parent / "bInterfaceNumber"), 16)
        vendor_id = int(_read_text(usb_parent / "idVendor"), 16)
        product_id = int(_read_text(usb_parent / "idProduct"), 16)
    except ValueError:
        return None

    device_path = dev_root / class_entry.name
    return HidNode(
        path=device_path,
        sysfs_path=hid_device,
        interface=interface,
        vendor_id=vendor_id,
        product_id=product_id,
        serial=_read_text(usb_parent / "serial"),
        product=_read_text(usb_parent / "product"),
        readable=os.access(device_path, os.R_OK),
        writable=os.access(device_path, os.W_OK),
    )


def discover_hid_nodes(
    sys_class: Path = Path("/sys/class/hidraw"),
    dev_root: Path = Path("/dev"),
    product_id: int = RECEIVER_PRODUCT_ID,
) -> list[HidNode]:
    try:
        entries: Iterable[Path] = sorted(sys_class.glob("hidraw*"))
    except OSError:
        return []

    nodes: list[HidNode] = []
    for entry in entries:
        node = inspect_hidraw_node(entry, dev_root)
        if node and node.vendor_id == VENDOR_ID and node.product_id == product_id:
            nodes.append(node)
    return nodes


def find_wired_headset(
    sys_class: Path = Path("/sys/class/hidraw"), dev_root: Path = Path("/dev")
) -> HidNode | None:
    """Report a headset sitting on its charging cable.

    Detection is sysfs-only on purpose: the node belongs to root because the
    udev rule deliberately covers just the receiver's control interface, and
    nothing here ever opens it. Knowing the cable is plugged in is what turns
    a bare "offline" into an explanation.
    """

    return next(
        iter(discover_hid_nodes(sys_class, dev_root, WIRED_HEADSET_PRODUCT_ID)), None
    )


def _control_node_for(
    product_id: int, sys_class: Path, dev_root: Path
) -> HidNode | None:
    return next(
        (
            node
            for node in discover_hid_nodes(sys_class, dev_root, product_id)
            if node.interface == CONTROL_INTERFACE
        ),
        None,
    )


def find_control_node(
    sys_class: Path = Path("/sys/class/hidraw"), dev_root: Path = Path("/dev")
) -> HidNode | None:
    """Return the control interface to drive, cable before receiver.

    A headset switched on while plugged in exposes control interface 3 itself.
    It is preferred when both are present: in that state the headset is on the
    cable, so the receiver has nothing paired to it anyway.
    """

    return _control_node_for(
        USB_HEADSET_PRODUCT_ID, sys_class, dev_root
    ) or _control_node_for(RECEIVER_PRODUCT_ID, sys_class, dev_root)
