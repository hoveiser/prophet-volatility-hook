# Deployment and Verification Record

## Network Overview
- Network: GenLayer Studionet
- Chain ID: 61999
- RPC Endpoint: https://studio.genlayer.com/api
- Deployer / Operator Account: `0x3de43AA2f7162c80af98abe78222aE0Cdf83c506`
- Flagship ProphetGrid Ecosystem Address: `0x31C53838fF49168128D772625e34d3D2F7e11116`
- Deployed Contract Name: `ProphetVolatilityHook`
- Deployed Contract Address: `0x50C948FD62034cEe92C161411D7c7c1737511666`
- Pinned Runner Version: `py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6`
- Contract Source LF SHA-256: `5875cbc7386e615ac532bc8aceb1ce4da1762f05cb9f6d12e6e5c3ad8e51b653`

---

## Live Studionet Transaction Lifecycle

All transactions were executed on Studionet, verified by validators, and reached `FINALIZED` status.

| Step | Operation | Transaction Hash | Status | Consensus Result / Votes | Details |
|------|-----------|------------------|--------|--------------------------|---------|
| 1 | Deploy ProphetVolatilityHook | `0x507273e8c827f25402521232336521c77a77196f3d8e8479af8eb78ecf35d5fb` | FINALIZED | AGREE: 3, IDLE: 2 | Deployed to `0x50C948FD62034cEe92C161411D7c7c1737511666` with ProphetGrid binding |
| 2 | Soft-Fail Payable Rejection | `0x16d728f6d15b06b2686b16b0470f0d67faefe23a52e7d1fb1763ff4654d4302a` | FINALIZED | AGREE: 3, IDLE: 2 | 500 wei sent (< min collateral). Rejection credited 100% to refundable balance |
| 3 | EOA Refund Withdrawal | `0x8fec876326d10476fd86f762a4bc67e2e1defdd922ffc4f5a2f12b9c5983641c` | FINALIZED | AGREE: 3, IDLE: 2 | 500 wei delivered to claimant EOA via `IEoaRecipient.emit_transfer` |
| 4 | Open Volatility Margin | `0x0499fb115e35621fa922b878e5114976b8ff533b3659c98dfc00968dd8fbbd36` | FINALIZED | AGREE: 3, IDLE: 2 | 0.005 GEN collateral staked for Position 1 linked to ProphetGrid market 11 |
| 5 | Consensus Regime Evaluation | `0x245004d6180a0168af68885486f27cbbdb46eb9638ae532d1aea8a03b43ae167` | FINALIZED | AGREE: 3, IDLE: 2 | Live web render + 250-bps grid quantization -> 500 bps (CALM_LOW_VOL_RELEASE) |
| 6 | Cross-Contract Reconciliation | `0xaf5fc1e5378e96388c11de97a33d8ca72434841af7f9ae0bbd0ff59aee07c1ce` | FINALIZED | AGREE: 3, IDLE: 2 | Verified market 11 on ProphetGrid: OPEN:OPEN_WINDOW:REFUNDABLE |

---

## On-Chain Post-Scenario State Verification

### Position 1 State
```json
{
  "position_id": "1",
  "trader": "0x3de43AA2f7162c80af98abe78222aE0Cdf83c506",
  "prophet_grid_market_id": "11",
  "posted_collateral_wei": 5000000000000000,
  "quantized_vol_bps": 500,
  "margin_tier": "CALM_LOW_VOL_RELEASE",
  "multiplier_bps": 10000,
  "required_margin_wei": 5000000000000000,
  "status": "RECONCILED",
  "volatility_source_url": "https://pypi.org/pypi/requests/json",
  "created_at_dt": "2026-11-20T10:26:33.098732Z",
  "last_evaluated_dt": "2026-11-20T10:27:34.793453Z",
  "cooldown_seconds": 10,
  "cooldown_elapsed": true,
  "reconciled": true,
  "reconciled_market_status": "OPEN:OPEN_WINDOW:REFUNDABLE",
  "can_release": true,
  "can_refund": true
}
```

### Custody Accounting Summary
```json
{
  "active_margin_escrow_wei": 5000000000000000,
  "total_refundable_balances_wei": 0,
  "native_custody_balance_wei": 5000000000000000,
  "stranded_residue_wei": 0,
  "invariant_holds": true
}
```
All accounting invariants hold with 0 wei stranded residue.
