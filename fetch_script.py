import os
import re
import time
from pathlib import Path

import browser_cookie3
import requests

# ================= 配置区 =================
# 1. 想要下载的活动 URL (直接从浏览器地址栏复制)
TARGET_URL = "https://lms.xjtu.edu.cn/course/{class_number}/learning-activity#/{activity_id}"

# 2. 本地存储文件夹
SAVE_DIR = "./lms_downloads"
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30
DOWNLOAD_CHUNK_SIZE = 64 * 1024
PROGRESS_INTERVAL_SECONDS = 1.0
# ==========================================

def iter_firefox_cookie_files():
    """Return all readable Firefox cookie databases under the current user."""
    firefox_dir = Path.home() / ".mozilla" / "firefox"
    if not firefox_dir.exists():
        return

    for profile_dir in sorted(firefox_dir.glob("*.default*")):
        cookie_file = profile_dir / "cookies.sqlite"
        if cookie_file.exists():
            yield cookie_file


def get_universal_cookies():
    """Try current user's common browsers until valid xjtu.edu.cn cookies are found."""
    browser_attempts = []

    for cookie_file in iter_firefox_cookie_files() or []:
        browser_attempts.append((
            f"firefox:{cookie_file.parent.name}",
            lambda cookie_file=cookie_file: browser_cookie3.firefox(
                cookie_file=str(cookie_file),
                domain_name="xjtu.edu.cn",
            ),
        ))

    browser_attempts.extend([
        ("chrome", lambda: browser_cookie3.chrome(domain_name="xjtu.edu.cn")),
        ("chromium", lambda: browser_cookie3.chromium(domain_name="xjtu.edu.cn")),
        ("edge", lambda: browser_cookie3.edge(domain_name="xjtu.edu.cn")),
        ("opera", lambda: browser_cookie3.opera(domain_name="xjtu.edu.cn")),
    ])

    errors = []
    for browser_name, loader in browser_attempts:
        try:
            cj = loader()
            cookies = list(cj)
            if cookies:
                print(f"[+] 已从 {browser_name} 加载 {len(cookies)} 条 xjtu.edu.cn Cookie")
                return cj
            errors.append(f"{browser_name}: 未找到 xjtu.edu.cn Cookie")
        except Exception as e:
            errors.append(f"{browser_name}: {e}")

    print("[-] 读取浏览器 Cookie 失败，未找到可用的 LMS 登录态。")
    print("    请确认你已在浏览器中登录 LMS，必要时关闭浏览器后重试。")
    if errors:
        print("    已尝试的浏览器/配置：")
        for item in errors:
            print(f"    - {item}")
    return None

def sanitize_filename(filename):
    """清理文件名中的非法字符"""
    return re.sub(r'[\\/:*?"<>|]', '_', filename)


def format_bytes(num_bytes):
    units = ["B", "KB", "MB", "GB"]
    value = float(num_bytes)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f}{unit}"
        value /= 1024


