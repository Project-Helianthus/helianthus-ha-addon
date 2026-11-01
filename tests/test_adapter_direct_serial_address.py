from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "helianthus/rootfs/etc/services.d/helianthus-gateway/run"

# The address normalisation and the adapter-direct endpoint builder of the run
# script, extracted verbatim and executed under bash with a bashio::exit.nok stub.
START = '  adapter_direct_address_trimmed=$(printf'
END = '  effective_transport="adapter-direct"'

DEVICE = "/dev/serial/by-id/<device>"
HOST_PORT = "192.0.2.10:9999"
ENDPOINT = {"enh": "adapter-direct://", "ens": "adapter-direct-ens://"}


def normalise(address: str, protocol: str) -> tuple[int, str, str, str]:
    """Return (exit code, normalised address, endpoint, stderr)."""
    text = RUN.read_text(encoding="utf-8")
    block = text[text.index(START) : text.index(END)]
    script = (
        "bashio::exit.nok() { echo \"NOK: $*\" >&2; exit 1; }\n"
        f"adapter_direct_address={address!r}\n"
        f"adapter_direct_protocol={protocol!r}\n"
        + block
        + 'printf "%s\\n%s" "${adapter_direct_address_trimmed}" "${effective_address}"\n'
    )
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    trimmed, _, endpoint = proc.stdout.partition("\n")
    return proc.returncode, trimmed, endpoint, proc.stderr


def test_run_script_is_valid_bash() -> None:
    assert subprocess.run(["bash", "-n", str(RUN)], check=False).returncode == 0


# --- serial device paths -----------------------------------------------------


@pytest.mark.parametrize("protocol", ["ens", "enh"])
def test_plain_device_path_passes_through_unchanged(protocol: str) -> None:
    rc, trimmed, endpoint, _ = normalise(DEVICE, protocol)
    assert rc == 0
    assert trimmed == DEVICE
    assert endpoint == f"{ENDPOINT[protocol]}{DEVICE}"


@pytest.mark.parametrize("protocol", ["ens", "enh"])
@pytest.mark.parametrize("slashes", [":", "://"])
def test_agreeing_prefix_on_device_path_is_stripped(protocol: str, slashes: str) -> None:
    # ens:/dev/... (one slash, the path's own) and ens:///dev/... (empty authority).
    address = f"{protocol}:{DEVICE}" if slashes == ":" else f"{protocol}://{DEVICE}"
    rc, trimmed, endpoint, _ = normalise(address, protocol)
    assert rc == 0
    assert trimmed == DEVICE
    assert endpoint == f"{ENDPOINT[protocol]}{DEVICE}"


@pytest.mark.parametrize("protocol", ["ens", "enh"])
def test_agreeing_prefix_is_case_insensitive_and_whitespace_tolerant(protocol: str) -> None:
    rc, trimmed, _, _ = normalise(f"  {protocol.upper()}://{DEVICE}  ", protocol)
    assert rc == 0
    assert trimmed == DEVICE


@pytest.mark.parametrize(
    ("address", "protocol", "prefix"),
    [
        (f"ens:{DEVICE}", "enh", "ens"),
        (f"ens://{DEVICE}", "enh", "ens"),
        (f"enh:{DEVICE}", "ens", "enh"),
        (f"enh://{DEVICE}", "ens", "enh"),
        (f"ENS://{DEVICE}", "enh", "ens"),
    ],
)
def test_disagreeing_prefix_on_device_path_fails_closed(address: str, protocol: str, prefix: str) -> None:
    rc, trimmed, endpoint, err = normalise(address, protocol)
    assert rc == 1
    assert trimmed == "" and endpoint == ""
    # Names both values and the fix.
    assert f"prefix '{prefix}:'" in err
    assert f"adapter_direct_protocol='{protocol}'" in err
    assert f"set adapter_direct_protocol to '{prefix}' or remove the prefix" in err


# --- <host>:<port> addresses behave exactly as before -------------------------


@pytest.mark.parametrize(
    ("address", "protocol", "trimmed", "endpoint"),
    [
        # A scheme prefix on host:port is stripped, the typed protocol decides,
        # and a prefix that disagrees with the protocol is not an error.
        (f"ens://{HOST_PORT}", "enh", HOST_PORT, f"adapter-direct://{HOST_PORT}"),
        (f"enh://{HOST_PORT}", "ens", HOST_PORT, f"adapter-direct-ens://{HOST_PORT}"),
        (f"ens://{HOST_PORT}", "ens", HOST_PORT, f"adapter-direct-ens://{HOST_PORT}"),
        (f"enh://{HOST_PORT}", "enh", HOST_PORT, f"adapter-direct://{HOST_PORT}"),
        (f"ENS://{HOST_PORT}", "enh", HOST_PORT, f"adapter-direct://{HOST_PORT}"),
        # Not a scheme://, so not rewritten (unchanged from before).
        (f"ens:{HOST_PORT}", "enh", f"ens:{HOST_PORT}", f"adapter-direct://ens:{HOST_PORT}"),
        # ens://dev/x is not the device-path form (that is ens:///dev/x or ens:/dev/x).
        ("ens://dev/x", "enh", "dev/x", "adapter-direct://dev/x"),
        # Other prefixes and plain addresses.
        (f"adapter-direct://{HOST_PORT}", "enh", HOST_PORT, f"adapter-direct://{HOST_PORT}"),
        (f"adapter-direct-ens://{HOST_PORT}", "ens", HOST_PORT, f"adapter-direct-ens://{HOST_PORT}"),
        (f"adapter-direct-ens://{HOST_PORT}", "enh", HOST_PORT, f"adapter-direct://{HOST_PORT}"),
        (HOST_PORT, "enh", HOST_PORT, f"adapter-direct://{HOST_PORT}"),
        (HOST_PORT, "ens", HOST_PORT, f"adapter-direct-ens://{HOST_PORT}"),
        (f"  {HOST_PORT}  ", "ens", HOST_PORT, f"adapter-direct-ens://{HOST_PORT}"),
    ],
)
def test_host_port_forms_behave_as_before(address: str, protocol: str, trimmed: str, endpoint: str) -> None:
    rc, got_trimmed, got_endpoint, err = normalise(address, protocol)
    assert rc == 0, err
    assert "NOK" not in err
    assert got_trimmed == trimmed
    assert got_endpoint == endpoint


def test_empty_address_after_prefix_is_still_rejected() -> None:
    rc, _, _, err = normalise("ens://", "ens")
    assert rc == 1
    assert "adapter_direct_address is required" in err
