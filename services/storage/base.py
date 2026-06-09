from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class StorageBackend(ABC):
    """抽象存储后端基类"""

    @abstractmethod
    def load_accounts(self) -> list[dict[str, Any]]:
        """加载所有账号数据"""
        pass

    @abstractmethod
    def save_accounts(self, accounts: list[dict[str, Any]]) -> None:
        """保存所有账号数据"""
        pass

    def upsert_account(self, account: dict[str, Any]) -> None:
        """增量写入单个账号（按 access_token upsert）。

        默认实现退化为「全量读改写」，子类（如数据库后端）应覆写为单行写入以避免
        在大号池下每改一个账号都重写整张表/整个文件。
        """
        access_token = str(account.get("access_token") or "").strip()
        if not access_token:
            return
        accounts = self.load_accounts()
        replaced = False
        for index, item in enumerate(accounts):
            if str(item.get("access_token") or "").strip() == access_token:
                accounts[index] = account
                replaced = True
                break
        if not replaced:
            accounts.append(account)
        self.save_accounts(accounts)

    def delete_account(self, access_token: str) -> None:
        """增量删除单个账号。默认实现退化为全量读改写，子类应覆写为单行删除。"""
        access_token = str(access_token or "").strip()
        if not access_token:
            return
        accounts = [
            item
            for item in self.load_accounts()
            if str(item.get("access_token") or "").strip() != access_token
        ]
        self.save_accounts(accounts)

    @abstractmethod
    def load_auth_keys(self) -> list[dict[str, Any]]:
        """加载所有鉴权密钥数据"""
        pass

    @abstractmethod
    def save_auth_keys(self, auth_keys: list[dict[str, Any]]) -> None:
        """保存所有鉴权密钥数据"""
        pass

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """健康检查，返回存储后端状态"""
        pass

    @abstractmethod
    def get_backend_info(self) -> dict[str, Any]:
        """获取存储后端信息"""
        pass
