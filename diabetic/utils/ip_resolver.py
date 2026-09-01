"""
diabetic/utils/ip_resolver.py

Dual-stack IPv4 & IPv6 address normalization and CIDR subnet matching utilities.
Supports standard LAN IPs (192.168.x.x), Tailscale IPv4 (100.64.0.0/10),
and Tailscale IPv6 ULA (fd7a:115c:a1e0::/48) with scope ID stripping.
"""
import ipaddress
from typing import Optional, Union


def normalize_ip(raw_ip: Optional[str]) -> Optional[Union[ipaddress.IPv4Address, ipaddress.IPv6Address]]:
    """
    Normalizes an incoming client IP string to a canonical IPv4Address or IPv6Address.
    Strips IPv6 scope IDs (e.g. '%eth0', '%tailscale0') and enclosing brackets ('[::1]').
    """
    if not raw_ip:
        return None

    cleaned = str(raw_ip).split("%")[0].strip("[] \t\n\r")
    if not cleaned:
        return None

    try:
        return ipaddress.ip_address(cleaned)
    except ValueError:
        return None


def matches_ip_rule(client_ip_str: Optional[str], bound_rule: Optional[str]) -> bool:
    """
    Evaluates whether client_ip_str satisfies a bound_rule (exact IP or CIDR network).

    Examples:
        - matches_ip_rule("192.168.4.150", "192.168.4.150") -> True
        - matches_ip_rule("192.168.4.150", "192.168.4.0/24") -> True
        - matches_ip_rule("fd7a:115c:a1e0::432c:a224", "fd7a:115c:a1e0::432c:a224") -> True
        - matches_ip_rule("fd7a:115c:a1e0::432c:a224", "fd7a:115c:a1e0::/48") -> True
    """
    client_ip = normalize_ip(client_ip_str)
    if client_ip is None or not bound_rule:
        return False

    rule_clean = str(bound_rule).split("%")[0].strip("[] \t\n\r")
    try:
        if "/" in rule_clean:
            net = ipaddress.ip_network(rule_clean, strict=False)
            return client_ip in net
        rule_ip = ipaddress.ip_address(rule_clean)
        return client_ip == rule_ip
    except ValueError:
        return False
