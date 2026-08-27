"""Phase 21: deciding whether a storefront address is one we will call.

A Shopify shop has to end in `.myshopify.com`, which makes this nearly a
non-problem. A WooCommerce store is wherever its owner put WordPress, so
the address a caller types is an address this server then dials carrying
that shop's credentials -- and on a cloud host, `169.254.169.254` is the
machine's own.
"""

import pytest

from app.core.exceptions import EcommerceProviderError
from app.integrations.ecommerce.hosts import normalise_host
from app.integrations.ecommerce.shopify import normalise_shop


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("shop.example.com", "shop.example.com"),
        ("https://shop.example.com", "shop.example.com"),
        ("https://shop.example.com/", "shop.example.com"),
        ("  SHOP.Example.COM  ", "shop.example.com"),
        ("a.b.co.uk", "a.b.co.uk"),
        ("my-shop.example.com", "my-shop.example.com"),
    ],
)
def test_an_address_somebody_would_paste_is_accepted(
    written: str,
    expected: str,
) -> None:
    assert normalise_host(written) == expected


def test_plain_http_is_refused_rather_than_upgraded() -> None:
    # A storefront reached over http hands its API credentials to anybody
    # on the path, and silently rewriting the scheme would be pretending
    # somebody asked for something they did not.
    with pytest.raises(EcommerceProviderError):
        normalise_host("http://shop.example.com")


@pytest.mark.parametrize(
    "written",
    [
        "localhost",
        "shop.local",
        "shop.internal",
        "box.home.arpa",
        "127.0.0.1",
        "169.254.169.254",
        "10.0.0.1",
        "192.168.1.1",
        "172.16.0.1",
    ],
)
def test_an_address_inside_the_wall_is_refused(written: str) -> None:
    with pytest.raises(EcommerceProviderError):
        normalise_host(written)


@pytest.mark.parametrize(
    "written",
    [
        "shop.example.com/wp-json",
        "shop.example.com:8080",
        "user:pass@shop.example.com",
        "shop.example.com?a=b",
        "shop.example.com/../evil.example.com",
        "shop",
        "",
        "https://",
        "-shop.example.com",
        "shop.example.com.",
    ],
)
def test_anything_that_is_not_plainly_a_host_is_refused(written: str) -> None:
    # Refused rather than trimmed down to a host: trimming would quietly
    # connect a shop the caller only half named, and a value that is not
    # what somebody typed should not be the value that gets used.
    with pytest.raises(EcommerceProviderError):
        normalise_host(written)


# --- Shopify's own, which is narrower ------------------------------------


def test_a_shopify_shop_must_be_a_myshopify_domain() -> None:
    assert normalise_shop("https://acme.myshopify.com/") == "acme.myshopify.com"

    with pytest.raises(EcommerceProviderError):
        normalise_shop("acme.example.com")
