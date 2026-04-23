from dataclasses import dataclass, field
from typing import Optional


@dataclass
class User:
    id: str
    name: str
    real_name: Optional[str] = None


@dataclass
class Channel:
    id: str
    name: str
    is_private: bool = False


@dataclass
class File:
    id: str
    message_ts: str
    url: Optional[str] = None
    local_path: Optional[str] = None
    size_bytes: Optional[int] = None


@dataclass
class Message:
    ts: str
    user: Optional[str] = None
    text: Optional[str] = None
    thread_ts: Optional[str] = None
    files: list[File] = field(default_factory=list)
