import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional  # noqa: UP035

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("audit")


class AuditAction(str, Enum):
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    PASSWORD_RESET = "password_reset"

    ACCESS_DENIED = "access_denied"
    PERMISSION_GRANTED = "permission_granted"
    PERMISSION_REVOKED = "permission_revoked"

    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    DOWNLOAD = "download"
    UPLOAD = "upload"

    USER_CREATED = "user_created"
    USER_DELETED = "user_deleted"
    USER_UPDATED = "user_updated"
    ROLE_CHANGED = "role_changed"
    SETTINGS_CHANGED = "settings_changed"

    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    INVALID_TOKEN = "invalid_token"
    SQL_INJECTION_ATTEMPT = "sql_injection_attempt"
    XSS_ATTEMPT = "xss_attempt"

    FILE_SHARED = "FILE_SHARED"
    FILE_SHARE_PENDING = "FILE_SHARE_PENDING"
    FILE_VIEWED = "FILE_VIEWED"
    FILE_PUBLISHED = "FILE_PUBLISHED"
    FILE_ARCHIVED = "FILE_ARCHIVED"
    FILE_MOVED = "FILE_MOVED"
    FOLDER_CREATED = "FOLDER_CREATED"
    FOLDER_RENAMED = "FOLDER_RENAMED"
    FOLDER_DELETED = "FOLDER_DELETED"
    MEMBER_INVITED = "MEMBER_INVITED"
    MEMBER_JOINED = "MEMBER_JOINED"


class AuditLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AuditLogger:
    @staticmethod
    def log_event(
            action: AuditAction,
            user_id: str | None = None,
            resource_type: str | None = None,
            resource_id: str | None = None,
            success: bool = True,
            level: AuditLevel = AuditLevel.INFO,
            ip_address: str | None = None,
            user_agent: str | None = None,
            request_id: str | None = None,
            details: dict[str, Any] | None = None,
            metadata: dict[str, Any] | None = None
    ):
        audit_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "action": action.value,
            "user_id": user_id or "anonymous",
            "success": success,
            "level": level.value,
            "request_id": request_id,
        }

        if resource_type:
            audit_entry["resource_type"] = resource_type
        if resource_id:
            audit_entry["resource_id"] = resource_id

        if ip_address:
            audit_entry["ip_address"] = ip_address
        if user_agent:
            audit_entry["user_agent"] = user_agent

        if details:
            audit_entry["details"] = details
        if metadata:
            audit_entry["metadata"] = metadata

        log_message = (
            f"AUDIT: {action.value} | "
            f"User: {user_id or 'anonymous'} | "
            f"Resource: {resource_type}:{resource_id} | "
            f"Success: {success}"
        )

        if level == AuditLevel.CRITICAL:
            audit_logger.critical(log_message, extra=audit_entry)
        elif level == AuditLevel.WARNING:
            audit_logger.warning(log_message, extra=audit_entry)
        else:
            audit_logger.info(log_message, extra=audit_entry)

    @staticmethod
    def log_authentication(
            action: AuditAction,
            user_id: Optional[str],
            success: bool,
            ip_address: Optional[str] = None,
            details: Optional[Dict[str, Any]] = None
    ):
        level = AuditLevel.WARNING if not success else AuditLevel.INFO

        AuditLogger.log_event(
            action=action,
            user_id=user_id,
            success=success,
            level=level,
            ip_address=ip_address,
            details=details
        )

    @staticmethod
    def log_data_access(
            action: AuditAction,
            user_id: str,
            resource_type: str,
            resource_id: str,
            ip_address: str | None = None,
            request_id: str | None = None
    ):
        AuditLogger.log_event(
            action=action,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip_address,
            request_id=request_id,
            level=AuditLevel.INFO
        )

    @staticmethod
    def log_security_event(
            action: AuditAction,
            ip_address: str,
            user_id: str | None = None,
            details: dict[str, Any] | None = None,
            request_id: str | None = None
    ):
        AuditLogger.log_event(
            action=action,
            user_id=user_id,
            success=False,
            level=AuditLevel.CRITICAL,
            ip_address=ip_address,
            details=details,
            request_id=request_id
        )

    @staticmethod
    def log_admin_action(
            action: AuditAction,
            admin_user_id: str,
            resource_type: str,
            resource_id: str | None = None,
            details: dict[str, Any] | None = None,
            request_id: str | None = None
    ):
        AuditLogger.log_event(
            action=action,
            user_id=admin_user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            level=AuditLevel.WARNING,
            details=details,
            request_id=request_id
        )

