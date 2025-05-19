import json
import os
import base64
import ssl
import asyncio
import threading
import argparse
from datetime import datetime, timezone
from websockets import connect
from websockets.exceptions import ConnectionClosed

parser = argparse.ArgumentParser()
parser.add_argument("--username", required=True, help="(required) Meno")
parser.add_argument("--password", required=True, help="(required) Heslo")
parser.add_argument("--client-cert", required=True, help="(required) Cesta ku klientskému certifikátu")
parser.add_argument("--client-key", required=True, help="(required) Cesta k privátnemu kľúču")
parser.add_argument("--okte-ca", required=True, help="(required) Cesta k serverovému OKTE certifikátu")
parser.add_argument("--output-dir", default="orderbook-snapshots", help="Adresár pre ukladanie snapshotov (default: %(default)s)")
parser.add_argument("--auto-save", type=int, default=60, help="Interval pre automatické ukladanie snapshotu v sekundách (0 = vypnuté) (default: %(default)s)")
parser.add_argument("--send-request-periodically", type=int, default=None, help="Periodické posielanie požiadavky na snapshot každých X sekúnd (default: vypnuté)")
parser.add_argument("--debug", action="store_true", help="Zobrazovať debug výpisy do konzoly")
args = parser.parse_args()

ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ssl_context.load_verify_locations(cafile=args.okte_ca)
ssl_context.load_cert_chain(certfile=args.client_cert, keyfile=args.client_key)

os.makedirs(args.output_dir, exist_ok=True)

orderbook_state = {}
last_seq_no = None
ignore_changes = False
send_requested = False
exit_requested = False
save_requested = False

def input_listener():
    global send_requested, exit_requested, save_requested
    while True:
        cmd = input("Zadaj príkaz ('send', 'save' alebo 'exit'):\n").strip().lower()
        if cmd == "send":
            send_requested = True
        elif cmd == "save":
            save_requested = True
        elif cmd == "exit":
            exit_requested = True
            break
        else:
            print("Neznámy príkaz. Použi 'send', 'save' alebo 'exit'.")

def debug_log(message):
    if args.debug:
        print(f"[DEBUG] {message}")
        
def save_orderbook(data, label="snapshot"):
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"orderbook_{label}_{now}.json"
    path = os.path.join(args.output_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"Orderbook uložený do {path}")

def update_orderbook_with_change(snapshot, change):
    change_map = {(
        period["period"]["start"],
        period["period"]["end"]
    ): period for period in snapshot.get("payload", {}).get("data", [])}

    for change_period in change.get("payload", {}).get("data", []):
        key = (change_period["period"]["start"], change_period["period"]["end"])
        if key not in change_map:
            continue
        target = change_map[key]
        
        allowed_sides = {"buyChanges", "sellChanges", "statistics"}
        unexpected_keys = set(change_period.keys()) - {"period", "action"} - allowed_sides
        if unexpected_keys:
            print(f"Nespracované zmeny v change_period: {unexpected_keys}, pre aktualizáciu týchto zmien zadajte 'send'")
            debug_log(json.dumps(change, indent=2))

        if "statistics" in change_period:
            target["statistics"] = change_period["statistics"]
            
        for side in ["buyChanges", "sellChanges"]:
            if side not in change_period:
                continue
            list_name = "buyList" if side == "buyChanges" else "sellList"
            order_list = target.setdefault(list_name, [])

            for ch in change_period[side]:
                index = ch.get("index")
                action = ch.get("action")

                if action == "add":
                    if index is not None and index <= len(order_list):
                        order_list.insert(index, {
                            "price": ch.get("price"),
                            "quantity": ch.get("quantity"),
                            "ownQuantity": ch.get("ownQuantity", 0)
                        })
                elif action == "update":
                    if index is not None and index < len(order_list):
                        order_list[index].update({
                            "price": ch.get("price"),
                            "quantity": ch.get("quantity"),
                            "ownQuantity": ch.get("ownQuantity", 0)
                        })
                elif action == "remove":
                    if index is not None and index < len(order_list):
                        order_list.pop(index)

async def periodic_snapshot_saver():
    while not exit_requested:
        await asyncio.sleep(args.auto_save)
        save_orderbook(orderbook_state, label="snapshot-autosave")

async def periodic_snapshot_sender(websocket):
    global ignore_changes
    while not exit_requested:
        await asyncio.sleep(args.send_request_periodically)
        ignore_changes = True
        await websocket.send(json.dumps({"type": "orderbook-snapshot"}))
        print("Poslaný pravidelný orderbook-snapshot request")        
        
async def connect_and_listen():
    global orderbook_state, last_seq_no, ignore_changes, send_requested, save_requested
    
    WEBSOCKET_URL = "wss://isot.okte.sk:8443/api/v1/idm/ws?topics=orderbook"
    auth_token = base64.b64encode(f"{args.username}:{args.password}".encode()).decode()
    headers = {"Authorization": f"Basic {auth_token}"}

    while not exit_requested:
        try:
            async with connect(
                WEBSOCKET_URL,
                additional_headers=headers,
                ssl=ssl_context,
                ping_interval=None,
            ) as websocket:

                print("Pripojený na WebSocket")

                if args.auto_save > 0:
                    asyncio.create_task(periodic_snapshot_saver())
                if args.send_request_periodically is not None:
                    asyncio.create_task(periodic_snapshot_sender(websocket))

                while not exit_requested:
                    if send_requested:
                        await websocket.send(json.dumps({"type": "orderbook-snapshot"}))
                        print("Poslaný orderbook-snapshot request")
                        ignore_changes = True
                        send_requested = False
                    
                    if save_requested:
                        save_orderbook(orderbook_state, label="snapshot")
                        save_requested = False
                    
                    message = await websocket.recv()
                    size = len(message.encode("utf-8"))
                    data = json.loads(message)
                    msg_type = data.get("type")
                    payload = data.get("payload", {})
                    seq_no = payload.get("seqNo", "N/A")
                    time_delta = payload.get("timeDelta", "N/A")

                    if msg_type == "ping":
                        debug_log("Ping prijatý, posielam Pong")
                        await websocket.send(json.dumps({"type": "pong"}))

                    elif msg_type == "orderbook-snapshot":
                        orderbook_state = data
                        last_seq_no = payload.get("seqNo")
                        ignore_changes = False
                        debug_log(f"Snapshot seqNo: {seq_no}, Δt: {time_delta} ms, veľkosť: {size} B")

                    elif msg_type == "orderbook-change":
                        if ignore_changes:
                            debug_log(f"Zmena ignorovaná kvôli prebiehajúcemu snapshot requestu")
                            continue
                        if last_seq_no is None or seq_no != last_seq_no + 1:
                            print(f"Výpadok v seqNo (očakávané {last_seq_no + 1 if last_seq_no else '???'}, prišlo {seq_no})")
                            break
                        last_seq_no = seq_no
                        update_orderbook_with_change(orderbook_state, data)
                        debug_log(f"Zmena aplikovaná seqNo: {seq_no}, Δt: {time_delta} ms, veľkosť: {size} B")

                    else:
                        print(f"Neznáma správa typu {msg_type}, veľkosť: {size} B")
                    
        except ConnectionClosed as e:
            print(f"Spojenie bolo zatvorené: {e}. Čakám 5 sekúnd...")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"Vyskytla sa chyba: {e}, Čakám 5 sekúnd...")
            await asyncio.sleep(5)

async def main():
    input_thread = threading.Thread(target=input_listener, daemon=True)
    input_thread.start()
    await connect_and_listen()

if __name__ == "__main__":
    asyncio.run(main())