def download_file(url, file_path, cookies, headers):
    temp_path = f"{file_path}.part"
    last_report_time = time.time()
    downloaded = 0

    with requests.get(
        url,
        cookies=cookies,
        headers=headers,
        stream=True,
        timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
    ) as response:
        print(f"[*] 下载响应: {response.status_code} {response.headers.get('Content-Type', '')}")
        if response.status_code != 200:
            print(f"[-] 下载失败，直链响应码: {response.status_code}")
            return False

        total_bytes = int(response.headers.get("Content-Length", "0") or 0)
        if total_bytes:
            print(f"[*] 文件大小: {format_bytes(total_bytes)}")
        else:
            print("[*] 文件大小未知，开始流式下载...")

        try:
            with open(temp_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                    if not chunk:
                        continue

                    f.write(chunk)
                    downloaded += len(chunk)

                    now = time.time()
                    if now - last_report_time >= PROGRESS_INTERVAL_SECONDS:
                        if total_bytes:
                            percent = downloaded / total_bytes * 100
                            print(
                                f"[*] 已下载 {format_bytes(downloaded)} / {format_bytes(total_bytes)} "
                                f"({percent:.1f}%)"
                            )
                        else:
                            print(f"[*] 已下载 {format_bytes(downloaded)}")
                        last_report_time = now
        except KeyboardInterrupt:
            print("\n[-] 用户中断下载，保留临时文件以便手动处理。")
            raise
        except requests.exceptions.ReadTimeout:
            print("[-] 下载超时，源站响应过慢。可以稍后重试。")
            return False

    os.replace(temp_path, file_path)
    print(f"[√] 成功保存至: {file_path}")
    return True

def download_xjtu_file():
    # 1. 自动解析 ID
    match = re.search(r'course/(\d+)/.*#/(\d+)', TARGET_URL)
    if not match:
        print("[-] 无法解析 URL，请确保 URL 格式正确（包含 course/ID 和 #/ID）")
        return
    
    course_id, activity_id = match.groups()
    base_url = "https://lms.xjtu.edu.cn"
    
    # 2. 获取 Cookie
    cookies = get_universal_cookies()
    if not cookies:
        return

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": TARGET_URL
    }

    if not os.path.exists(SAVE_DIR):
        os.makedirs(SAVE_DIR)

    try:
        # 步骤 A：获取活动元数据
        print(f"[*] 正在连接活动接口: {activity_id}...")
        api_url = f"{base_url}/api/activities/{activity_id}"
        resp = requests.get(
            api_url,
            cookies=cookies,
            headers=headers,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )

        print(f"[*] 活动接口响应: {resp.status_code} {resp.headers.get('Content-Type', '')}")
        if resp.status_code != 200:
            print(f"[-] 访问失败，状态码: {resp.status_code}。请确认是否已在浏览器登录。")
            return

        try:
            data = resp.json()
        except ValueError:
            print("[-] 活动接口未返回 JSON，可能拿到的是登录页或鉴权失败页面。")
            print(resp.text[:300])
            return

        uploads = data.get("uploads", []) or data.get("data", {}).get("uploads", [])
        
        if not uploads:
            print("[-] 该活动中没有发现可下载的文件资源。")
            return

        # 步骤 B：循环处理文件
        for file_info in uploads:
            file_id = file_info['id']
            raw_name = file_info.get('name', 'unknown_file.pdf')
            file_name = sanitize_filename(raw_name)
            
            print(f"[*] 发现资源: {file_name}，正在解析下载直链...")
            
            # 步骤 C：通过预览接口换取媒体直链
            preview_api = f"{base_url}/api/uploads/{file_id}/preview"
            prev_resp = requests.get(
                preview_api,
                cookies=cookies,
                headers=headers,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            )

            print(f"[*] 预览接口响应: {prev_resp.status_code} {prev_resp.headers.get('Content-Type', '')}")
            real_url = None
            if prev_resp.status_code == 200:
                try:
                    preview_data = prev_resp.json()
                    real_url = (
                        preview_data.get("url")
                        or preview_data.get("link")
                        or preview_data.get("redirect_url")
                    )
                except ValueError:
                    print("[-] 预览接口未返回 JSON，跳过直链解析。")
            
            # 如果预览接口没给 URL，尝试备选下载接口
            if not real_url:
                real_url = f"{base_url}/api/attachments/{file_info.get('reference_id')}/download"
                print(f"[*] 预览接口未提供直链，尝试备选接口: {real_url}")

            # 步骤 D：执行二进制流下载
            print(f"[+] 正在下载...")
            file_path = os.path.join(SAVE_DIR, file_name)
            download_file(real_url, file_path, cookies, headers)

    except Exception as e:
        print(f"[X] 运行出错: {e}")

if __name__ == "__main__":
    download_xjtu_file()
