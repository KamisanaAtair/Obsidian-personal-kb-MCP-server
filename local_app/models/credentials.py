"""System credential storage; there is deliberately no plaintext fallback."""

# Credential backends can raise platform-specific exceptions containing secrets.
# This trust boundary deliberately translates every backend failure without text.
# ruff: noqa: BLE001

from .errors import ModelError


class SystemCredentialStore:
    def __init__(self, namespace: str):
        self.namespace = namespace

    def _backend(self):
        try:
            import keyring

            backend = keyring.get_keyring()
            # Do not silently accept third-party plaintext or null backends.
            if type(backend).__module__ not in {
                "keyring.backends.macOS",
                "keyring.backends.Windows",
                "keyring.backends.SecretService",
                "keyring.backends.libsecret",
            }:
                raise RuntimeError("Unsupported credential backend")
            return backend
        except Exception:
            raise ModelError(
                "credential_store_unavailable", "系统凭据库不可用，请先解锁或配置系统凭据库。"
            ) from None

    def get(self, reference: str) -> str | None:
        try:
            return self._backend().get_password(self.namespace, reference)
        except ModelError:
            raise
        except Exception:
            raise ModelError(
                "credential_store_unavailable", "无法读取系统凭据库，请检查系统授权。"
            ) from None

    def set(self, reference: str, value: str) -> None:
        try:
            self._backend().set_password(self.namespace, reference, value)
        except ModelError:
            raise
        except Exception:
            raise ModelError(
                "credential_store_unavailable", "无法保存到系统凭据库，配置尚未保存。"
            ) from None

    def delete(self, reference: str) -> None:
        try:
            backend = self._backend()
            if backend.get_password(self.namespace, reference) is not None:
                backend.delete_password(self.namespace, reference)
        except ModelError:
            raise
        except Exception:
            raise ModelError(
                "credential_store_unavailable", "无法删除系统凭据，请检查系统授权后重试。"
            ) from None


class MemoryCredentialStore:
    """Explicitly injected, ephemeral store for tests; never selected at runtime."""

    def __init__(self):
        self._values = {}

    def get(self, reference):
        return self._values.get(reference)

    def set(self, reference, value):
        self._values[reference] = value

    def delete(self, reference):
        self._values.pop(reference, None)
