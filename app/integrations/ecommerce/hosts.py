"""Deciding whether a shop's address is one this server will call.

The address of a storefront is the only part of a URL that a caller
supplies, and this application then makes requests to it carrying that
shop's credentials. For Shopify that is nearly a non-problem, because the
answer has to end in `.myshopify.com`. WooCommerce is wherever its owner
put WordPress, so anything is a candidate -- and "anything" includes
`http://169.254.169.254/`, which on a cloud host is the metadata service
that hands out the machine's own credentials.

So a host gets checked before it is ever dialled. What is refused here is
the shape of the address, which is cheap and catches the whole obvious
class: a literal private or loopback address, a name nobody can resolve
outside a datacentre, a scheme that is not TLS.

What this does *not* do is resolve the name and check where it points. A
hostname that resolves to a private address today, or resolves differently
between this check and the request, walks straight past. Closing that
means resolving here and connecting to the resolved address, which is a
custom transport rather than a regular expression. It is worth doing the
day this application is deployed somewhere with a metadata service and an
untrusted signup flow, and it is written down here so that day is a
decision rather than a discovery.
"""

import ipaddress
import re

from app.core.exceptions import EcommerceProviderError

# A hostname, as RFC 1123 allows one: labels of letters, digits and
# hyphens, not starting or ending with a hyphen, at least two of them.
# Deliberately without a port: a storefront on a non-standard port is not
# something this product supports, and allowing one widens what can be
# reached for no case anybody has.
HOSTNAME = re.compile(
    r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)

# Names that mean "this machine" or "this network", whatever DNS says.
_LOCAL_SUFFIXES = (".local", ".localhost", ".internal", ".home.arpa")
_LOCAL_NAMES = frozenset({"localhost"})


def normalise_host(address: str) -> str:
    """The bare lowercase host out of whatever somebody pasted.

    A scheme and a trailing slash are forgiven, because people paste
    `https://shop.example.com/` out of a browser bar. Anything else with
    a path, a port, a query or credentials in it is refused rather than
    trimmed down to the host: trimming would quietly connect a shop the
    caller only half named, and a value that is not what somebody typed
    should not be the value that gets used.
    """
    written = address.strip().lower()

    if written.startswith("http://"):
        # Refused rather than upgraded. A storefront reached over plain
        # HTTP hands its API credentials to anybody on the path, and
        # silently rewriting it to https would be pretending somebody
        # asked for something they did not.
        raise EcommerceProviderError("A storefront address must use https")

    host = written.removeprefix("https://").rstrip("/")

    if not HOSTNAME.match(host):
        raise EcommerceProviderError(f"Not a usable storefront address: {address}")

    if _is_local(host):
        raise EcommerceProviderError(f"Not a reachable storefront: {address}")

    return host


def _is_local(host: str) -> bool:
    """Whether this names something inside the wall rather than a shop."""
    if host in _LOCAL_NAMES or host.endswith(_LOCAL_SUFFIXES):
        return True

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # A name rather than a literal, which is the ordinary case. What
        # it resolves to is the gap this module's docstring describes.
        return False

    return not address.is_global
