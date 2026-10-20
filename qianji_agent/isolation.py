"""Legacy plan annotation; all active dependency decisions use continuation.decide."""
from .dispatch import REJECTIONS
from .codec import digest,loads
from .operations import native_equal

FIELDS=('id','userid','type','stype','currency','status','loan','credit')
def plain_account(asset):
 return asset.get('type')==1 and asset.get('currency','CNY')=='CNY' and not asset.get('loan') and not asset.get('credit') and asset.get('status') in {None,0,-1}
def account_version(asset):return digest({k:asset.get(k) for k in FIELDS})
def annotate(plan,before):
 if plan.get('action')!='bill_create' or plan.get('row',{}).get('type') not in {0,1} or len(plan.get('balances',{}))!=1:return
 ids=set(str(i) for i in plan['balances']);assets=[a for a in before['assets'] if str(a['id']) in ids]
 if len(assets)==1 and plain_account(assets[0]):plan['independence_scope']={str(a['id']):account_version(a) for a in assets}

def can_continue(pending,command,before=None):
 """Compatibility helper; no historical exemptions without the durable policy context."""
 if before is None:return False
 from .continuation import decide
 return decide(pending,command,before,{'historical_requests':[]},[])['allowed']
