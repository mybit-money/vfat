from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from .base import AdapterKey
from ..contracts import PositionInput, TokenAmount, Valuation
from ..events import (ChainProfile, DecodedTransaction, MergedActivity, TRANSFER_TOPIC,
                      _data_words, _hex_int, _topic_address, _unique_logs, load_chain_profile)


PROFILE_PATH = Path(__file__).resolve().parents[3] / 'profiles' / 'ethereum-uniswap-v4.json'
NATIVE = '0x0000000000000000000000000000000000000000'
WETH = '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'
DRV = '0xb1d1eae60eea9525032a6dcb4c1ce336a1de71be'
REVIEWED_POOL_ID = '0x20ae5557f7d6ce39a6e5370c331106a87a80ea5c1bec686361bde2d9f5e82631'
REVIEWED_POOL_KEY = (NATIVE, DRV, 15000, 300, NATIVE)
# IPoolManager.sol: ModifyLiquidity(bytes32,address,int24,int24,int256,bytes32)
MODIFY_LIQUIDITY_TOPIC = '0xf208f4912782fd25c7f114ca3723a2d5dd6f3bcc3ac8db5af63baa85f711d5ec'
# IPoolManager.sol: Swap(bytes32,address,int128,int128,uint160,uint128,int24,uint24)
SWAP_TOPIC = '0x40e9cecb9f5f1f1c5b9c97dec2917b7ee92e57ba5563708daca94dd84ad7112f'
# Observed Sickle fee-side event, deliberately NOT decoded with an unverified ABI.
OPAQUE_FEE_TOPIC = '0x20637f693d80799c8bf08f5bf9614910f0106e0f0d787852fcd247b514b5f1ee'


def _signed(word: str) -> int:
    value = int(word, 16)
    return value - (1 << 256) if value & (1 << 255) else value


def _sqrt_at_tick(tick: int) -> int:
    """Integer Q96 arithmetic from Uniswap v4-core TickMath.getSqrtPriceAtTick."""
    if abs(tick) > 887272:
        raise ValueError('invalid_v4_tick')
    factors = (
        0xfffcb933bd6fad37aa2d162d1a594001, 0xfff97272373d413259a46990580e213a,
        0xfff2e50f5f656932ef12357cf3c7fdcc, 0xffe5caca7e10e4e61c3624eaa0941cd0,
        0xffcb9843d60f6159c9db58835c926644, 0xff973b41fa98c081472e6896dfb254c0,
        0xff2ea16466c96a3843ec78b326b52861, 0xfe5dee046a99a2a811c461f1969c3053,
        0xfcbe86c7900a88aedcffc83b479aa3a4, 0xf987a7253ac413176f2b074cf7815e54,
        0xf3392b0822b70005940c7a398e4b70f3, 0xe7159475a2c29b7443b29c7fa6e889d9,
        0xd097f3bdfd2022b8845ad8f792aa5825, 0xa9f746462d870fdf8a65dc1f90e061e5,
        0x70d869a156d2a1b890bb3df62baf32f7, 0x31be135f97d08fd981231505542fcfa6,
        0x9aa508b5b7a84e1c677de54f3e99bc9, 0x5d6af8dedb81196699c329225ee604,
        0x2216e584f5fa1ea926041bedfe98, 0x48a170391f7dc42444e8fa2,
    )
    price = 1 << 128
    for bit, factor in enumerate(factors):
        if abs(tick) & (1 << bit):
            price = price * factor >> 128
    if tick > 0:
        price = ((1 << 256) - 1) // price
    return (price + (1 << 32) - 1) >> 32


def _principal(lower: int, upper: int, liquidity: int, price: int) -> tuple[int, int]:
    """Positive principal, rounded up exactly as V4 SqrtPriceMath for additions."""
    if lower >= upper or liquidity <= 0 or liquidity >= 1 << 127:
        raise ValueError('invalid_v4_liquidity')
    low, high = _sqrt_at_tick(lower), _sqrt_at_tick(upper)
    current = max(low, min(price, high))
    numerator0 = (liquidity << 96) * (high-current)
    denominator0 = high * current
    amount0 = (numerator0 + denominator0-1) // denominator0
    amount1 = (liquidity * (current-low) + (1 << 96)-1) >> 96
    return amount0, amount1


def _load_profile():
    profile = load_chain_profile(PROFILE_PATH)
    return replace(profile, tokens=MappingProxyType(dict(profile.tokens)),
                   pools=MappingProxyType(dict(profile.pools)))


def _profile_value(name):
    return json.loads(PROFILE_PATH.read_text(encoding='utf-8'))[name]


def _load_pool_key():
    data = _profile_value('poolKey')
    pair = _profile_value('pools')[_profile_value('poolId')]
    return (pair['token0'], pair['token1'], data['fee'], data['tickSpacing'], data['hooks'])


