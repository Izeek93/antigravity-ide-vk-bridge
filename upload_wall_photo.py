import os
import sys
import time
import json
import urllib.request
import urllib.parse
from typing import Optional
import requests
from PIL import Image

import config
import post_scheduler

def upload_photo_to_wall(photo_path: str, retries: int = 5) -> Optional[str]:
    """
    Надёжно загружает фотографию на стену сообщества через User Token (photos scope)
    с автоматической нормализацией через PIL и retry-циклом до 5 попыток.
    Возвращает строку вложения вида photo{owner_id}_{id}.
    """
    user_token = post_scheduler._load_user_token()
    if not user_token:
        print("[Upload Error] No user token found", file=sys.stderr)
        return None

    # Нормализуем картинку в чистый RGB JPEG перед отправкой
    norm_path = photo_path
    try:
        im = Image.open(photo_path)
        if im.mode != "RGB":
            im = im.convert("RGB")
        norm_path = photo_path + ".wall_norm.jpg"
        im.save(norm_path, "JPEG", quality=95)
    except Exception as e:
        norm_path = photo_path

    last_err = None
    for attempt in range(1, retries + 1):
        try:
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
                    raise RuntimeError(f"getWallUploadServer error: {res}")
                upload_url = res["response"]["upload_url"]

            # 2. Upload file via requests
            with open(norm_path, "rb") as f:
                up_res = requests.post(
                    upload_url,
                    files={"photo": ("photo.jpg", f, "image/jpeg")},
                    timeout=30
                ).json()

            photo_val = up_res.get("photo")
            if not photo_val or photo_val in ("", "[]"):
                raise ValueError(f"VK Upload Server returned empty photo field: {up_res}")

            # 3. photos.saveWallPhoto
            save_url = "https://api.vk.com/method/photos.saveWallPhoto"
            save_params = {
                "access_token": user_token,
                "v": config.VK_API_VERSION,
                "group_id": config.VK_GROUP_ID,
                "photo": photo_val,
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
                raise RuntimeError(f"saveWallPhoto error: {saved}")

        except Exception as e:
            last_err = e
            print(f"[Upload Attempt {attempt}/{retries} Failed] {e}", file=sys.stderr)
            time.sleep(1.5 * attempt)

    print(f"[Upload Error] Failed to upload {photo_path} to wall after {retries} attempts: {last_err}", file=sys.stderr)
    return None

if __name__ == "__main__":
    if len(sys.argv) > 1:
        p = sys.argv[1]
        print(upload_photo_to_wall(p))
