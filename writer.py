import asyncio
import websockets
from fastapi import FastAPI, Request
import uvicorn
import threading
import httpx
import os
from dotenv import load_dotenv
import json
import requests

listener_client = None
listener_queue = asyncio.Queue()
ws_loop = None  

load_dotenv()

LYZR_API_URL = os.getenv("LYZR_API_URL", "https://agent-prod.studio.lyzr.ai/v3/inference/chat/")
LYZR_API_KEY = os.getenv("LYZR_API_KEY")
USER_ID = os.getenv("USER_ID")
AGENT_ID = os.getenv("AGENT_ID")
SESSION_ID = os.getenv("SESSION_ID")

app = FastAPI()

async def forward_to_lyzr(message: str) -> str:
    payload = {
        "user_id": USER_ID,
        "agent_id": AGENT_ID,
        "session_id": SESSION_ID,
        "message": message
    }
    headers = {
        "Content-Type": "application/json",
        "x-api-key": LYZR_API_KEY
    }
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.post(LYZR_API_URL, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        return data.get("response", "No response from LyZR")

def get_all_pull_requests(owner, repo, state="open", token=None):
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    headers = {}
    if token:
        headers["Authorization"] = f"token {token}"
    all_prs = []
    page = 1
    while True:
        params = {"state": state, "per_page": 100, "page": page}
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        prs = response.json()
        if not prs:
            break
        all_prs.extend(prs)
        page += 1
    return all_prs

async def process_prs_and_forward(listener_ws, prs):
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for pr in prs:
            try:
                patch_url = pr.get("patch_url")
                if not patch_url:
                    raise ValueError("PR has no patch_url")
                patch_response = await client.get(patch_url)
                patch_response.raise_for_status()
                patch_content = patch_response.text
                response_text = await forward_to_lyzr(patch_content)
                payload = {
                    "pr_number": pr['number'],
                    "pr_title": pr['title'],
                    "lyzr_response": response_text
                }
                await listener_ws.send(json.dumps(payload))
            except Exception as e:
                error_payload = {
                    "pr_number": pr['number'],
                    "error": str(e)
                }
                if listener_ws:
                    try:
                        await listener_ws.send(json.dumps(error_payload))
                    except websockets.ConnectionClosed:
                        listener_client = None

async def listener_sender():
    global listener_client
    while True:
        message = await listener_queue.get()
        if listener_client:
            try:
                await listener_client.send(message)
            except websockets.ConnectionClosed:
                listener_client = None

async def ws_handler(websocket):
    global listener_client
    try:
        async for message in websocket:
            if message == "__register_streamlit__":
                listener_client = websocket
                try:
                    pr_data = get_all_pull_requests(owner="DhruvVayugundla", repo="testing")
                    asyncio.create_task(process_prs_and_forward(listener_client, pr_data))
                except Exception as e:
                    await listener_client.send(json.dumps({"error": str(e)}))
                continue
            if websocket == listener_client:
                print(f"Reply from listener: {message}")
            else:
                await listener_queue.put(message)
    except websockets.ConnectionClosed:
        if websocket == listener_client:
            listener_client = None

@app.post("/webhook")
async def webhook(request: Request):
    body = await request.json()
    pull_requests = body.get("pull_request")
    if not pull_requests or "patch_url" not in pull_requests:
        return {"status": "error", "message": "Missing 'pull_requests.patch_url' field"}
    patch_url = pull_requests["patch_url"]
    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            response = await client.get(patch_url)
            response.raise_for_status()
            patch_content = response.text
        except httpx.RequestError as e:
            return {"status": "error", "message": f"Failed to fetch patch_url: {str(e)}"}
        except httpx.HTTPStatusError as e:
            return {"status": "error", "message": f"HTTP error fetching patch_url: {str(e)}"}
    if ws_loop:
        pr = pull_requests
        pr_info = {
            "user_login": pr["user"]["login"],
            "user_id": pr["user"]["id"],
            "title": pr["title"],
            "number": body["number"],
            "action": body["action"]
        }
        lyzr_response = await forward_to_lyzr(patch_content)
        combined_response = {
            "pull_request": pr_info,
            "lyzr_response": lyzr_response
        }
        ws_loop.call_soon_threadsafe(listener_queue.put_nowait, str(combined_response))
        return {"status": "sent", "message": combined_response}
    return {"status": "error", "message": "WebSocket loop not ready"}

async def main():
    global ws_loop
    ws_loop = asyncio.get_running_loop()
    server = await websockets.serve(ws_handler, "localhost", 8765)
    asyncio.create_task(listener_sender())
    await server.wait_closed()

def start_api():
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    threading.Thread(target=start_api, daemon=True).start()
    asyncio.run(main())
