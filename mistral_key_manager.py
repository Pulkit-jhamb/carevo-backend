import os
import time
import threading
import requests

ROTATION_INTERVAL = 600  # 10 minutes in seconds
HEALTH_CHECK_URL = "https://api.mistral.ai/v1/health"  # Replace with actual health endpoint if different

class MistralKeyManager:
    def __init__(self):
        self.keys = []
        self.key_stats = {}  # {key: {"last_checked": ..., "healthy": ..., "avg_response": ...}}
        self.current_index = 0
        self.last_rotation = time.time()
        self.lock = threading.Lock()
        self.load_keys()
        self.health_check_all_keys()
        self.rotation_thread = threading.Thread(target=self.rotate_keys_loop, daemon=True)
        self.rotation_thread.start()

    def load_keys(self):
        keys_str = os.getenv("MISTRAL_API_KEYS", "")
        self.keys = [k.strip() for k in keys_str.split(",") if k.strip()]
        for k in self.keys:
            if k not in self.key_stats:
                self.key_stats[k] = {"last_checked": 0, "healthy": True, "avg_response": None}

    def health_check_key(self, key):
        try:
            start = time.time()
            headers = {"Authorization": f"Bearer {key}"}
            resp = requests.get(HEALTH_CHECK_URL, headers=headers, timeout=5)
            healthy = resp.status_code == 200
            elapsed = time.time() - start
        except Exception:
            healthy = False
            elapsed = None
        self.key_stats[key]["last_checked"] = time.time()
        self.key_stats[key]["healthy"] = healthy
        if healthy and elapsed is not None:
            prev = self.key_stats[key]["avg_response"]
            self.key_stats[key]["avg_response"] = (
                elapsed if prev is None else (prev + elapsed) / 2
            )
        return healthy

    def health_check_all_keys(self):
        self.load_keys()
        for k in self.keys:
            self.health_check_key(k)

    def get_next_working_key(self):
        self.load_keys()
        sorted_keys = sorted(
            [k for k in self.keys if self.key_stats[k]["healthy"]],
            key=lambda k: self.key_stats[k]["avg_response"] or float("inf")
        )
        return sorted_keys[0] if sorted_keys else None

    def rotate_keys_loop(self):
        while True:
            time.sleep(5)
            self.load_keys()
            now = time.time()
            if now - self.last_rotation > ROTATION_INTERVAL:
                self.last_rotation = now
                self.current_index = (self.current_index + 1) % len(self.keys)
            # Health check current key
            current_key = self.keys[self.current_index] if self.keys else None
            if current_key and not self.health_check_key(current_key):
                # Switch to next healthy key
                next_key = self.get_next_working_key()
                if next_key:
                    self.current_index = self.keys.index(next_key)

    def get_active_key(self):
        self.load_keys()
        if not self.keys:
            return None
        current_key = self.keys[self.current_index]
        if not self.key_stats[current_key]["healthy"]:
            next_key = self.get_next_working_key()
            if next_key:
                self.current_index = self.keys.index(next_key)
                current_key = next_key
        return current_key

# Singleton instance
mistral_key_manager = MistralKeyManager()

def get_active_mistral_key():
    return mistral_key_manager.get_active_key()