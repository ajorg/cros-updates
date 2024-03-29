# cros-updates
Notify of Chrome OS Updates

**Update:** The Chrome version is back in the metadata, and I've added a feature to lookup the product name so that updates come as `Samsung Galaxy Chromebook updated to 103.0.5060.132` instead of `Kohaku-jpzq updated to 14816.131.0`.

~~**Update:** Google broke this around 2pm Pacific on September 22, 2020 by removing most of the metadata from the response.
I've temporarily moved this to using the Chrome OS version instead of the Chrome version. It doesn't tell the same story, but at least it works.~~

## Overview
This project contains a module and AWS Lambda function that notifies me
whenever Google pushes an update to one of my Chromebooks. It does this by
calling the same API the Chromebook calls to check for its own updates, but
with some simplification of parameters so that I shouldn't have to update the
function frequently. Triggered by a CloudWatch Events scheduled event, the
function compares the response with the one it got the last time it ran (stored
in DynamoDB) and sends a message to an SNS Topic if there's been a change. I
have my phone number subscribed to the SNS Topic, so I'll get a text.

It's all completely serverless and costs nearly nothing. My AWS bill is about
$0.34/month but that's mostly for other things I have in S3.

## Setup
Sorry for not going into great detail here. Obviously there are important
things missing from this project, like a minimal IAM policy or a CDK script to
set it all up. Cut an issue or send a pull request if you want to help improve
anything, or I may get around to it eventually.

The project includes example Chromebook data and environment configuration.

```sh
aws lambda update-function-configuration \
  --function-name cros-updates \
  --environment "$(
    jq -c \
      --arg chromebooks_json "$(jq -c . chromebooks.json)" \
      '.Variables.CHROMEBOOKS_JSON = $chromebooks_json' \
      environment.json)"
```
