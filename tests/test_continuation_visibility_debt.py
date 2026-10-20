"""Synthetic recheck only. All journals are temporary; no real transport."""
import copy
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from test_account_review import FullBackend
from qianji_agent.codec import digest, loads
from qianji_agent.engine import Engine


class VisibilityBackend(FullBackend):
    changed_currency = False

    def read(self, route, params):
        if route == "asset/info":
            return copy.deepcopy(next(a for a in self.data["assets"] if str(a["id"]) == str(params["did"])))
        return super().read(route, params)

    def write(self, route, params):
        if route != "asset/visible":
            raise AssertionError("Unexpected synthetic route")
        self.writes += 1
        row = next(a for a in self.data["assets"] if str(a["id"]) == str(params["did"]))
        row["status"] = 0 if row["status"] == 2 else 2
        if self.changed_currency:
            row["currency"] = "USD"
        return {}


class DebtBackend(FullBackend):
    wrong_finish_date = False

    def read(self, route, params):
        if route == "asset/info":
            return copy.deepcopy(next(a for a in self.data["assets"] if str(a["id"]) == str(params["did"])))
        return super().read(route, params)

    def write(self, route, params):
        self.writes += 1
        debt = self.data["assets"][-1]
        if route == "asset/finish":
            debt["status"] = 1
            debt["loan"]["enddate"] = "1999-01-01" if self.wrong_finish_date else params["v"]
            return {}
        if route != "bill/syncall":
            raise AssertionError("Unexpected synthetic route")
        rows = loads(loads(params["v"])["bills"]["changelist"])
        self.data["bills"].extend(rows)
        cash = self.data["assets"][0]
        for row in rows:
            amount = row["money"]
            if row["type"] == 6:  # Additional principal borrowed.
                cash["money"] += amount
                debt["money"] -= amount
                debt["loan"]["money"] -= amount
            elif row["type"] == 9:  # Principal repaid.
                cash["money"] -= amount
                debt["money"] += amount
                debt["loan"]["totalpay"] += amount
            else:
                raise AssertionError("Unexpected synthetic bill type")
        return {}


class RecheckBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "journal"

    def test_hidden_shared_child_restore_advances_proven_parent_projection(self):
        backend = VisibilityBackend()
        child, parent = backend.data["assets"]
        child.update(type=2, status=2, credit={"limit": Decimal(100), "shareid": 11})
        parent.update(type=2, status=0, credit={"limit": Decimal(100), "shareid": -1})
        engine = Engine(backend, "123", self.state)
        engine.account_review()
        result = engine.execute("restore", {
            "action": "account_restore", "object_id": "10", "expected_version": digest(child)})
        proof = engine.verify(engine.journal.get("restore")["plan"], engine.snapshot(True), "restore")
        self.assertTrue(proof["native_fields_verified"])
        self.assertEqual(result["state"], "verified", result)
        self.assertTrue(engine.account_review()["account_review"]["ready"])

    def test_hidden_restore_must_not_absorb_unrequested_currency(self):
        backend = VisibilityBackend()
        backend.changed_currency = True
        backend.data["assets"][0]["status"] = 2
        engine = Engine(backend, "123", self.state)
        engine.account_review()
        result = engine.execute("restore", {
            "action": "account_restore", "object_id": "10",
            "expected_version": digest(backend.data["assets"][0])})
        self.assertEqual(result["state"], "pending_verification", result)
        self.assertTrue(engine.journal.active_halts())

    def test_archive_must_not_absorb_unrequested_currency(self):
        backend = VisibilityBackend()
        backend.changed_currency = True
        backend.data["assets"][0]["status"] = 0
        engine = Engine(backend, "123", self.state)
        engine.account_review()
        result = engine.execute("archive", {
            "action": "account_archive", "object_id": "10",
            "expected_version": digest(backend.data["assets"][0])})
        self.assertEqual(result["state"], "pending_verification", result)
        self.assertTrue(engine.journal.active_halts())

    def test_known_archive_keeps_hidden_account_under_late_drift_monitoring(self):
        backend=VisibilityBackend();backend.data['assets'][0]['status']=0
        engine=Engine(backend,'123',self.state)
        result=engine.execute('archive-known',{'action':'account_archive','object_id':'10','expected_version':digest(backend.data['assets'][0])})
        self.assertEqual(result['state'],'verified',result)
        self.assertTrue(engine.account_review()['account_review']['ready'])
        backend.data['assets'][0]['money']-=Decimal('.20')
        review=engine.account_review()['account_review']
        self.assertFalse(review['ready'])
        self.assertTrue(any(a['account_id']=='10' and a['state']=='halted' for a in review['accounts']))

    def test_shared_restore_cannot_absorb_unrequested_parent_balance(self):
        class ParentChange(VisibilityBackend):
            def write(self,*args):
                result=super().write(*args)
                self.data['assets'][1]['money']+=Decimal('.20')
                return result
        backend=ParentChange();child,parent=backend.data['assets']
        child.update(type=2,status=2,credit={'limit':Decimal(100),'shareid':11})
        parent.update(type=2,status=0,credit={'limit':Decimal(100),'shareid':-1})
        engine=Engine(backend,'123',self.state)
        result=engine.execute('restore-parent-balance',{'action':'account_restore','object_id':'10','expected_version':digest(child)})
        self.assertEqual(result['state'],'pending_verification',result)
        self.assertTrue(engine.journal.active_halts())

    def debt_backend(self, zero=False):
        backend = DebtBackend()
        backend.data["assets"].append({
            "id": 12, "userid": "123", "name": "Debt", "type": 5, "stype": 51,
            "currency": "CNY", "status": 0, "money": Decimal("0" if zero else "-.04"),
            "loan": {"money": Decimal("-.06"), "totalpay": Decimal(".06" if zero else ".02"),
                     "startdate": "2026-10-18", "enddate": ""}})
        return backend

    def debt_change(self, action):
        backend = self.debt_backend()
        engine = Engine(backend, "123", self.state)
        engine.account_review()
        command = {
            "action": action, "object_id": "12", "book_id": "1", "account_id": "10",
            "amount": "0.01", "time": "2026-10-18T08:00:00+08:00",
            "expected_version": digest(backend.data["assets"][-1])}
        result = engine.execute(action, command)
        proof = engine.verify(engine.journal.get(action)["plan"], engine.snapshot(True), action)
        self.assertTrue(proof["native_fields_verified"])
        self.assertEqual(result["state"], "verified", result)
        self.assertTrue(engine.account_review()["account_review"]["ready"])

    def test_debt_add_advances_verified_principal_total(self):
        self.debt_change("debt_add")

    def test_debt_pay_advances_verified_total_paid(self):
        self.debt_change("debt_pay")

    def finish_debt(self, wrong=False):
        backend = self.debt_backend(zero=True)
        backend.wrong_finish_date = wrong
        engine = Engine(backend, "123", self.state)
        engine.account_review()
        result = engine.execute("finish", {
            "action": "debt_finish", "object_id": "12", "end_date": "2026-10-20",
            "expected_version": digest(backend.data["assets"][-1])})
        return engine, result

    def test_debt_finish_legitimate_enddate_removes_active_watchpoint(self):
        engine, result = self.finish_debt()
        self.assertEqual(result["state"], "verified", result)
        self.assertTrue(engine.account_review()["account_review"]["ready"])

    def test_debt_finish_must_verify_requested_enddate(self):
        engine, result = self.finish_debt(wrong=True)
        self.assertEqual(result["state"], "pending_verification", result)
        self.assertTrue(engine.journal.active_halts())


if __name__ == "__main__":
    unittest.main(verbosity=2)
