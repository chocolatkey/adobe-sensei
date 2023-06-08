import httpx
import json
import random
from datetime import datetime
from requests_toolbelt.multipart import decoder, encoder

# Need "device_token" & "device_id"
with open("config.json", "r") as f:
    config = json.load(f)

assert config["device_token"]
assert config["device_id"]

# 2023-06-07T20:12:34.567-0100
nt = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S.%f%z")

client = httpx.Client(
    headers={
        # TODO windows version randomized?
        "User-Agent": f"NGL Client/1.33.0.11 (WINDOWS_64/10.0.19045.1) [{nt[:22] + nt[25:]}]",
        "X-IMS-ClientId": "ps_gentech_diffusion_desktop",
    },
    timeout=60,  # Don't want to timeout while Adobe is doing AI thingies
)

# Adobe IMS = Adobe Identity Management System

# IMSLib.dll + imshelper.dll
# SQLite DB Adobe\OOBE\opm.db has creds (TODO figure out encryption scheme) or just intercept

# Device tokens are JWTs that last a year with user auth
# Device ID is a UUID derived from your machine info (I think?)

# Authorize
print("Authorizing device ID", config["device_id"])
r = client.post(
    "https://ims-prod06.adobelogin.com/ims/token/v4",
    data={
        "grant_type": "device",
        "device_id": config["device_id"],
        "device_token": config["device_token"],
        "client_id": "ps_gentech_diffusion_desktop",
        "scope": "AdobeID,openid,creative_cloud",
        "locale": "en_US",
    },
)
r.raise_for_status()
j = r.json()
assert j["access_token"]
client.headers.update(
    {
        "Authorization": f'Bearer {j["access_token"]}',
        "x-api-key": "ps_gentech_diffusion_desktop",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": "",
    }
)

####################################################################################################

# Possible values:
# - https://sensei.adobe.io
# - https://sensei-ue1.adobe.io (default?)
# - https://sensei-stage-ue1.adobe.io
client.base_url = "https://sensei-ue1.adobe.io"

# Engine
# - Classification:diffusion-service:Service-7367c21c82b946e7adb3995315de18a8
# - Classification:diffusion-service:Service-c742bc2eaae1491987dc00daff32fc07
# - Feature:autocrop:Service-3f6d0678be864218ad8c89ef48462c17 (the one we use)
# - Feature:sensei-demo:Service-66484d87ede04702af063315a7de4094 # Photoshop Conversion(?)
# - Feature:sensei-demo:Service-efcddebf2b4141e9ae7252091c6a2398 # Illustrator Conversion(?)
engine = "Feature:autocrop:Service-3f6d0678be864218ad8c89ef48462c17"

# I think this is just a client ID for PS?
analyzer = "Service-398fbb92554d450f9e47b1a8ac8f033a"

gi_MODE = "ginp"  # ginp = no text promp, tinp = text prompt
# TODO text prompt input with gi_PROMPT
gi_SEED = random.randint(0, 2**31 - 1)  # Higher than max int32 crashes the API
print("Seed:", gi_SEED)

# Harcoded? Work it out!
gi_NUM_STEPS = 50
gi_GUIDANCE = 6
gi_SIMILARITY = 0
gi_CROP = False
gi_DILATE = False
gi_CONTENT_PRESERVE = 0.0
gi_ENABLE_PROMPT_FILTER = True


####################################################################################################


def encode_and_post(path: str, data: dict):
    enc = encoder.MultipartEncoder(data)
    return client.post(
        path, data=enc.to_string(), headers={"Content-Type": enc.content_type}
    )


# Create session
print("Creating session...")
r = encode_and_post(
    "/services/session/create", {"contentAnalyzerRequests": '{"session_ttl":600}'}
)
r.raise_for_status()

# Session data is in the headers
session_size = r.headers["remaining-session-size"]  # 25MB
session_id = r.headers["x-session-id"]
client.headers.update({"x-session-id": session_id})
print("Session", session_id, "of size", int(session_size) / 1024 / 1024, "MB")

print("Submitting image...")
r = client.post(
    "/services/session/load",
    data={
        "loadContentRequest": json.dumps(
            {
                "sensei:inputs": {
                    "gi_IMAGE": {
                        "dc:format": "image/png",
                        "sensei:multipart_field_name": "input_image",
                    },
                    "gi_MASK": {
                        "dc:format": "image/png",
                        "sensei:multipart_field_name": "input_mask",
                    },
                }
            }
        )
    },
    files={
        "input_image": open("image.png", "rb"),
        "input_mask": open("mask.png", "rb"),
    },
)
r.raise_for_status()
assert r.json()["status"] == 200

client.headers.update(
    {
        "x-analyzer-id": analyzer,
        "Prefer": "respond-sync, wait=30",  # TODO what happens if increased to e.g. 60?
    }
)

