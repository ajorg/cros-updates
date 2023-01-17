#!/usr/bin/env python3
# Copyright (c) Andrew Jorgensen. All rights reserved.
# SPDX-License-Identifier: MIT
"""Sends notifications of Chrome OS updates

Uses the same update service API that a Chromebook uses to check what the
latest version is for a particular update channel / track. Reads configuration
from the environment because it's intended to be used in AWS Lambda, at least
in this form here.

TABLE_NAME should contain the name of a DynamoDB table to store known version
information for your Chromebooks.

TOPIC_ARN should contain the ARN of an SNS topic to send notifications to (you
can subscribe to SMS notifications).

CHROMEBOOKS_JSON should contain a JSON document describing the Chromebooks you
want queried.

The format of CHROMEBOOKS_JSON is like this, so that you can query many:
[
  {
    "appid": "{92A7272A-834A-47A3-9112-E8FD55831660}",
    "track": "stable-channel",
    "board": "kevin-signed-mpkeys",
    "hardware_class": "KEVIN D25-A3E-B2A-O8Y"
  }
]
"""
from os import environ

# requests is neat and trendy, but it's not in the standard library, so...
from urllib.request import urlopen
from xml.etree import ElementTree
from datetime import date
import json
import re

import boto3

# If the protocol changes, keeping these as constants may make updates easier
AUSERVER = environ.get("AUSERVER") or "https://tools.google.com/service/update2"
REQUEST = """<?xml version="1.0" encoding="UTF-8"?>
<request protocol="3.0" ismachine="1">
  <app appid="{appid}" track="{track}" board="{board}" hardware_class="{hardware_class}" delta_okay="false">
    <updatecheck/>
  </app>
</request>"""
VERSION_ATTRIB = "ChromeVersion"
VERSION_XPATH = f".//action[@{VERSION_ATTRIB}]"
EOL_ATTRIB = "_eol_date"
EOL_XPATH = f".//updatecheck[@{EOL_ATTRIB}]"
SECONDS_IN_DAY = 24 * 60 * 60

# Default this to something valid for testing
CHROMEBOOKS_JSON = (
    environ.get("CHROMEBOOKS_JSON")
    or """[
  {
    "appid": "{92A7272A-834A-47A3-9112-E8FD55831660}",
    "track": "stable-channel",
    "board": "kevin-signed-mpkeys",
    "hardware_class": "KEVIN D25-A3E-B2A-O8Y"
  },
  {
    "appid": "{C924E0C4-AF80-4B6B-A6F0-DD75EDBCC37C}",
    "track": "stable-channel",
    "board": "reven-signed-mp-v2keys",
    "hardware_class": "REVEN-ANAE A6A-A7I"
  }
]"""
)
CHROMEBOOKS = json.loads(CHROMEBOOKS_JSON)

if __name__ != "__main__":
    # Only connect to AWS when used as a module
    TABLE_NAME = environ.get("TABLE_NAME") or "cros-updates"
    TABLE = boto3.resource("dynamodb").Table(TABLE_NAME)

    TOPIC_ARN = (
        # Obviously this default value is in a specific account
        # There's a way to get the ARN from the name, but that's tedious
        environ.get("TOPIC_ARN")
        or "arn:aws:sns:us-west-2:246745595609:cros-updates"
    )
    TOPIC = boto3.resource("sns").Topic(TOPIC_ARN)

# Get chromebook names from the recovery table
RECOVERY = []
for url in (
    "https://dl.google.com/dl/edgedl/chromeos/recovery/recovery2.json",
    "https://dl.google.com/dl/edgedl/chromeos/recovery/cloudready_recovery2.json",
):
    with urlopen(url) as RECOVERY2_JSON:
        RECOVERY.extend(json.load(RECOVERY2_JSON))

for CHROMEBOOK in CHROMEBOOKS:
    for RECORD in RECOVERY:
        if re.fullmatch(RECORD["hwidmatch"], CHROMEBOOK["hardware_class"]):
            CHROMEBOOK["name"] = RECORD["name"]
            break


def request_update(appid, track, board, hardware_class):
    request = REQUEST.format(
        appid=appid, track=track, board=board, hardware_class=hardware_class
    )
    print(json.dumps({"Request": request}))

    with urlopen(AUSERVER, data=request.encode()) as response:
        data = response.read()
        print(json.dumps({"Response": data.decode(), "Status": response.status}))

    return UpdateResponse(data)


class UpdateResponse:
    """Representation of a chromeOS update response"""

    def __init__(self, data):
        self._root = ElementTree.fromstring(data)

    @property
    def version(self):
        """Get the Chrome version for a chromeOS device"""
        for element in self._root.findall(VERSION_XPATH):
            return element.attrib[VERSION_ATTRIB]

    @property
    def eol(self):
        """Get the EOL date for a chromeOS device"""
        try:
            element = self._root.find(EOL_XPATH)
            _eol_date = element.attrib[EOL_ATTRIB]
        except AttributeError:
            return None
        return date.fromtimestamp(int(_eol_date) * SECONDS_IN_DAY)


def lambda_handler(event, context):
    """AWS Lambda Handler"""
    for chromebook in CHROMEBOOKS:
        item = TABLE.get_item(
            Key={
                k: v for k, v in chromebook.items() if k in ("appid", "hardware_class")
            }
        )
        print(json.dumps(item.get("Item"), sort_keys=True))
        item = item.get("Item", chromebook)
        response = request_update(
            **(
                {
                    k: chromebook[k]
                    for k in ("appid", "track", "board", "hardware_class")
                }
            )
        )

        name = chromebook.get(
            "name", chromebook["hardware_class"].split()[0].lower().capitalize()
        )
        print(
            json.dumps(
                {"name": name, "version": response.version, "eol": str(response.eol)}
            )
        )

        old_version = item.get("version")
        if response.version != old_version:
            message = f"{name} updated from {old_version} to {response.version}"
            if response.eol:
                eol = response.eol.strftime("%B %Y")
                message += f" and supported until {eol}"
            TOPIC.publish(Message=message)
            print(json.dumps({"Message": message}))

            item["version"] = response.version
            item["name"] = name
            print(json.dumps(item, sort_keys=True))
            TABLE.put_item(Item=item)


if __name__ == "__main__":
    for chromebook in CHROMEBOOKS:
        response = request_update(
            **(
                {
                    k: chromebook[k]
                    for k in ("appid", "track", "board", "hardware_class")
                }
            )
        )
        name = chromebook.get(
            "name", chromebook["hardware_class"].split()[0].lower().capitalize()
        )
        print(
            json.dumps(
                {"name": name, "version": response.version, "eol": str(response.eol)}
            )
        )

        message = f"{name} updated to {response.version}"
        if response.eol:
            eol = response.eol.strftime("%B %Y")
            message += f" and supported until {eol}"
        print(message)
