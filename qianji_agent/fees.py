"""Reject fee conversions the native single currency ratio cannot represent."""
from decimal import Decimal,ROUND_HALF_UP

def check_fee_conversion(principal,base,fee,fee_base):
 gross_source=principal+fee;gross_base=base+fee_base
 # Native Bill.getTransFeeStat uses fee * curr.bv / curr.sv.
 native_fee=fee*gross_base/gross_source
 cent=Decimal('.01')
 if native_fee.quantize(cent,rounding=ROUND_HALF_UP)!=fee_base or (gross_base-native_fee).quantize(cent,rounding=ROUND_HALF_UP)!=base:raise ValueError('fee_conversion_inconsistent')