@dataclass(frozen=True)
class EthereumUniswapV4Adapter:
    key: AdapterKey = AdapterKey(1, 'uniswap_v4')
    chain_profile: ChainProfile = field(default_factory=_load_profile)
    default_rpc_endpoints: tuple[str, ...] = ('https://ethereum-rpc.publicnode.com', 'https://eth.llamarpc.com')
    price_chain_slug: str = 'ethereum'
    position_manager: str = field(default_factory=lambda: _profile_value('positionManager'))
    pool_manager: str = field(default_factory=lambda: _profile_value('poolManager'))
    pool_id: str = field(default_factory=lambda: _profile_value('poolId'))
    pool_key: tuple = field(default_factory=_load_pool_key)

    def normalize_price_token(self, address: str) -> str:
        address = address.lower()
        return WETH if address in (NATIVE, '0x'+'ee'*20, 'eth', 'native') else address

    def supports_position(self, position: PositionInput) -> bool:
        metadata = position.metadata if isinstance(position.metadata, Mapping) else {}
        expected = {'protocolType': 'uniswap_v4', 'poolAddress': self.pool_manager,
                    'poolManagerAddress': self.pool_manager, 'poolId': self.pool_id}
        if (position.chain_id != 1 or position.sickle_address.lower() not in self.chain_profile.tracked_sickle_addresses
                or (position.nft_manager_address or '').lower() != self.position_manager
                or any(str(metadata.get(k, '')).lower() != v for k, v in expected.items())):
            return False
        underlying = metadata.get('underlying')
        if not isinstance(underlying, (list, tuple)) or len(underlying) != 2:
            return False
        pair = self.chain_profile.pools[self.pool_id]
        return all(isinstance(token, Mapping) and
                   str(token.get('address', '')).lower() in
                   ((NATIVE, '0x'+'ee'*20) if address == NATIVE else (address,))
                   and token.get('decimals') == 18 for token, address in zip(underlying, pair))

    def profile_for_positions(self, positions: tuple[PositionInput, ...]) -> ChainProfile:
        return replace(self.chain_profile, tracked_sickle_addresses=frozenset(
            p.sickle_address.lower() for p in positions if self.supports_position(p)))

    def decode_receipt(self, activity: MergedActivity, receipt: Mapping,
                       positions: tuple[PositionInput, ...]) -> DecodedTransaction:
        tx_hash = str(receipt.get('transactionHash', '')).lower()
        if tx_hash != activity.transaction_hash.lower():
            raise ValueError('receipt transactionHash does not match activity')
        if activity.chain_id != self.key.chain_id:
            raise ValueError('activity chain does not match chain profile')
        # The PoolKey is immutable, read from PositionManager and independently
        # keccak-verified against this ID (see pool-key-evidence.json). No hook may
        # adjust the principal deltas calculated below.
        if self.pool_key != REVIEWED_POOL_KEY:
            raise ValueError('pool_key_unsupported')
        if self.pool_id != REVIEWED_POOL_ID:
            raise ValueError('pool_identity_mismatch')
        if _hex_int(receipt.get('status', '0x1')) != 1:
            raise ValueError('receipt_transaction_failed')
        selected = tuple(p for p in positions if p.position_id in
                         activity.source_position_ids + activity.recipient_position_ids)
        if not selected or not all(self.supports_position(p) for p in selected):
            raise ValueError('pool_identity_mismatch')
        profile = self.profile_for_positions(selected)
        token_ids = {int(p.token_id) for p in selected if p.token_id and p.token_id.isdecimal()}
        for p in selected:
            root = (p.position_root_token_id or '').rsplit(':', 1)[-1]
            if root.isdecimal():
                token_ids.add(int(root))
        receipt_logs = receipt.get('logs', [])
        if any(str(log.get('transactionHash', tx_hash)).lower() != tx_hash for log in receipt_logs):
            raise ValueError('log_transaction_mismatch')
        logs = sorted(_unique_logs(tx_hash, receipt_logs),
                      key=lambda log: _hex_int(log.get('logIndex', '0x0')))
        gross, fees, lp = {}, {}, {}
        warnings = ['native_claim_unavailable']
        price = None
        context = None
        seen_pool = False
        incomplete_lp = False
        opaque_fee = False
        pending = None
        token0, token1 = profile.pools[self.pool_id]

        for log in logs:
            address = str(log.get('address', '')).lower()
            topics = [str(t).lower() for t in log.get('topics', [])]
            if not topics:
                continue
            if address == self.pool_manager and topics[0] in (MODIFY_LIQUIDITY_TOPIC, SWAP_TOPIC):
                # Other pools neither update the selected price nor contribute amounts.
                if len(topics) != 3 or topics[1] != self.pool_id:
                    context = None
                    continue
                seen_pool = True
                words = _data_words(log.get('data', '0x'))
                if topics[0] == SWAP_TOPIC:
                    if len(words) != 6:
                        raise ValueError('invalid_v4_swap_event')
                    price = int(words[2], 16)
                    context = None
                    continue
                if len(words) != 4:
                    raise ValueError('invalid_v4_modify_liquidity_event')
                context = None
                if _topic_address(topics[2]) != self.position_manager or int(words[3],16) not in token_ids:
                    continue
                delta = _signed(words[2])
                context = 'claim' if delta == 0 else 'remove' if delta < 0 else 'add'
                if delta < 0:
                    warnings.append('claim_principal_separation_unavailable')
                elif delta > 0:
                    if pending is not None:
                        incomplete_lp = True
                    if price is None:
                        incomplete_lp = True
                    else:
                        pending = _principal(_signed(words[0]), _signed(words[1]), delta, price)
                continue
            if (context is not None and address in profile.tracked_sickle_addresses
                    and topics[0] == OPAQUE_FEE_TOPIC):
                # Native fee data is not an ERC20 Transfer. Do not assume its absence
                # or guess its layout; the observed opaque event blocks complete USD.
                opaque_fee = True
            if topics[0] != TRANSFER_TOPIC or len(topics) != 3:
                continue
            words = _data_words(log.get('data', '0x'))
            if len(words) != 1:
                continue
            sender, recipient = _topic_address(topics[1]), _topic_address(topics[2])
            raw = int(words[0], 16)
            if sender in profile.claim_source_addresses and recipient in profile.tracked_sickle_addresses:
                if context == 'claim':
                    gross[address] = gross.get(address, 0) + raw
                elif context == 'remove':
                    # Removed capital and accrued fees are netted into one transfer.
                    # Preserve the evidence in diagnostics without calling it income.
                    warnings.append(f'unseparated_withdrawal_raw:{address}:{raw}')
            if sender in profile.tracked_sickle_addresses and recipient in profile.automation_fee_recipients:
                # Endpoints alone do not identify a pool or NFT. Only the current
                # validated lineage liquidity operation can attribute this fee.
                # A foreign operation or swap clears that evidence; do not guess.
                if context is None:
                    raise ValueError('fee_attribution_ambiguous')
                fees[address] = fees.get(address, 0) + raw
            if (pending is not None and context == 'add' and address == token1
                    and sender in profile.tracked_sickle_addresses and recipient == self.pool_manager):
                if raw == pending[1]:
                    for token, amount in zip((token0, token1), pending):
                        if amount > 0:
                            lp[token] = lp.get(token, 0) + amount
                else:
                    incomplete_lp = True
                pending = None

        if not seen_pool:
            raise ValueError('pool_identity_mismatch')
        if pending is not None or incomplete_lp:
            incomplete_lp = True
            lp = {}
            warnings.append('lp_settlement_unavailable')
        if opaque_fee:
            warnings.append('native_fee_unavailable')

        def amounts(values):
            result = []
            for address, raw in sorted(values.items()):
                metadata = profile.tokens.get(address)
                if metadata is None:
                    # Schema v1 requires an integer decimals field. Zero is a raw-unit
                    # sentinel, NOT token decimals; warnings forbid valuation.
                    warnings.append('unknown_token_decimals:' + address)
                result.append(TokenAmount(address, metadata.symbol if metadata else None,
                                          metadata.decimals if metadata else 0, raw))
            return tuple(result)

        gross_amounts, fee_amounts, lp_amounts = amounts(gross), amounts(fees), amounts(lp)
        return DecodedTransaction(
            chain_id=1, transaction_hash=tx_hash, timestamp=activity.timestamp,
            action_type=activity.action_type, source_position_ids=activity.source_position_ids,
            recipient_position_ids=activity.recipient_position_ids,
            automation_payment_method=activity.automation_payment_method,
            gross_claims=gross_amounts, automation_fees=fee_amounts, lp_additions=lp_amounts,
            gross_claim_usd=Valuation(None, reason='claim_principal_separation_unavailable'
                                    if 'claim_principal_separation_unavailable' in warnings else 'native_claim_unavailable'),
            automation_fee_usd=Valuation(None, reason='native_fee_unavailable') if opaque_fee
                else Valuation(None, reason='historical_reward_usd_unavailable') if fees
                else Valuation(Decimal(0), source='receipt_no_matching_fee_transfer'),
            net_compound_usd=Valuation(None, reason='claim_principal_separation_unavailable'
                if 'claim_principal_separation_unavailable' in warnings
                else 'lp_settlement_unavailable' if incomplete_lp else 'historical_lp_usd_unavailable'),
            network_gas_native=Decimal(_hex_int(receipt.get('gasUsed','0x0')) *
                                       _hex_int(receipt.get('effectiveGasPrice','0x0'))) / Decimal(10**18),
            network_gas_payer=str(receipt.get('from', '')).lower() or None,
            warnings=tuple(dict.fromkeys(warnings)),
        )
