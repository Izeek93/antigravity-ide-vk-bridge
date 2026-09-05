import os
import sys
import json
import random
import urllib.request
import urllib.parse
from typing import Optional

import config
import post_scheduler

def upload_photo_to_wall(photo_path: str) -> Optional[str]:
    """
    Загружает фотографию на стену сообщества через User Token (photos scope)
    и возвращает строку вложения photo{owner_id}_{id}.
    """
    user_token = post_scheduler._load_user_token()
    if not user_token:
        print("[Upload Error] No user token found", file=sys.stderr)
        return None

    # 1. photos.getWallUploadServer
    url = "https://api.vk.com/method/photos.getWallUploadServer"
    params = {
        "access_token": user_token,
        "v": config.VK_API_VERSION,
        "group_id": config.VK_GROUP_ID
    }
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=15) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        if "response" not in res:
            print(f"[Upload Error] getWallUploadServer: {res}", file=sys.stderr)
            return None
        upload_url = res["response"]["upload_url"]

    # 2. Upload file
    boundary = "----WebKitFormBoundary" + "".join([str(random.randint(0, 9)) for _ in range(16)])
    with open(photo_path, "rb") as f:
        file_bytes = f.read()

    body = bytearray()
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(f'Content-Disposition: form-data; name="photo"; filename="photo.jpg"\r\n'.encode("utf-8"))
    body.extend(b"Content-Type: image/jpeg\r\n\r\n")
    body.extend(file_bytes)
    body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))

    upload_req = urllib.request.Request(upload_url, data=bytes(body))
    upload_req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(upload_req, timeout=30) as resp:
        up_res = json.loads(resp.read().decode("utf-8"))

    # 3. photos.saveWallPhoto
    save_url = "https://api.vk.com/method/photos.saveWallPhoto"
    save_params = {
        "access_token": user_token,
        "v": config.VK_API_VERSION,
        "group_id": config.VK_GROUP_ID,
        "photo": up_res.get("photo"),
        "server": up_res.get("server"),
        "hash": up_res.get("hash")
    }
    save_data = urllib.parse.urlencode(save_params).encode("utf-8")
    save_req = urllib.request.Request(save_url, data=save_data)
    with urllib.request.urlopen(save_req, timeout=15) as resp:
        saved = json.loads(resp.read().decode("utf-8"))
        if "response" in saved and saved["response"]:
            item = saved["response"][0]
            att = f"photo{item['owner_id']}_{item['id']}"
            return att
        print(f"[Upload Error] saveWallPhoto: {saved}", file=sys.stderr)
        return None

if __name__ == "__main__":
    if len(sys.argv) > 1:
        p = sys.argv[1]
        print(upload_photo_to_wall(p))
