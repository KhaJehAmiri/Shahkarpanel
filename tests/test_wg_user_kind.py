"""Tests for WireGuard / AmneziaWG user kind markers."""
from app.wireguard.kind import (
    NXPANEL_WG_KIND,
    user_wg_stack_labels,
    wg_kind_from_template_tags,
    wg_wants_awg_address,
    wg_wants_plain_address,
)


def test_user_wg_stack_labels_from_marker():
    assert user_wg_stack_labels({NXPANEL_WG_KIND: "amneziawg"}) == ["amneziawg"]
    assert user_wg_stack_labels({NXPANEL_WG_KIND: "wireguard"}) == ["wireguard"]
    assert user_wg_stack_labels({NXPANEL_WG_KIND: "both"}) == ["wireguard", "amneziawg"]


def test_user_wg_stack_labels_from_addresses():
    assert user_wg_stack_labels({"awg_address": "10.11.0.2/32"}) == ["amneziawg"]
    assert user_wg_stack_labels({"address": "10.10.0.2/32"}) == ["wireguard"]
    assert user_wg_stack_labels(
        {"address": "10.10.0.2/32", "awg_address": "10.11.0.2/32"}
    ) == ["wireguard", "amneziawg"]


def test_wg_wants_address_respects_marker():
    awg_only = {NXPANEL_WG_KIND: "amneziawg"}
    plain_only = {NXPANEL_WG_KIND: "wireguard"}
    assert wg_wants_awg_address(awg_only) is True
    assert wg_wants_plain_address(awg_only) is False
    assert wg_wants_awg_address(plain_only) is False
    assert wg_wants_plain_address(plain_only) is True


def test_wg_kind_from_template_tags():
    assert wg_kind_from_template_tags(["__native:amneziawg"]) == "amneziawg"
    assert wg_kind_from_template_tags(["__native:wireguard"]) == "wireguard"
    assert wg_kind_from_template_tags(["__native:wireguard", "__native:amneziawg"]) == "both"
