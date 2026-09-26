"""PI System data source, standing in for the (unshown) VBA `PIValue` function
referenced from `VariableValue` for tags formatted like `PI:...`.

The pasted macros only showed the *call site* (`Tag(0) = "PI" -> PIValue(VariableTag, RequiredUnit)`),
not `PIValue` itself, so there's nothing to port line-for-line here. This
provides a small `PIClient` protocol plus a PI Web API-based implementation -
PI Web API is the most portable way to reach an OSIsoft/AVEVA PI System from
Python without a local PI SDK/AF SDK install. If your site instead relies on
PI SDK/AF SDK COM automation, implement `PIClient` against that instead and
pass it in wherever a `pi_client` argument is expected.

`pi_value` assumes tags are written as `PI:<TagPath>` or `PI:<TagPath>:<Unit>`,
mirroring the `OFM:TableName:ColumnHeading:Unit` convention used elsewhere in
the sheet - confirm this against how the real Configuration sheet actually
formats its PI tags before relying on it.
"""

from __future__ import annotations

from typing import Any, Protocol

from .units import ipt_unit_conv


class PIClient(Protocol):
    def get_value(self, tag_path: str) -> Any: ...


class PIWebAPIClient:
    """Reads the current snapshot value of a PI tag via PI Web API."""

    def __init__(self, base_url: str, auth: Any = None, verify_ssl: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.verify_ssl = verify_ssl

    def get_value(self, tag_path: str) -> Any:
        import requests

        point_resp = requests.get(
            f"{self.base_url}/points",
            params={"path": tag_path},
            auth=self.auth,
            verify=self.verify_ssl,
            timeout=30,
        )
        point_resp.raise_for_status()
        value_url = point_resp.json()["Links"]["Value"]

        value_resp = requests.get(value_url, auth=self.auth, verify=self.verify_ssl, timeout=30)
        value_resp.raise_for_status()
        return value_resp.json()["Value"]


def pi_value(client: PIClient, pi_variable: str, reqd_unit: str) -> Any:
    parts = str(pi_variable).split(":")
    if len(parts) < 2:
        raise ValueError(f"PI Variable {pi_variable} should be configured as PI:TagPath[:Unit]")
    tag_path = parts[1]
    pi_unit = parts[2] if len(parts) > 2 else reqd_unit

    raw_value = client.get_value(tag_path)
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return "-"
    return ipt_unit_conv(pi_unit, reqd_unit, value)
