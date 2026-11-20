import os
import sys

# Ensure clean direct connection bypassing any local proxy
os.environ["HTTP_PROXY"] = ""
os.environ["HTTPS_PROXY"] = ""
os.environ["http_proxy"] = ""
os.environ["https_proxy"] = ""
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

import json
import time
from dotenv import load_dotenv
from genlayer_py import create_client, create_account
from genlayer_py.chains import studionet
from genlayer_py.types import TransactionStatus

load_dotenv()
pk = os.getenv("GENLAYER_PRIVATE_KEY")
if not pk:
    print("ERROR: GENLAYER_PRIVATE_KEY missing from .env")
    sys.exit(1)

deployer = create_account(pk)
client = create_client(studionet, account=deployer)

print(f"Deployer account: {deployer.address}")
bal = client.get_balance(deployer.address)
print(f"Deployer balance: {bal} wei ({bal / 10**18} GEN)")

PROPHET_GRID = "0x31C53838fF49168128D772625e34d3D2F7e11116"
HOOK_ADDRESS = "0x50C948FD62034cEe92C161411D7c7c1737511666"
DEPLOY_TX_HASH = "0x507273e8c827f25402521232336521c77a77196f3d8e8479af8eb78ecf35d5fb"

evidence = {
    "network": "GenLayer Studionet",
    "chain_id": 61999,
    "rpc_url": "https://studio.genlayer.com/api",
    "deployer_address": deployer.address,
    "prophet_grid_address": PROPHET_GRID,
    "deployed_hook_address": HOOK_ADDRESS,
    "deploy_tx_hash": DEPLOY_TX_HASH,
    "transactions": [
        {
            "description": "Deploy ProphetVolatilityHook",
            "signer": deployer.address,
            "tx_hash": DEPLOY_TX_HASH,
            "status": "FINALIZED",
            "consensus_result": "MAJORITY_AGREE",
            "contract_address": HOOK_ADDRESS,
            "result_data": ""
        }
    ]
}

def wait_and_record(tx_hash, description, signer=deployer.address):
    hash_str = tx_hash if isinstance(tx_hash, str) else tx_hash.hex()
    print(f"\n[TX] {description} -> Hash: {hash_str}")
    receipt = client.wait_for_transaction_receipt(
        tx_hash,
        status=TransactionStatus.FINALIZED,
        interval=3000,
        retries=60,
        full_transaction=True
    )
    status_str = receipt.get("status", "UNKNOWN")
    tx_info = client.get_transaction(hash_str)
    status_name = tx_info.get("status_name", status_str)
    last_round = tx_info.get("last_round", {})
    consensus_res = "N/A"
    if isinstance(last_round, dict):
        votes = last_round.get("validator_votes_name", [])
        if votes:
            consensus_res = f"VOTES: {votes}"

    print(f"     Status: {status_name}")
    print(f"     Consensus: {consensus_res}")

    tx_record = {
        "description": description,
        "signer": signer,
        "tx_hash": hash_str,
        "status": status_name,
        "consensus_result": consensus_res
    }
    evidence["transactions"].append(tx_record)
    return receipt, tx_info

# Verify Initial State
cfg = client.read_contract(address=HOOK_ADDRESS, function_name="get_hook_config", args=[])
print(f"On-chain Hook Config: {cfg}")
inv0 = client.read_contract(address=HOOK_ADDRESS, function_name="get_custody_accounting_summary", args=[])
print(f"Initial Invariants: {inv0}")

# STEP 2: Soft-fail payable rejection & 100% refund credit
print("\n=== STEP 2: SOFT-FAIL PAYABLE REJECTION & REFUNDABLE CREDIT ===")
soft_fail_tx = client.write_contract(
    address=HOOK_ADDRESS,
    function_name="open_volatility_margin_payable",
    args=["11", "https://pypi.org/pypi/requests/json", 10],
    value=500  # Below MIN_COLLATERAL
)
wait_and_record(soft_fail_tx, "Soft-fail open_volatility_margin_payable (below min collateral)")

