from pydantic import BaseModel


class CreateOrderResponse(BaseModel):
    order_id: str
    amount: int
    currency: str
    key_id: str
    plan: str
    product_type: str
    billing_period: str


class VerifyPaymentResponse(BaseModel):
    plan: str
    product_type: str
    billing_period: str
    max_workspaces: int
    max_projects_per_workspace: int
    max_members_per_workspace: int
    max_storage_bytes: int
    can_use_4d: bool
    can_use_5d: bool
    can_use_clash_detection: bool
    can_use_ai: bool
    can_use_facility: bool
    can_use_api: bool

