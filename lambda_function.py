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
import json

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
VERSION_XPATH = ".//action[@{}]".format(VERSION_ATTRIB)

# Default this to something valid for testing
CHROMEBOOKS_JSON = (
    environ.get("CHROMEBOOKS_JSON")
    or """[
  {
    "appid": "{92A7272A-834A-47A3-9112-E8FD55831660}",
    "track": "stable-channel",
    "board": "kevin-signed-mpkeys",
    "hardware_class": "KEVIN D25-A3E-B2A-O8Y"
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


def chrome_version(appid, track, board, hardware_class):
    """Get the Chrome version for a Chromebook"""
    request = REQUEST.format(
        appid=appid, track=track, board=board, hardware_class=hardware_class
    )
    print(json.dumps({"Request": request}))

    with urlopen(AUSERVER, data=request.encode()) as response:
        data = response.read()
        print(json.dumps({"Response": data.decode(), "Status": response.status}))
        root = ElementTree.fromstring(data)

    for action in root.findall(VERSION_XPATH):
        return action.attrib[VERSION_ATTRIB]


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
        version = chrome_version(**chromebook)
        if version != item.get("version"):
            name = chromebook["hardware_class"].split()[0].lower().capitalize()
            message = "{name} updated to {version}".format(name=name, version=version)
            TOPIC.publish(Message=message)
            print(json.dumps({"Message": message}))

            item["version"] = version
            print(json.dumps(item, sort_keys=True))
            TABLE.put_item(Item=item)


if __name__ == "__main__":
    for chromebook in CHROMEBOOKS:
        print(chrome_version(**chromebook))
