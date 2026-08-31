import os
import sys
import json
import time
import random
import urllib.request
import urllib.parse
from pathlib import Path
from config import VK_GROUP_TOKEN, VK_API_VERSION

API_BASE = "https://api.vk.com/method/"

def call_api(method: str, params: dict = None, token: str = None) -> dict:
    if params is None:
        params = {}
    if token is None:
        token = VK_GROUP_TOKEN
    params["access_token"] = token
    if "v" not in params:
        params["v"] = VK_API_VERSION
    
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(API_BASE + method, data=data)
    with urllib.request.urlopen(req, timeout=15) as response:
        res = json.loads(response.read().decode("utf-8"))
        if "error" in res:
            raise RuntimeError(f"VK API Error ({method}): {res['error']}")
        return res.get("response", {})

def send_message(user_id: int, text: str, keyboard: dict = None, attachment: str = None) -> int:
    params = {
        "user_id": user_id,
        "random_id": random.randint(1, 2147483647),
        "message": text,
    }
    if keyboard:
        params["keyboard"] = json.dumps(keyboard, ensure_ascii=False)
    if attachment:
        params["attachment"] = attachment
    try:
        return call_api("messages.send", params)
    except RuntimeError as e:
        # If error 912 (bot capabilities disabled in community), retry without keyboard
        if "912" in str(e) and keyboard:
            params.pop("keyboard", None)
            return call_api("messages.send", params)
        raise

def set_activity(user_id: int, activity_type: str = "typing"):
    try:
        call_api("messages.setActivity", {
            "user_id": user_id,
            "type": activity_type
        })
    except Exception:
        pass

def mark_as_read(peer_id: int, start_message_id: int = None):
    try:
        params = {"peer_id": peer_id}
        if start_message_id:
            params["start_message_id"] = start_message_id
        call_api("messages.markAsRead", params)
    except Exception:
        pass

def verify_message_delivered(msg_id: int, expect_attachment: str = None) -> bool:
    """Verifies that a message was truly recorded and delivered on VK servers with expected attachments."""
    try:
        res = call_api("messages.getById", {"message_ids": msg_id})
        items = res.get("items", [])
        if not items:
            return False
        msg = items[0]
        if expect_attachment:
            attachments = msg.get("attachments", [])
            types = [a.get("type") for a in attachments]
            if expect_attachment not in types:
                return False
        return True
    except Exception:
        return False

def upload_photo(user_id: int, photo_path: str) -> str:
    """Uploads a photo to VK messages server and returns attachment string 'photo{owner_id}_{id}'"""
    upload_server = call_api("photos.getMessagesUploadServer", {"peer_id": user_id})
    upload_url = upload_server.get("upload_url")
    if not upload_url:
        raise RuntimeError("Failed to get photos upload server URL")

    # Multipart upload
    boundary = "----WebKitFormBoundary" + "".join([str(random.randint(0, 9)) for _ in range(16)])
    with open(photo_path, "rb") as f:
        file_bytes = f.read()

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="photo"; filename="{os.path.basename(photo_path)}"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(upload_url, data=body)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(req, timeout=30) as r:
        upload_resp = json.loads(r.read().decode("utf-8"))

    photo_val = upload_resp.get("photo")
    if not photo_val or photo_val == "[]":
        raise RuntimeError(f"VK photos upload server returned invalid photo data: {upload_resp}")

    # Save messages photo
    save_resp = call_api("photos.saveMessagesPhoto", {
        "photo": photo_val,
        "server": upload_resp["server"],
        "hash": upload_resp["hash"],
    })
    if not save_resp:
        raise RuntimeError("Failed to save uploaded photo in VK")
    saved = save_resp[0]
    return f"photo{saved['owner_id']}_{saved['id']}"

def upload_audiomessage(user_id: int, audio_path: str) -> str:
    """Uploads voice note (audiomessage / doc) to VK messages server and returns 'doc{owner_id}_{id}'"""
    upload_server = call_api("docs.getMessagesUploadServer", {
        "peer_id": user_id,
        "type": "audio_message"
    })
    upload_url = upload_server.get("upload_url")
    if not upload_url:
        raise RuntimeError("Failed to get docs upload server URL")

    boundary = "----WebKitFormBoundary" + "".join([str(random.randint(0, 9)) for _ in range(16)])
    with open(audio_path, "rb") as f:
        file_bytes = f.read()

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{os.path.basename(audio_path)}"\r\n'
        f"Content-Type: audio/ogg\r\n\r\n"
    ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(upload_url, data=body)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(req, timeout=30) as r:
        upload_resp = json.loads(r.read().decode("utf-8"))

    file_val = upload_resp.get("file")
    if not file_val:
        raise RuntimeError(f"VK docs upload server returned invalid file data: {upload_resp}")

    save_resp = call_api("docs.save", {
        "file": file_val
    })
    audio_doc = save_resp.get("audio_message") or save_resp.get("doc", {})
    return f"doc{audio_doc['owner_id']}_{audio_doc['id']}"

def upload_document(user_id: int, file_path: str, title: str = None) -> str:
    """Uploads a generic document (.txt, .py, .log, .pdf, .zip) to VK messages and returns 'doc{owner_id}_{id}'"""
    if not title:
        title = os.path.basename(file_path)

    upload_server = call_api("docs.getMessagesUploadServer", {
        "peer_id": user_id,
        "type": "doc"
    })
    upload_url = upload_server.get("upload_url")
    if not upload_url:
        raise RuntimeError("Failed to get docs upload server URL")

    boundary = "----WebKitFormBoundary" + "".join([str(random.randint(0, 9)) for _ in range(16)])
    with open(file_path, "rb") as f:
        file_bytes = f.read()

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{os.path.basename(file_path)}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(upload_url, data=body)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(req, timeout=30) as r:
        upload_resp = json.loads(r.read().decode("utf-8"))

    file_val = upload_resp.get("file")
    if not file_val:
        raise RuntimeError(f"VK docs upload server returned invalid file data: {upload_resp}")

    save_resp = call_api("docs.save", {
        "file": file_val,
        "title": title
    })
    doc_obj = save_resp.get("doc", {})
    return f"doc{doc_obj['owner_id']}_{doc_obj['id']}"
