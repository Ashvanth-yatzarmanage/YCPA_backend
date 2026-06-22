from pydantic import BaseModel, field_validator


class CreateOrderRequest(BaseModel):
    product_type: str
    plan: str
    billing_period: str

    @field_validator("product_type")
    @classmethod
    def valid_product_type(cls, v: str) -> str:
        if v not in ("pim", "aim"):
            raise ValueError("product_type must be pim or aim")
        return v

    @field_validator("plan")
    @classmethod
    def valid_plan(cls, v: str) -> str:
        if v not in ("professional", "enterprise"):
            raise ValueError("plan must be professional or enterprise")
        return v

    @field_validator("billing_period")
    @classmethod
    def valid_billing_period(cls, v: str) -> str:
        if v not in ("monthly", "yearly"):
            raise ValueError("billing_period must be monthly or yearly")
        return v


class VerifyPaymentRequest(BaseModel):
    razorpay_payment_id: str
    razorpay_order_id: str
    razorpay_signature: str
    product_type: str       # pim | aim
    plan: str               # professional | enterprise
    billing_period: str     # monthly | yearly

    @field_validator("product_type")
    @classmethod
    def valid_product_type(cls, v: str) -> str:
        if v not in ("pim", "aim"):
            raise ValueError("product_type must be pim or aim")
        return v

    @field_validator("plan")
    @classmethod
    def valid_plan(cls, v: str) -> str:
        if v not in ("professional", "enterprise"):
            raise ValueError("plan must be professional or enterprise")
        return v

    @field_validator("billing_period")
    @classmethod
    def valid_billing_period(cls, v: str) -> str:
        if v not in ("monthly", "yearly"):
            raise ValueError("billing_period must be monthly or yearly")
        return v