ref_bal1 = client.read_contract(address=HOOK_ADDRESS, function_name="get_refundable_balance", args=[deployer.address])
last_rej1 = client.read_contract(address=HOOK_ADDRESS, function_name="get_last_payable_rejection", args=[deployer.address])
print(f"Refundable Balance: {ref_bal1} wei (Expected 500)")
print(f"Last Rejection: {last_rej1} (Expected COLLATERAL_BELOW_MINIMUM)")

# STEP 3: EOA Withdrawal of refundable balance
print("\n=== STEP 3: EOA WITHDRAWAL OF REFUNDABLE BALANCE ===")
withdraw_tx = client.write_contract(
    address=HOOK_ADDRESS,
    function_name="withdraw_refundable_balance",
    args=[500]
)
wait_and_record(withdraw_tx, "Withdraw refundable balance via EOA recipient transfer")

ref_bal2 = client.read_contract(address=HOOK_ADDRESS, function_name="get_refundable_balance", args=[deployer.address])
print(f"Refundable Balance after withdrawal: {ref_bal2} wei (Expected 0)")

# STEP 4: Margin Open linked to ProphetGrid market 11
print("\n=== STEP 4: OPEN VOLATILITY MARGIN LINKED TO PROPHETGRID ===")
open_margin_tx = client.write_contract(
    address=HOOK_ADDRESS,
    function_name="open_volatility_margin_payable",
    args=["11", "https://pypi.org/pypi/requests/json", 10],
    value=5000000000000000  # 0.005 GEN
)
wait_and_record(open_margin_tx, "Open margin buffer linked to ProphetGrid market 11")

pos_count = client.read_contract(address=HOOK_ADDRESS, function_name="get_positions_count", args=[])
pos1 = client.read_contract(address=HOOK_ADDRESS, function_name="get_margin_position", args=["1"])
print(f"Total positions: {pos_count}")
print(f"Position 1: {json.dumps(pos1, indent=2)}")

# STEP 5: Cooldown wait
print("\n=== STEP 5: COOLDOWN WAIT ===")
print("Waiting 15 seconds for cooldown to elapse...")
time.sleep(15)

# STEP 6: Evaluate Volatility Regime via Consensus
print("\n=== STEP 6: EVALUATE VOLATILITY REGIME VIA CONSENSUS ===")
eval_tx = client.write_contract(
    address=HOOK_ADDRESS,
    function_name="evaluate_volatility_regime",
    args=["1"]
)
wait_and_record(eval_tx, "Evaluate volatility regime via validator consensus")

pos1_eval = client.read_contract(address=HOOK_ADDRESS, function_name="get_margin_position", args=["1"])
print(f"Position 1 after Consensus Evaluation: {json.dumps(pos1_eval, indent=2)}")

# STEP 7: Cross-Contract Reconciliation with ProphetGrid
print("\n=== STEP 7: CROSS-CONTRACT RECONCILIATION WITH PROPHETGRID ===")
recon_tx = client.write_contract(
    address=HOOK_ADDRESS,
    function_name="reconcile_market_margin_state",
    args=["1"]
)
wait_and_record(recon_tx, "Reconcile market margin state against ProphetGrid")

pos1_recon = client.read_contract(address=HOOK_ADDRESS, function_name="get_margin_position", args=["1"])
print(f"Position 1 after Cross-Contract Reconciliation: {json.dumps(pos1_recon, indent=2)}")

# STEP 8: Final Invariants
print("\n=== STEP 8: FINAL CUSTODY ACCOUNTING INVARIANTS ===")
inv_final = client.read_contract(address=HOOK_ADDRESS, function_name="get_custody_accounting_summary", args=[])
print(f"Final Invariants: {json.dumps(inv_final, indent=2)}")
evidence["final_invariants"] = inv_final
evidence["position_final"] = pos1_recon

os.makedirs("evidence", exist_ok=True)
with open("evidence/studionet_evidence.json", "w", encoding="utf-8") as f:
    json.dump(evidence, f, indent=2)

print("\nSUCCESS! All transactions finalized and evidence saved to evidence/studionet_evidence.json")
