"""Isolated review regressions: no auth, network, native App, production state or scheduler calls.
Run with candidate root as first argument; all runtime state uses TemporaryDirectory.
"""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from decimal import Decimal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT))
from test_account_review import FullBackend
from test_business import expense
from qianji_agent.engine import Engine
from qianji_agent.journal import Journal
from qianji_agent.codec import loads, digest
from qianji_agent.operations import prepare, make_row
from qianji_agent.continuation import classify_pending


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / 'journal'

    def test_new_plain_bill_must_reject_extra_currency_and_task_relations(self):
        class LinkedResult(FullBackend):
            def write(self, *args):
                result = super().write(*args)
                row = self.data['bills'][-1]
                row['extra'] = {'preinstallid': 777, 'curr': {'ss': 'USD', 'sv': 100, 'ts': 'CNY', 'tv': row['money'], 'bs': 'CNY', 'bv': row['money']}}
                row['packid'] = 777
                return result
        backend = LinkedResult()
        engine = Engine(backend, '123', self.state)
        engine.account_review()
        result = engine.execute('new', expense())
        self.assertEqual(result['state'], 'pending_verification', result)
        self.assertTrue(engine.journal.active_halts())

    def test_old_plain_bill_with_new_native_task_relation_is_conflict(self):
        backend = FullBackend()
        plan = prepare(expense(), backend.data, '123', bill_id='900')
        journal = Journal(self.state, '123')
        journal.start('old', 'h', plan)
        row = copy.deepcopy(plan['row'])
        row.update(packid=777, extra={'preinstallid': 55})
        backend.data['bills'] = [row]
        backend.data['assets'][0]['money'] -= row['money']
        scope = classify_pending({'request_id': 'old', 'plan': plan}, backend.data)
        self.assertEqual(scope['reason'], 'record_relationship_conflict', scope)
        result = Engine(backend, '123', self.state).execute('new', expense())
        self.assertEqual(result['state'], 'not_executed', result)
        self.assertEqual(backend.writes, 0)

    def test_account_rename_must_not_absorb_unrequested_currency_change(self):
        class ChangedRename(FullBackend):
            def write(self, route, params):
                self.writes += 1
                row = loads(params['v'])
                row['currency'] = 'USD'
                self.data['assets'] = [row if a['id'] == row['id'] else a for a in self.data['assets']]
                return {}
        backend = ChangedRename()
        engine = Engine(backend, '123', self.state)
        engine.account_review()
        result = engine.execute('rename', {'action': 'account_rename', 'object_id': '10', 'name': 'Renamed', 'expected_version': digest(backend.data['assets'][0])})
        self.assertEqual(result['state'], 'pending_verification', result)
        self.assertTrue(engine.journal.active_halts())

    def test_hidden_pending_account_still_appears_halted_in_review(self):
        backend = FullBackend()
        engine = Engine(backend, '123', self.state)
        plan = prepare(expense(), backend.data, '123', bill_id='999')
        with engine.journal.lock():
            engine.journal.start('hidden-pending', 'h', plan)
        backend.data['assets'][0]['status'] = 2
        self.assertEqual(engine.journal.active_halts()[0]['account_id'], '10')
        result = engine.account_review()['account_review']
        self.assertFalse(result['ready'], result)
        self.assertTrue(any(a['account_id'] == '10' and a['state'] == 'halted' for a in result['accounts']), result)

    def test_successful_repeat_create_updates_own_task_watchpoint(self):
        class TaskBackend(FullBackend):
            def read(self, route, params):
                if route == 'repeat_task/list':
                    return {'list': copy.deepcopy(self.data['repeat']), 'hasmore': 0}
                return super().read(route, params)
            def write(self, route, params):
                if route == 'repeat_task/submit':
                    self.writes += 1
                    task = loads(params['v'])
                    task.update(id=30, count=0, status=1, packid=300)
                    self.data['repeat'] = [task]
                    return {}
                return super().write(route, params)
        backend = TaskBackend()
        engine = Engine(backend, '123', self.state)
        engine.account_review()
        command = {'action': 'repeat_create', 'kind': 'expense', 'book_id': '1', 'account_id': '10', 'category_id': '20', 'amount': '0.01', 'start_date': '2026-10-21', 'repeat_unit': 'day', 'end_count': 1, 'clock': '08:00'}
        self.assertEqual(engine.execute('task', command)['state'], 'verified')
        result = engine.account_review()['account_review']
        self.assertTrue(result['ready'], result)
        self.assertEqual(engine.execute('ordinary', expense())['state'], 'verified')

    def test_verified_debt_history_loan_delta_is_known_not_external_drift(self):
        class DebtBackend(FullBackend):
            def write(self, route, params):
                self.writes += 1
                new = loads(loads(params['v'])['bills']['changelist'])[0]
                old = self.data['bills'][0]
                delta = new['money'] - old['money']
                self.data['bills'] = [new]
                self.data['assets'][0]['money'] -= delta
                self.data['assets'][-1]['money'] += delta
                self.data['assets'][-1]['loan']['totalpay'] += delta
                return {}
        backend = DebtBackend()
        debt = {'id': 12, 'userid': '123', 'name': 'Debt', 'type': 5, 'stype': 51, 'currency': 'CNY', 'status': 0, 'money': Decimal('-.04'), 'loan': {'money': Decimal('-.06'), 'totalpay': Decimal('.02'), 'startdate': '2026-10-18', 'enddate': ''}}
        backend.data['assets'].append(debt)
        row = make_row('123', '1', '100', 1792281600, 9)
        row.update(money=Decimal('.02'), assetid=12, fromid=10, status=1)
        backend.data['bills'] = [row]
        engine = Engine(backend, '123', self.state)
        engine.account_review()
        command = {'action': 'debt_bill_update', 'object_id': '100', 'expected_version': digest(row), 'related_id': '12', 'related_version': digest(debt), 'amount': '0.01'}
        result = engine.execute('debt', command)
        plan = engine.journal.get('debt')['plan']
        self.assertTrue(engine.verify(plan, engine.snapshot(True), 'debt')['native_fields_verified'])
        self.assertEqual(result['state'], 'verified', result)
        self.assertTrue(engine.account_review()['account_review']['ready'])

    def test_first_execute_cannot_leave_successful_account_unwatched(self):
        backend = FullBackend()
        engine = Engine(backend, '123', self.state)
        self.assertEqual(engine.execute('first', expense())['state'], 'verified')
        self.assertIn('10', engine.journal.watch_state()['watchpoints'])
        backend.data['assets'][0]['money'] -= Decimal('.20')
        result = engine.account_review()['account_review']
        self.assertFalse(result['ready'], result)
        self.assertTrue(any(a['account_id'] == '10' and a['code'] == 'account_drift_unexplained' for a in result['accounts']), result)

    def test_known_catalog_pending_does_not_owner_halt_unrelated_book(self):
        backend = FullBackend()
        engine = Engine(backend, '123', self.state)
        engine.account_review()
        backend.data['books'].append({'bookid': 2, 'name': 'Second', 'userid': '123'})
        command = {'action': 'book_rename', 'object_id': '2', 'name': 'Renamed', 'expected_version': digest(backend.data['books'][-1])}
        plan = prepare(command, backend.data, '123')
        with engine.journal.lock():
            engine.journal.start('unrelated-catalog', 'h', plan)
        scope = classify_pending({'request_id': 'unrelated-catalog', 'plan': plan}, backend.data)
        self.assertTrue(scope['complete'])
        self.assertEqual(scope['catalog_refs'], ['book:2'])
        result = engine.execute('book-one-expense', expense())
        self.assertEqual(result['state'], 'verified', result)


    def test_repeat_account_move_then_delete_advances_old_and_new_accounts(self):
        class Tasks(FullBackend):
            def read(self, route, params):
                if route == 'repeat_task/list':
                    return {'list': copy.deepcopy(self.data['repeat']), 'hasmore': 0}
                return super().read(route, params)
            def write(self, route, params):
                if route == 'repeat_task/submit':
                    self.writes += 1
                    row = loads(params['v']); row.update(id=30, count=0, status=1, packid=300)
                    self.data['repeat'] = [row]; return {}
                if route == 'repeat_task/delete':
                    self.writes += 1; self.data['repeat'] = []; return {}
                return super().write(route, params)
        backend = Tasks(); engine = Engine(backend, '123', self.state)
        command = {'action': 'repeat_create', 'kind': 'expense', 'book_id': '1', 'account_id': '10', 'category_id': '20', 'amount': '0.01', 'start_date': '2026-10-21', 'repeat_unit': 'day', 'end_count': 1, 'clock': '08:00'}
        self.assertEqual(engine.execute('create-task', command)['state'], 'verified')
        row = backend.data['repeat'][0]
        self.assertEqual(engine.execute('move-task', {'action':'repeat_update', 'object_id':'30', 'expected_version':digest(row), 'account_id':'11'})['state'], 'verified')
        self.assertTrue(engine.account_review()['account_review']['ready'])
        row = backend.data['repeat'][0]
        self.assertEqual(engine.execute('delete-task', {'action':'repeat_delete', 'object_id':'30', 'expected_version':digest(row)})['state'], 'verified')
        self.assertTrue(engine.account_review()['account_review']['ready'])

    def test_shared_credit_attach_advances_only_proved_member_relation(self):
        class Assets(FullBackend):
            def write(self, route, params):
                self.writes += 1; row = loads(params['v'])
                self.data['assets'] = [row if a['id'] == row['id'] else a for a in self.data['assets']]
                return {}
        backend=Assets()
        for row in backend.data['assets']:
            row.update(type=2, status=0, credit={'limit':Decimal('100'), 'shareid':-1})
        engine=Engine(backend,'123',self.state)
        engine.account_review()
        command={'action':'account_update','object_id':'10','expected_version':digest(backend.data['assets'][0]),'shared_limit_account_id':'11','shared_limit_version':digest(backend.data['assets'][1])}
        result=engine.execute('attach',command)
        self.assertEqual(result['state'],'verified',result)
        self.assertTrue(engine.account_review()['account_review']['ready'])

    def test_plain_bill_metadata_defaults_do_not_create_false_conflict(self):
        class Defaults(FullBackend):
            def write(self,*args):
                result=super().write(*args)
                self.data['bills'][-1].update(packid=None, extra={'flag':0})
                return result
        backend=Defaults();engine=Engine(backend,'123',self.state)
        self.assertEqual(engine.execute('defaults',expense())['state'],'verified')
        self.assertTrue(engine.account_review()['account_review']['ready'])

    def test_known_rename_still_rejects_unrequested_loan_field(self):
        class UnrelatedLoan(FullBackend):
            def write(self,route,params):
                self.writes+=1;row=loads(params['v']);row['loan']={'money':-1}
                self.data['assets'][0]=row;return {}
        backend=UnrelatedLoan();engine=Engine(backend,'123',self.state)
        result=engine.execute('rename-loan',{'action':'account_rename','object_id':'10','expected_version':digest(backend.data['assets'][0]),'name':'Renamed'})
        self.assertEqual(result['state'],'pending_verification')
        self.assertTrue(engine.journal.active_halts())


if __name__ == '__main__':
    unittest.main(verbosity=2)
