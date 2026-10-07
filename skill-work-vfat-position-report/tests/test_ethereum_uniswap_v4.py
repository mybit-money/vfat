from __future__ import annotations

import copy
import json
import unittest
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from vfat_report.adapters.base import AdapterKey
from vfat_report.adapters.registry import get_adapter
from vfat_report.contracts import PositionInput
from vfat_report.contracts import ActivityInput
from vfat_report.events import MergedActivity, merge_position_activity


FIXTURES = Path(__file__).parent / 'fixtures' / 'ethereum-uniswap-v4'
ETH = '0x0000000000000000000000000000000000000000'
WETH = '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'
DRV = '0xb1d1eae60eea9525032a6dcb4c1ce336a1de71be'
SICKLE = '0xfb12aa1f51ba66ef761def09233946a4369b0de6'
MANAGER = '0xbd216513d74c8cf14cf4747e6aaa6420ff64ee9e'
POOL_MANAGER = '0x000000000004444c5dc75cb358380d2e3de08a90'
POOL_ID = '0x20ae5557f7d6ce39a6e5370c331106a87a80ea5c1bec686361bde2d9f5e82631'
ROOT = 'bd216513d74c8cf14cf4747e6aaa6420ff64ee9e:413470'


def position():
    return PositionInput(
        position_id=ROOT, chain_id=1, protocol='uniswap', position_type='nft',
        sickle_address=SICKLE, token_id='413473', nft_manager_address=MANAGER,
        position_root_token_id=ROOT,
        metadata={'protocolType': 'uniswap_v4', 'poolAddress': POOL_MANAGER,
                  'poolManagerAddress': POOL_MANAGER, 'poolId': POOL_ID,
                  'underlying': [{'address': ETH, 'symbol': 'ETH', 'decimals': 18},
                                 {'address': DRV, 'symbol': 'DRV', 'decimals': 18}]},
    )


class EthereumUniswapV4ProfileTests(unittest.TestCase):
    def setUp(self):
        self.adapter = get_adapter(AdapterKey(1, 'uniswap_v4'))
        self.assertIsNotNone(self.adapter, 'Ethereum adapter must be registered')

    def test_profile_and_pricing(self):
        self.assertEqual(type(self.adapter).__name__, 'EthereumUniswapV4Adapter')
        profile = self.adapter.chain_profile
        self.assertEqual((profile.chain_id, profile.native_symbol, profile.native_decimals), (1, 'ETH', 18))
        self.assertEqual(profile.tokens[DRV].decimals, 18)
        self.assertEqual(profile.pools[POOL_ID], (ETH, DRV))
        self.assertEqual(self.adapter.price_chain_slug, 'ethereum')
        for alias in (ETH, '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee', 'ETH', 'native'):
            self.assertEqual(self.adapter.normalize_price_token(alias), WETH)
        self.assertEqual(self.adapter.normalize_price_token(DRV.upper()), DRV)
        with self.assertRaises(TypeError):
            profile.tokens[DRV] = profile.tokens[ETH]

    def test_supported_identity_and_underlying(self):
        self.assertTrue(self.adapter.supports_position(position()))
        for field, value in [('chain_id', 999), ('sickle_address', ETH), ('nft_manager_address', ETH)]:
            self.assertFalse(self.adapter.supports_position(replace(position(), **{field: value})))
        for field, value in [('protocolType', 'nest'), ('poolAddress', ETH), ('poolManagerAddress', ETH), ('poolId', '0x'+'11'*32), ('underlying', [])]:
            changed = copy.deepcopy(position().metadata)
            changed[field] = value
            self.assertFalse(self.adapter.supports_position(replace(position(), metadata=changed)))
        changed = copy.deepcopy(position().metadata)
        changed['underlying'][1]['decimals'] = 6
        self.assertFalse(self.adapter.supports_position(replace(position(), metadata=changed)))

    def test_native_alias_preserves_pool_currency_identity(self):
        changed = copy.deepcopy(position().metadata)
        changed['underlying'][0]['address'] = '0x'+'ee'*20
        self.assertTrue(self.adapter.supports_position(replace(position(), metadata=changed)))
        changed['underlying'][0]['address'] = WETH
        self.assertFalse(self.adapter.supports_position(replace(position(), metadata=changed)))

    def test_reviewed_pool_key_and_independent_hash_evidence(self):
        evidence = json.loads((FIXTURES / 'pool-key-evidence.json').read_text())
        hash_evidence = json.loads((FIXTURES / 'pool-key-hash-evidence.json').read_text())
        self.assertEqual(evidence['request']['params'][0]['to'], MANAGER)
        self.assertEqual(hash_evidence['request']['params'][0], evidence['response']['result'][:322])
        self.assertEqual(hash_evidence['response']['result'], POOL_ID)
        words = [evidence['response']['result'][i:i+64] for i in range(2,322,64)]
        self.assertEqual(('0x'+words[0][-40:], '0x'+words[1][-40:], int(words[2],16), int(words[3],16), '0x'+words[4][-40:]),
                         self.adapter.pool_key)