# PS makes 3 simultaneous requests to this endpoint with different seeds
print("Waiting for prediction...")
r = encode_and_post(
    "/services/v2/predict",
    {
        "contentAnalyzerRequests": json.dumps(
            {
                "sensei:engines": [
                    {
                        "sensei:execution_info": {"sensei:engine": engine},
                        "sensei:inputs": {
                            "gi_IMAGE": {
                                "dc:format": "image/png",
                                "repo:id": "gi_IMAGE",
                                "sensei:repoType": "SESSION_CACHE",
                            },
                            "gi_MASK": {
                                "dc:format": "image/png",
                                "repo:id": "gi_MASK",
                                "sensei:repoType": "SESSION_CACHE",
                            },
                        },
                        "sensei:outputs": {
                            "gi_GEN_IMAGE": {
                                "dc:format": "image/png",
                                "sensei:multipart_field_name": "generated-image",
                            },
                            "gi_GEN_MASK": {
                                "dc:format": "image/png",
                                "sensei:multipart_field_name": "generated-mask",
                            },
                            "spl:response": {
                                "dc:format": "application/json",
                                "sensei:multipart_field_name": "spl:response",
                            },
                        },
                        "sensei:params": {
                            "spl:request": {
                                "graph": {"uri": "urn:graph:MultiDiffusion_v2"},
                                "inputs": {
                                    "gi_IMAGE": {"id": "1", "type": "image"},
                                    "gi_MASK": {"id": "2", "type": "image"},
                                },
                                "outputs": {
                                    "gi_GEN_IMAGE": {
                                        "expectedMimeType": "image/png",
                                        "id": "5",
                                        "type": "image",
                                    },
                                    "gi_GEN_MASK": {
                                        "expectedMimeType": "image/png",
                                        "id": "6",
                                        "type": "image",
                                    },
                                    "gi_GEN_STATUS": {"id": "7", "type": "scalar"},
                                },
                                "params": [
                                    {
                                        "name": "gi_MODE",
                                        "type": "string",
                                        "value": gi_MODE,
                                    },
                                    {
                                        "name": "gi_SEED",
                                        "type": "scalar",
                                        "value": gi_SEED,
                                    },
                                    {
                                        "name": "gi_NUM_STEPS",
                                        "type": "scalar",
                                        "value": gi_NUM_STEPS,
                                    },
                                    {
                                        "name": "gi_GUIDANCE",
                                        "type": "scalar",
                                        "value": gi_GUIDANCE,
                                    },
                                    {
                                        "name": "gi_SIMILARITY",
                                        "type": "scalar",
                                        "value": gi_SIMILARITY,
                                    },
                                    {
                                        "name": "gi_CROP",
                                        "type": "boolean",
                                        "value": gi_CROP,
                                    },
                                    {
                                        "name": "gi_DILATE",
                                        "type": "boolean",
                                        "value": gi_DILATE,
                                    },
                                    {
                                        "name": "gi_CONTENT_PRESERVE",
                                        "type": "scalar",
                                        "value": gi_CONTENT_PRESERVE,
                                    },
                                    {
                                        "name": "gi_ENABLE_PROMPT_FILTER",
                                        "type": "boolean",
                                        "value": gi_ENABLE_PROMPT_FILTER,
                                    },
                                    # {
                                    #    "name": "gi_PROMPT",
                                    #    "type": "string",
                                    #    "value": "another cat",
                                    # },
                                ],
                            }
                        },
                    }
                ],
                "sensei:in_response": False,
                "sensei:invocation_batch": False,
                "sensei:invocation_mode": "synchronous",
                "sensei:name": "Multidiffusion",
            }
        )
    },
)
r.raise_for_status()
multipart_data = decoder.MultipartDecoder.from_response(r)
for part in multipart_data.parts:
    is_json = False

    for key, value in part.headers.items():
        if key.decode("utf8") == "Content-Disposition":
            if '"contentAnalyzerResponse"' in value.decode("utf8"):
                with open(
                    "out/contentAnalyzerResponse.json", "w", encoding="utf-8"
                ) as f:
                    json.dump(json.loads(part.text), f, indent=4)
            elif f'"spl:response"' in value.decode("utf8"):
                with open("out/spl_response.json", "w", encoding="utf-8") as f:
                    json.dump(json.loads(part.text), f, indent=4)
            elif f'"generated-mask"' in value.decode("utf8"):
                with open(f"out/generated-mask-{gi_SEED}.png", "wb") as f:
                    f.write(part.content)
            elif f'"generated-image"' in value.decode("utf8"):
                with open(f"out/generated-image-{gi_SEED}.png", "wb") as f:
                    f.write(part.content)
