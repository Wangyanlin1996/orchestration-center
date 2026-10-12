# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Browser gateways narrow access; they never assert a caller identity."""

BROWSER_GATEWAY_HEADER = "X-OpenAN-Browser-Gateway"


def is_browser_gateway_request(request) -> bool:
    # The header grants nothing: spoofing it can only restrict access. Shipped
    # proxies overwrite any incoming value, including an explicitly empty one.
    return BROWSER_GATEWAY_HEADER in request.headers
