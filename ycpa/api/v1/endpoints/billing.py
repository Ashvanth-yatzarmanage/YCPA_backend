import hashlib
import hmac
import logging

from fastapi import APIRouter, status

from ycpa.core.auth.dependencies import CurrentUser
from ycpa.core.config import get_settings
from ycpa.core.database.dependencies import DatabaseSession
from ycpa.core.exceptions import BadRequestException
from ycpa.core.schemas.responses import SuccessResponse
from ycpa.schemas.requests.billing import CreateOrderRequest, VerifyPaymentRequest
from ycpa.schemas.responses.billing import CreateOrderResponse, VerifyPaymentResponse
from ycpa.services.billing import BillingService

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/billing", tags=["Billing"])



@router.post(
    "/create-order",
    response_model=SuccessResponse[CreateOrderResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a Razorpay order for a subscription upgrade",
)
async def create_order(
    body: CreateOrderRequest,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[CreateOrderResponse]:
    service = BillingService(session)
    data = await service.create_order(
        user=current_user,
        product_type=body.product_type,
        plan=body.plan,
        billing_period=body.billing_period,
    )
    return SuccessResponse(
        success=True,
        message="Order created.",
        data=CreateOrderResponse(**data),
    )



@router.post(
    "/verify-payment",
    response_model=SuccessResponse[VerifyPaymentResponse],
    status_code=status.HTTP_200_OK,
    summary="Verify Razorpay signature and upgrade subscription",
)
async def verify_payment(
    body: VerifyPaymentRequest,
    current_user: CurrentUser,
    session: DatabaseSession,
) -> SuccessResponse[VerifyPaymentResponse]:
    key_secret = settings.RAZORPAY_KEY_SECRET.get_secret_value()
    expected = hmac.new(
        key_secret.encode(),
        f"{body.razorpay_order_id}|{body.razorpay_payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, body.razorpay_signature):
        logger.warning(
            "Razorpay signature mismatch",
            extra={"user_id": str(current_user.id), "order_id": body.razorpay_order_id},
        )
        raise BadRequestException("Payment verification failed. Invalid signature.")

    service = BillingService(session)
    data = await service.upgrade_subscription(
        user=current_user,
        razorpay_payment_id=body.razorpay_payment_id,
        razorpay_order_id=body.razorpay_order_id,
    )
    return SuccessResponse(
        success=True,
        message=f"Upgraded to {data['plan']} successfully.",
        data=VerifyPaymentResponse(**data),
    )