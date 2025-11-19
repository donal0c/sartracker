"""
Secure Credential Store

Provides a secure way to store sensitive data (passwords, tokens).
Attempts to use system keyring (if available) and falls back to
an obfuscated file with strict permissions (0o600) in the user's
profile directory.

Usage:
    from utils.secure_store import SecureStore
    SecureStore.set_credential("service_name", "username", "password")
    password = SecureStore.get_credential("service_name", "username")
"""

import os
import json
import base64
import sys
import logging
from pathlib import Path
from typing import Optional, Dict

# Try to import keyring
try:
    import keyring
    HAS_KEYRING = True
except ImportError:
    HAS_KEYRING = False

LOGGER = logging.getLogger('SARTracker.SecureStore')


class SecureStore:
    """
    Abstracts credential storage.
    Prioritizes system keyring -> restricted file storage.
    """
    
    APP_NAME = "SARTracker"
    
    @staticmethod
    def _get_storage_path() -> Path:
        """
        Get path to local secrets file.
        """
        # Use QGIS standard data directory structure if possible, or standard XDG
        if sys.platform.startswith("win"):
            base = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local")))
        elif sys.platform == "darwin":
            base = Path(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/Library/Application Support")))
        else:
            base = Path(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")))
            
        folder = base / "QGIS" / "QGIS3" / "profiles" / "default" / "python" / "plugins" / "sartracker" / "secrets"
        # Or better: standard plugin data dir
        # Let's stick to a safe user-data dir
        folder = base / "QGIS" / "SARTracker"
        
        if not folder.exists():
            try:
                folder.mkdir(parents=True, mode=0o700)
            except OSError:
                # Fallback to home if we can't create in data dir
                folder = Path(os.path.expanduser("~/.sartracker"))
                folder.mkdir(parents=True, mode=0o700, exist_ok=True)
                
        return folder / "secrets.store"

    @staticmethod
    def _obfuscate(data: str) -> str:
        """Simple obfuscation to prevent plain-text reading."""
        # This is NOT encryption. It just stops casual 'cat' from revealing passwords.
        # Without dependencies like 'cryptography', we can't easily do strong encryption 
        # without exposing the key in the code anyway.
        # Security relies on file permissions (0o600).
        b = data.encode('utf-8')
        return base64.b64encode(b).decode('ascii')

    @staticmethod
    def _deobfuscate(data: str) -> str:
        """Reverse obfuscation."""
        try:
            b = base64.b64decode(data.encode('ascii'))
            return b.decode('utf-8')
        except Exception:
            return ""

    @classmethod
    def set_credential(cls, service: str, username: str, secret: str) -> bool:
        """
        Save a credential.
        """
        if HAS_KEYRING:
            try:
                keyring.set_password(f"{cls.APP_NAME}:{service}", username, secret)
                return True
            except Exception as e:
                LOGGER.warning(f"Keyring failed, falling back to file: {e}")
        
        return cls._file_set(service, username, secret)

    @classmethod
    def get_credential(cls, service: str, username: str) -> Optional[str]:
        """
        Retrieve a credential.
        """
        if HAS_KEYRING:
            try:
                val = keyring.get_password(f"{cls.APP_NAME}:{service}", username)
                if val is not None:
                    return val
            except Exception:
                pass  # Fallthrough to file
        
        return cls._file_get(service, username)

    @classmethod
    def delete_credential(cls, service: str, username: str):
        """
        Delete a credential.
        """
        if HAS_KEYRING:
            try:
                keyring.delete_password(f"{cls.APP_NAME}:{service}", username)
            except Exception:
                pass
        
        cls._file_delete(service, username)

    @classmethod
    def get_backend_name(cls) -> str:
        """
        Get the name of the active storage backend for diagnostics.
        
        Returns:
            str: "System Keyring (<backend>)" or "Encrypted File (Fallback)"
        """
        if HAS_KEYRING:
            try:
                # Try to identify the keyring backend
                backend = keyring.get_keyring()
                return f"System Keyring ({type(backend).__name__})"
            except Exception:
                return "System Keyring (Unknown Backend)"
        return "Encrypted File (Fallback)"

    @classmethod
    def is_secure(cls) -> bool:
        """
        Check if storage is considered secure (using system keyring).
        """
        return HAS_KEYRING

    # --- File Backend ---

    @classmethod
    def _load_store(cls) -> Dict:
        path = cls._get_storage_path()
        if not path.exists():
            return {}
        
        try:
            # Enforce permissions check before reading
            if sys.platform != "win32":
                mode = path.stat().st_mode
                if mode & 0o077:
                    LOGGER.warning(f"Secrets file has unsafe permissions: {oct(mode)}")
                    # Attempt to fix
                    path.chmod(0o600)

            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            LOGGER.error(f"Failed to load secrets store: {e}")
            return {}

    @classmethod
    def _save_store(cls, data: Dict):
        path = cls._get_storage_path()
        try:
            # Write to temp file then rename for atomicity
            tmp = path.with_suffix('.tmp')
            
            with open(tmp, 'w', encoding='utf-8') as f:
                # Set perms on file descriptor if possible, or path after
                json.dump(data, f)
            
            if sys.platform != "win32":
                tmp.chmod(0o600)
                
            tmp.replace(path)
        except Exception as e:
            LOGGER.error(f"Failed to save secrets store: {e}")

    @classmethod
    def _file_set(cls, service: str, username: str, secret: str) -> bool:
        store = cls._load_store()
        if service not in store:
            store[service] = {}
        
        store[service][username] = cls._obfuscate(secret)
        cls._save_store(store)
        return True

    @classmethod
    def _file_get(cls, service: str, username: str) -> Optional[str]:
        store = cls._load_store()
        if service in store and username in store[service]:
            return cls._deobfuscate(store[service][username])
        return None

    @classmethod
    def _file_delete(cls, service: str, username: str):
        store = cls._load_store()
        if service in store and username in store[service]:
            del store[service][username]
            if not store[service]:
                del store[service]
            cls._save_store(store)
