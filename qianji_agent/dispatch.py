"""Private dispatch evidence and finite public diagnostics, never a replay policy."""
from .transport import QianjiError

REJECTIONS={'backend_rejected','feature_unavailable','reconnect_required'}
ERROR_CODES=REJECTIONS|{'backend_result_unknown','invalid_response','transport_failure','result_unknown','read_unavailable'}
VERIFY_CODES={'historical_balance_context_unattributed','account_drift_unexplained','object_not_verified','native_fields_not_verified','balance_not_verified',
 'task_data_not_verified','task_clock_not_verified','task_balance_not_verified','task_child_relation_not_verified',
 'installment_remaining_not_verified','installment_child_relation_not_verified',
 'debt_history_not_verified','debt_origin_not_verified','deletion_not_verified',
 'native_deletion_event_missing','native_prepay_bills_not_verified','native_prepay_state_not_verified',
 'native_tags_not_verified','native_transition_not_verified','owner_mismatch',
 'refund_child_not_verified','refund_cumulative_relation_not_verified','refund_markers_not_verified',
 'refund_source_relation_not_verified','related_native_bill_not_verified','scheduled_task_changed',
 'shared_credit_parent_changed','unexpected_copy_metadata',
 'historical_schedule_bill_changed','native_currency_not_verified','native_images_not_verified',
 'native_flags_or_fee_not_verified','incomplete_sync',
 'read_unavailable','result_unknown','backend_result_unknown','transport_failure',
 'reconnect_required','feature_unavailable','invalid_response'}
SECRET_KEYS={'authorization','proxyauthorization','cookie','setcookie','utoken','tok','token',
 'accesstoken','refreshtoken','password','passwd','secret','headers','session','sessionid','devicetoken'}

def private_response(value,depth=0):
 if depth>32:return '[depth-limited]'
 if isinstance(value,dict):
  return {k:private_response(v,depth+1) for k,v in value.items()
          if isinstance(k,str) and ''.join(c for c in k.lower() if c.isalnum()) not in SECRET_KEYS}
 if isinstance(value,list):return [private_response(v,depth+1) for v in value]
 return value

def dispatch_success(response):
 return {'outcome':'response_received','response':private_response(response)}

def dispatch_error(error):
 code=error.code if isinstance(error,QianjiError) and error.code in ERROR_CODES else 'result_unknown'
 backend=isinstance(error,QianjiError) and code not in {'transport_failure','result_unknown','read_unavailable'}
 result={'outcome':'backend_error' if backend else 'transport_unknown','error_code':code}
 name=(getattr(error,'cause_type',None) if isinstance(error,QianjiError) else None) or type(error).__name__
 result['exception_type']=name if name in {'QianjiError','TimeoutError','OSError','ConnectionError','URLError','HTTPError','SSLError','JSONDecodeError'} else 'Exception'
 response=getattr(error,'response',None) if isinstance(error,QianjiError) else None
 if response is not None:result['response']=private_response(response)
 return result

def verification_code(error):
 code=error.code if isinstance(error,QianjiError) else str(error)
 return code if code in VERIFY_CODES else 'verification_incomplete'