class EthereumUniswapV4ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.adapter = get_adapter(AdapterKey(1, 'uniswap_v4'))

    def fixture(self, name):
        receipt = json.loads((FIXTURES / (name+'-receipt.json')).read_text())
        data = next(a for a in json.loads((FIXTURES / 'activity.json').read_text())['activities'] if a['fixture'] == name)
        activity = MergedActivity(1, data['transactionHash'], datetime.fromisoformat(data['timestamp']), data['actionType'],
                                  (ROOT,), (ROOT,), data['isAutomation'], data.get('automationPaymentMethod'))
        return activity, receipt

    def decode(self, name, mutate=None):
        activity, receipt = self.fixture(name)
        if mutate:
            mutate(receipt)
        return self.adapter.decode_receipt(activity, receipt, (position(),))

    def test_reviewed_exact_raw_amounts_and_gas(self):
        expected = [
            ('manual-compound', 149900950242857240585, 1349108552185715165,
             {ETH: 3529955058449672, DRV: 284732973291841119728}, '0.000190202108379192'),
            ('automated-compound', 153436634871055107226, 2761859427678991930,
             {DRV: 269803301529586295801}, '0.000055908875038566'),
            ('rebalance-413470-413473', None, 1103644823552445743,
             {ETH: 376818096921121608, DRV: 6668163230339663424835}, '0.000540091550072412'),
        ]
        for name, gross, fee, lp, gas in expected:
            with self.subTest(name=name):
                result = self.decode(name)
                activity, receipt = self.fixture(name)
                self.assertEqual(result.transaction_hash, activity.transaction_hash)
                self.assertEqual(result.timestamp, activity.timestamp)
                self.assertEqual(result.source_position_ids, (ROOT,))
                self.assertEqual(result.recipient_position_ids, (ROOT,))
                self.assertEqual({x.token_address:x.raw_amount for x in result.gross_claims}, {} if gross is None else {DRV:gross})
                self.assertEqual({x.token_address:x.raw_amount for x in result.automation_fees}, {DRV:fee})
                self.assertEqual({x.token_address:x.raw_amount for x in result.lp_additions}, lp)
                self.assertEqual(result.network_gas_native, Decimal(gas))
                self.assertEqual(result.network_gas_payer, receipt['from'])
                self.assertIsNone(result.gas_account_debit_native)
                self.assertIsNone(result.gross_claim_usd.usd)
                self.assertIn('native_claim_unavailable', result.warnings)
                self.assertIn('native_fee_unavailable', result.warnings)
                if gross is None:
                    self.assertIn('claim_principal_separation_unavailable', result.warnings)

    def test_manual_label_does_not_erase_observed_fee(self):
        result = self.decode('manual-compound')
        self.assertEqual(result.automation_fees[0].raw_amount, 1349108552185715165)

    def test_zero_fee_requires_absence_of_matching_transfer_and_native_fee_event(self):
        # This mutation is a synthetic zero-fee case, not the real manual receipt.
        def remove_fees(r):
            r['logs'] = [l for l in r['logs'] if not (
                (len(l['topics']) == 3 and l['topics'][2].endswith('d4627ecb405b64448ee6b07dcf860bf55590c83d'))
                or l['topics'][0] == '0x20637f693d80799c8bf08f5bf9614910f0106e0f0d787852fcd247b514b5f1ee')]
        result = self.decode('manual-compound', remove_fees)
        self.assertEqual(result.automation_fees, ())
        self.assertEqual(result.automation_fee_usd.usd, Decimal(0))

    def test_duplicates_do_not_double_count(self):
        original = self.decode('manual-compound')
        duplicated = self.decode('manual-compound', lambda r:r['logs'].extend(copy.deepcopy(r['logs'])))
        self.assertEqual(duplicated, original)

    def test_unrelated_pool_and_unrelated_nft_do_not_contribute(self):
        def mutate(r):
            for log in copy.deepcopy(r['logs']):
                log['logIndex'] = hex(int(log['logIndex'],16)+4096)
                if log['topics'][0].startswith('0xf208') or log['topics'][0].startswith('0x40e9'):
                    log['topics'][1] = '0x'+'11'*32
                    r['logs'].append(log)
        self.assertEqual(self.decode('manual-compound', mutate), self.decode('manual-compound'))
        def wrong_nft(r):
            for log in r['logs']:
                if log['topics'][0].startswith('0xf208'):
                    log['data'] = log['data'][:-64] + format(999999,'064x')
        self.assertEqual(self.decode('manual-compound', wrong_nft).lp_additions, ())

    def test_wrong_pool_and_wrong_receipt_fail_closed(self):
        activity, receipt = self.fixture('manual-compound')
        with self.assertRaisesRegex(ValueError, 'pool_identity_mismatch'):
            replace(self.adapter, pool_id='0x'+'11'*32).decode_receipt(activity, receipt, (position(),))
        with self.assertRaisesRegex(ValueError, 'transactionHash'):
            self.adapter.decode_receipt(replace(activity, transaction_hash='0x'+'11'*32), receipt, (position(),))

    def test_foreign_transaction_logs_cannot_contaminate_receipt(self):
        def mutate(r):
            r['logs'][1]['transactionHash'] = '0x'+'11'*32
        with self.assertRaisesRegex(ValueError, 'log_transaction_mismatch'):
            self.decode('manual-compound', mutate)

    def test_v3_mint_cannot_create_v4_additions(self):
        def mutate(r):
            r['logs'] = [{'address':POOL_MANAGER, 'logIndex':'0x1',
                          'topics':['0x7a53080ba414158be7ec69b987b5fb7d07dee101fe85488f0853ae16239d0bde'],
                          'data':'0x'+format(1000,'064x')*4}]
        with self.assertRaisesRegex(ValueError, 'pool_identity_mismatch'):
            self.decode('manual-compound', mutate)

    def test_missing_selected_pool_price_is_unavailable(self):
        def mutate(r):
            r['logs'] = [l for l in r['logs'] if not l['topics'][0].startswith('0x40e9')]
        result = self.decode('manual-compound', mutate)
        self.assertEqual(result.lp_additions, ())
        self.assertIn('lp_settlement_unavailable', result.warnings)

    def test_missing_settlement_retains_unavailable_valuation_reason(self):
        result = self.decode('manual-compound', lambda r:r.update(
            logs=[l for l in r['logs'] if l['logIndex'] != '0x3bc']))
        self.assertEqual(result.lp_additions, ())
        self.assertEqual(result.net_compound_usd.reason, 'lp_settlement_unavailable')

    def test_unknown_claim_token_is_preserved_without_decimals_guess(self):
        def mutate(r):
            for existing in r['logs']:
                existing['logIndex'] = hex(int(existing['logIndex'],16)*2)
            log = copy.deepcopy(r['logs'][1])
            log['address'] = '0x'+'ab'*20
            log['logIndex'] = hex(int(log['logIndex'],16)+1)
            r['logs'].append(log)
        result = self.decode('manual-compound', mutate)
        unknown = next(x for x in result.gross_claims if x.token_address == '0x'+'ab'*20)
        self.assertEqual(unknown.raw_amount, 149900950242857240585)
        self.assertIsNone(unknown.symbol)
        self.assertIn('unknown_token_decimals:0x'+'ab'*20, result.warnings)

    def test_pool_hooks_and_unverified_key_fail_closed(self):
        activity, receipt = self.fixture('manual-compound')
        self.assertTrue(hasattr(self.adapter, 'pool_key'), 'math must be guarded by the reviewed immutable PoolKey')
        with self.assertRaisesRegex(ValueError, 'pool_key_unsupported'):
            replace(self.adapter, pool_key=(ETH, DRV, 15000, 300, SICKLE)).decode_receipt(activity, receipt, (position(),))

    def test_settlement_mismatch_and_failed_receipt_fail_closed(self):
        def mismatch(r):
            for log in r['logs']:
                if log['logIndex'] == '0x3bc':
                    log['data'] = '0x'+format(1,'064x')
        result = self.decode('manual-compound', mismatch)
        self.assertEqual(result.lp_additions, ())
        self.assertIn('lp_settlement_unavailable', result.warnings)
        with self.assertRaisesRegex(ValueError, 'receipt_transaction_failed'):
            self.decode('manual-compound', lambda r:r.update(status='0x0'))

    def test_other_pool_settlement_transfers_are_excluded(self):
        def mutate(r):
            copies = copy.deepcopy(r['logs'])
            for log in copies:
                log['logIndex'] = hex(int(log['logIndex'],16)+4096)
                if log['topics'][0].startswith('0xf208') or log['topics'][0].startswith('0x40e9'):
                    log['topics'][1] = '0x'+'11'*32
            # Only pool events and settlement, not independently observed fee transfers.
            r['logs'].extend(l for l in copies if l['address'] == POOL_MANAGER
                             or (len(l['topics']) == 3 and l['topics'][2].endswith(POOL_MANAGER[2:])))
        self.assertEqual(self.decode('manual-compound', mutate), self.decode('manual-compound'))

    def test_partial_claim_and_rebalance_usd_remain_unavailable(self):
        compound = self.decode('manual-compound')
        self.assertTrue(compound.gross_claims)
        self.assertEqual(compound.gross_claim_usd.reason, 'native_claim_unavailable')
        self.assertIsNone(compound.gross_claim_usd.usd)
        rebalance = self.decode('rebalance-413470-413473')
        self.assertEqual(rebalance.gross_claim_usd.reason, 'claim_principal_separation_unavailable')
        self.assertIsNone(rebalance.gross_claim_usd.usd)

    def test_rebalance_lineage_merges_once(self):
        activity, _ = self.fixture('rebalance-413470-413473')
        item = ActivityInput(1, activity.transaction_hash, activity.timestamp, 'rebalance', (ROOT,), ROOT)
        merged = merge_position_activity([item,item])
        self.assertEqual(len(merged),1)
        self.assertEqual(merged[0].source_position_ids,(ROOT,))
        self.assertEqual(merged[0].recipient_position_ids,(ROOT,))


if __name__ == '__main__':
    unittest.main()
