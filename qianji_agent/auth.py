"""Read-only bootstrap of the user's logged-in official macOS App."""
import base64,datetime,hashlib,json,plistlib,subprocess,urllib.parse
from pathlib import Path
from dataclasses import dataclass
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
from .transport import QianjiError

@dataclass(frozen=True,repr=False)
class Session:
 uid:str
 headers:dict
 salts:tuple
 build:str
 base_currency:str='CNY'
 def __repr__(self):return '<Session: private in-memory connection>'

def load_session(app=None,prefs_path=None,profile=None):
 app=Path(app) if app else Path('/Applications/MoneyTrack.app/Contents')
 prefs_path=Path(prefs_path) if prefs_path else Path.home()/'Library/Containers/com.mutangtech.qianji.fltios/Data/Library/Preferences/com.mutangtech.qianji.fltios.plist'
 profile=profile or json.loads((Path(__file__).parent/'profiles/mac-1580.json').read_text())
 try:
  binary=app/'Frameworks/App.framework/Versions/A/App'
  if hashlib.sha256(binary.read_bytes()).hexdigest()!=profile['sha256']:raise QianjiError('adapter_update_required')
  info=plistlib.loads((app/'Info.plist').read_bytes())
  if info['CFBundleIdentifier']!='com.mutangtech.qianji.fltios' or str(info['CFBundleVersion'])!=profile['build']:raise QianjiError('adapter_update_required')
  try:prefs=plistlib.loads(prefs_path.read_bytes())
  except FileNotFoundError:raise QianjiError('app_login_required') from None
  host=prefs.get('flutter.configkit__api_host','https://api.qianjiapp.com/')
  if host.rstrip('/')!='https://api.qianjiapp.com':raise QianjiError('unexpected_destination')
  def decrypt(value):
   c=Cipher(algorithms.AES(base64.b64decode(profile['key'],validate=True)),modes.CTR(base64.b64decode(profile['iv'],validate=True))).decryptor()
   raw=c.update(base64.b64decode(value,validate=True))+c.finalize()
   pad=raw[-1]
   if not 1<=pad<=16 or raw[-pad:]!=bytes([pad])*pad:raise ValueError('bad_padding')
   return raw[:-pad].decode()
  try:
   user=json.loads(decrypt(prefs['flutter.u_account_datav2']));uid=str(user['id'])
   token=decrypt(prefs['flutter.u_actok2_'+uid]);device=prefs['flutter.local_device_id']
   if not uid or len(uid)>128 or not token or not isinstance(device,str) or not device:raise ValueError()
  except Exception:raise QianjiError('app_login_required') from None
  def command(*args):return subprocess.run(args,check=True,capture_output=True,text=True).stdout.strip()
  os_version=command('sw_vers','-productVersion');os_build=command('sw_vers','-buildVersion');model=command('sysctl','-n','hw.model')
  quote=lambda v:urllib.parse.quote(str(v),safe='')
  offset=int(datetime.datetime.now().astimezone().utcoffset().total_seconds())
  headers={'Accept':'application/json','Content-Type':'application/x-www-form-urlencoded',
   'User-Agent':'Dart/'+profile['dart']+' (dart:io)','VS':profile['build'],'VSN':quote(info['CFBundleShortVersionString']),
   'devid':device,'os':'6','osvs':quote('Version '+os_version+' (Build '+os_build+')'),
   'Pkg':'com.mutangtech.qianji.fltios','Devbrand':'Apple','Devname':quote(model),'Mk':'fltmac',
   'Clang':'zh','CRegion':'CN','timezoneoffset':str(offset),'utoken':token}
  return Session(uid,headers,tuple(profile['salts']),profile['build'],prefs.get('flutter.'+uid+'_confu_basecur','CNY'))
 except QianjiError:raise
 except PermissionError:raise QianjiError('app_access_denied') from None
 except FileNotFoundError:raise QianjiError('app_not_installed') from None
 except Exception:raise QianjiError('app_state_unreadable') from None
