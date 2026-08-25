"""Developer Test Mode Checkout route for manual payment testing."""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from retrypay.config import Settings, get_settings

router = APIRouter(tags=["checkout"])


@router.get("/checkout", response_class=HTMLResponse)
async def dev_checkout_page(
    order_id: str = Query(..., description="Razorpay Order ID"),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    """Render developer-owned Razorpay Test Mode checkout page."""
    key_id = settings.RAZORPAY_KEY_ID or ""

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ReTryPay — Test Mode Checkout</title>
    <style>
        body {{
            font-family: system-ui, -apple-system, sans-serif;
            background: #0f172a;
            color: #f8fafc;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            margin: 0;
        }}
        .card {{
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 12px;
            padding: 32px;
            max-width: 440px;
            width: 100%;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
            text-align: center;
        }}
        h1 {{ font-size: 1.5rem; margin-bottom: 8px; color: #38bdf8; }}
        p {{ color: #94a3b8; font-size: 0.95rem; margin-bottom: 24px; }}
        .info {{
            background: #0f172a;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 24px;
            text-align: left;
            font-family: monospace;
            font-size: 0.85rem;
        }}
        .info div {{ margin-bottom: 6px; }}
        .btn {{
            background: #0284c7;
            color: white;
            border: none;
            border-radius: 8px;
            padding: 14px 28px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            width: 100%;
            transition: background 0.2s;
        }}
        .btn:hover {{ background: #0369a1; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>Razorpay Test Mode Checkout</h1>
        <p>Complete a failed payment interaction in Test Mode.</p>
        <div class="info">
            <div><strong>Order ID:</strong> {order_id}</div>
            <div><strong>Key ID:</strong> {key_id[:8]}****</div>
            <div><strong>Mode:</strong> Test Mode Only</div>
        </div>
        <button id="rzp-button" class="btn">Pay Now (Razorpay Test Mode)</button>
    </div>
    <script src="https://checkout.razorpay.com/v1/checkout.js"></script>
    <script>
        var options = {{
            "key": "{key_id}",
            "amount": "250000",
            "currency": "INR",
            "name": "ReTryPay Test Merchant",
            "description": "Razorpay Test Mode Order",
            "order_id": "{order_id}",
            "handler": function (response) {{
                alert("Payment Captured ID: " + response.razorpay_payment_id);
            }},
            "prefill": {{
                "name": "Merchant Test User",
                "email": "merchant_test@example.com",
                "contact": "+919999999999"
            }},
            "theme": {{ "color": "#0284c7" }}
        }};
        var rzp = new Razorpay(options);
        rzp.on('payment.failed', function (response) {{
            console.log('Payment Failed:', response.error);
            alert("Payment Failed Recorded: " + (response.error.code || "FAILED"));
        }});
        document.getElementById('rzp-button').onclick = function(e) {{
            rzp.open();
            e.preventDefault();
        }};
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)
