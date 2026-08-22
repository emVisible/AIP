"""apa-core: Credential Vault（设计文档 §12.1 第三层 / §13.1 apa-vault）。

凭据加密存储、会话绑定、TTL 过期。C4 不变量：凭据只存在于 Vault 与
Executor 内存，绝不进入 AIP 消息 payload。

加密方案（纯标准库，POC 级）：
    KDF     hashlib.scrypt（OpenSSL 实现）→ 64B = enc_key(32) || mac_key(32)
    加密    HMAC-SHA256 计数器模式 keystream XOR 明文
    完整性  encrypt-then-MAC：tag = HMAC(mac_key, nonce || ct)
生产部署建议：换用 FernetBackend（pip install cryptography，接口不变）
或对接 HashiCorp Vault / 云 KMS（§13.1）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class VaultError(RuntimeError):
    pass


# --- 原语 -----------------------------------------------------------------------
def _derive_keys(master: bytes, salt: bytes) -> tuple:
    dk = hashlib.scrypt(master, salt=salt, n=2 ** 14, r=8, p=1, dklen=64,
                        maxmem=64 * 1024 * 1024)
    return dk[:32], dk[32:]  # enc_key, mac_key


def _keystream(enc_key: bytes, nonce: bytes, length: int) -> bytes:
    out = b""
    counter = 0
    while len(out) < length:
        out += hmac.new(enc_key, nonce + counter.to_bytes(8, "big"),
                        hashlib.sha256).digest()
        counter += 1
    return out[:length]


def _encrypt(master: bytes, salt: bytes, plaintext: bytes) -> dict:
    enc_key, mac_key = _derive_keys(master, salt)
    nonce = os.urandom(16)
    ct = bytes(a ^ b for a, b in zip(plaintext, _keystream(enc_key, nonce, len(plaintext))))
    tag = hmac.new(mac_key, nonce + ct, hashlib.sha256).digest()
    return {"nonce": nonce, "ct": ct, "tag": tag}


def _decrypt(master: bytes, salt: bytes, nonce: bytes, ct: bytes, tag: bytes) -> bytes:
    enc_key, mac_key = _derive_keys(master, salt)
    expect = hmac.new(mac_key, nonce + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(expect, tag):
        raise VaultError("integrity check failed (wrong key or tampered data)")
    return bytes(a ^ b for a, b in zip(ct, _keystream(enc_key, nonce, len(ct))))


# --- 后端 ------------------------------------------------------------------------
class VaultBackend:
    def put(self, name: str, secret: str, *, ttl_ms: Optional[int] = None) -> None:
        raise NotImplementedError

    def get(self, name: str) -> Optional[str]:
        """过期或不存在返回 None。"""
        raise NotImplementedError

    def delete(self, name: str) -> bool:
        raise NotImplementedError

    def list_names(self) -> List[str]:
        raise NotImplementedError


class EncryptedFileVault(VaultBackend):
    """单文件加密存储。master key 来源：参数 > APA_VAULT_KEY 环境变量 >
    自动生成并落盘 <path>.key（0600，开发便利；生产应使用外部密钥）。"""

    MAGIC_VERSION = 1

    def __init__(self, path: str | Path, master_key: Optional[bytes] = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if master_key is None:
            env = os.environ.get("APA_VAULT_KEY")
            master_key = env.encode() if env else None
        key_file = self.path.with_suffix(self.path.suffix + ".key")
        if master_key is None:
            if key_file.exists():
                master_key = key_file.read_bytes().strip()
            else:
                master_key = base64.urlsafe_b64encode(os.urandom(32))
                key_file.write_bytes(master_key)
                os.chmod(key_file, 0o600)
        self._master = master_key
        self._salt = self._load_salt(key_file)
        self._data: Dict[str, dict] = {}
        self._load()

    def _load_salt(self, key_file: Path) -> bytes:
        salt_file = self.path.with_suffix(self.path.suffix + ".salt")
        if salt_file.exists():
            return salt_file.read_bytes()
        salt = os.urandom(16)
        salt_file.write_bytes(salt)
        os.chmod(salt_file, 0o600)
        return salt

    def _load(self) -> None:
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if raw.get("version") != self.MAGIC_VERSION:
            raise VaultError(f"unsupported vault version {raw.get('version')}")
        self._data = raw.get("entries", {})

    def _save(self) -> None:
        blob = {"version": self.MAGIC_VERSION, "entries": self._data}
        self.path.write_text(json.dumps(blob, indent=1), encoding="utf-8")
        os.chmod(self.path, 0o600)

    @staticmethod
    def _expired(entry: dict) -> bool:
        exp = entry.get("expires_ms")
        return exp is not None and time.time() * 1000 > exp

    # -- 接口 --
    def put(self, name: str, secret: str, *, ttl_ms: Optional[int] = None) -> None:
        box = _encrypt(self._master, self._salt, secret.encode())
        expires = time.time() * 1000 + ttl_ms if ttl_ms else None
        self._data[name] = {
            "nonce": base64.b64encode(box["nonce"]).decode(),
            "ct": base64.b64encode(box["ct"]).decode(),
            "tag": base64.b64encode(box["tag"]).decode(),
            "created_ms": int(time.time() * 1000),
            "expires_ms": int(expires) if expires else None,
        }
        self._save()

    def get(self, name: str) -> Optional[str]:
        entry = self._data.get(name)
        if entry is None:
            return None
        if self._expired(entry):
            self.delete(name)
            return None
        try:
            pt = _decrypt(
                self._master, self._salt,
                base64.b64decode(entry["nonce"]),
                base64.b64decode(entry["ct"]),
                base64.b64decode(entry["tag"]),
            )
        except VaultError:
            raise
        except Exception as e:  # noqa: BLE001
            raise VaultError(f"corrupt entry {name!r}: {e}") from e
        return pt.decode()

    def delete(self, name: str) -> bool:
        if name in self._data:
            del self._data[name]
            self._save()
            return True
        return False

    def list_names(self) -> List[str]:
        return [n for n, e in self._data.items() if not self._expired(e)]


class EnvVault(VaultBackend):
    """零持久化后端：从 APA_SECRET_<NAME> 环境变量读取。CI/容器友好。"""

    prefix = "APA_SECRET_"

    def put(self, name: str, secret: str, *, ttl_ms=None) -> None:
        raise VaultError("EnvVault is read-only")

    def get(self, name: str) -> Optional[str]:
        return os.environ.get(self.prefix + name.upper())

    def delete(self, name: str) -> bool:
        return False

    def list_names(self) -> List[str]:
        p = len(self.prefix)
        return [k[p:].lower() for k in os.environ if k.startswith(self.prefix)]


class FernetBackend(VaultBackend):
    """可选生产后端：cryptography.Fernet。安装后接口与其他后端一致。

    密钥来源：参数 > APA_VAULT_KEY 环境变量 > 自动生成并保存在
    <path>.json 的 "key" 字段（开发便利；生产用外部 KMS）。
    """

    def __init__(self, path: str | Path, master_key: Optional[bytes] = None) -> None:
        try:
            from cryptography.fernet import Fernet, InvalidToken
        except ImportError as e:  # pragma: no cover
            raise VaultError(
                "FernetBackend requires 'cryptography': pip install cryptography"
            ) from e
        self._InvalidToken = InvalidToken
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.meta_path = self.path.with_suffix(".json")
        key: Optional[bytes] = master_key or \
            (os.environ.get("APA_VAULT_KEY", "").encode() or None)
        meta: Dict[str, Any] = {}
        if self.meta_path.exists():
            meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
            key = key or str(meta.get("key", "")).encode()
        if not key:
            key = Fernet.generate_key()
        if "key" not in meta:
            meta["key"] = key.decode() if isinstance(key, bytes) else str(key)
            self.meta_path.write_text(json.dumps(meta), encoding="utf-8")
            os.chmod(self.meta_path, 0o600)
        self._fernet = Fernet(key)
        self._entries: Dict[str, dict] = dict(meta.get("entries", {}))

    def _save(self) -> None:
        meta: Dict[str, Any] = {}
        if self.meta_path.exists():
            meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
        meta["entries"] = self._entries
        self.meta_path.write_text(json.dumps(meta), encoding="utf-8")
        os.chmod(self.meta_path, 0o600)

    def put(self, name: str, secret: str, *, ttl_ms: Optional[int] = None) -> None:
        token = self._fernet.encrypt(secret.encode()).decode()
        self._entries[name] = {
            "token": token,
            "expires_ms": int(time.time() * 1000 + ttl_ms) if ttl_ms else None,
        }
        self._save()

    def get(self, name: str) -> Optional[str]:
        e = self._entries.get(name)
        if e is None:
            return None
        if e.get("expires_ms") and time.time() * 1000 > e["expires_ms"]:
            return None
        try:
            return self._fernet.decrypt(e["token"].encode()).decode()
        except self._InvalidToken as err:
            raise VaultError(f"invalid token for {name!r}") from err

    def delete(self, name: str) -> bool:
        if name in self._entries:
            del self._entries[name]
            self._save()
            return True
        return False

    def list_names(self) -> List[str]:
        return list(self._entries)


# --- 注入门面（Executor 本地注入层，C4） --------------------------------------------
class VaultManager:
    """把 auth 规格解析为请求头注入值。

    auth 规格（可安全出现在 AIP params 中——只有引用没有机密）：
        {"vault": "<name>"}   从 Vault 取
        {"env":   "<VAR>"}    从环境变量取
    """

    def __init__(self, backend: VaultBackend) -> None:
        self.backend = backend

    def resolve(self, auth_spec: Optional[dict]) -> Optional[str]:
        if not auth_spec:
            return None
        if "literal" in auth_spec:
            raise VaultError("literal secrets are forbidden by C4 — use vault/env ref")
        if "vault" in auth_spec:
            return self.backend.get(str(auth_spec["vault"]))
        if "env" in auth_spec:
            return os.environ.get(str(auth_spec["env"]))
        raise VaultError(f"unsupported auth spec keys: {sorted(auth_spec)}")

    def inject_headers(self, headers: Dict[str, str],
                       auth_spec: Optional[dict]) -> Dict[str, str]:
        token = self.resolve(auth_spec)
        if not token:
            return headers
        out = dict(headers)
        out.setdefault("Authorization", f"Bearer {token}")
        return out


def open_vault(path: Optional[str] = None, *, backend: str = "auto") -> VaultBackend:
    """便捷工厂：backend="auto" → 有 cryptography 用 Fernet，否则 EncryptedFile。"""
    if backend == "env":
        return EnvVault()
    if backend == "fernet":
        return FernetBackend(path or "data/vault.key")
    if backend == "file":
        return EncryptedFileVault(path or "data/vault.enc.json")
    try:
        import cryptography  # noqa: F401
        return FernetBackend(path or "data/vault.key")
    except VaultError:
        return EncryptedFileVault(path or "data/vault.enc.json")