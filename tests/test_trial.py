import pytest
import json

def test_hook_deploy(direct_vm, direct_deploy, direct_alice):
    def gl_call_hook(vm, request):
        if "CallContract" in request:
            cc = request["CallContract"]
            calldata_obj = cc.get("calldata", {})
            method = calldata_obj.get("method")
            args = calldata_obj.get("args", [])
            if method == "get_market":
                market_id = args[0] if args else "1"
                market_data = {
                    "market_id": market_id,
                    "question": "Test Market",
                    "status": "OPEN",
                    "phase": "OPEN_WINDOW",
                    "refundable": False,
                    "can_claim": False
                }
                from genlayer.py import calldata
                return bytes([0]) + calldata.encode(json.dumps(market_data))
        return None

    direct_vm._gl_call_hook = gl_call_hook
    direct_vm.sender = direct_alice

    contract = direct_deploy(
        "contracts/prophet_volatility_hook.py",
        "0x31C53838fF49168128D772625e34d3D2F7e11116",
        1000000000000000,
        1000000000000000000,
        60,
        86400
    )

    config = contract.get_hook_config()
    assert config["min_collateral_wei"] == 1000000000000000
    assert config["total_positions_count"] == 0
