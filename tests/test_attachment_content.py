"""Corrupt bytes and native lossless CDN variants must not misstate evidence."""
import hashlib,io,struct,tempfile,unittest,zlib
from pathlib import Path
from unittest.mock import patch
from PIL import Image,PngImagePlugin,ImageOps
from qianji_agent import attachments
from qianji_agent.transport import QianjiError
from qianji_agent.models import Receipt
from qianji_agent.engine import Engine
from test_engine import Backend

def png(color=(20,40,60,255),metadata=False):
 image=Image.new('RGBA',(3,2),color);out=io.BytesIO()
 info=PngImagePlugin.PngInfo()
 if metadata:info.add_text('Comment','same pixels, different file metadata')
 image.save(out,format='PNG',pnginfo=info,compress_level=1 if metadata else 9)
 return out.getvalue()

class Response(io.BytesIO):
 def __enter__(self):return self
 def __exit__(self,*args):self.close()
class Opener:
 def __init__(self,data):self.data=data;self.requests=[]
 def open(self,request,timeout):self.requests.append(request);return Response(self.data)

class AttachmentContentTests(unittest.TestCase):
 def test_corrupt_png_crc_is_refused_before_upload(self):
  data=bytearray(png());pos=data.index(b'IDAT');data[pos+4]^=1
  with tempfile.TemporaryDirectory()as directory:
   path=Path(directory)/'broken.png';path.write_bytes(data)
   with self.assertRaises(ValueError):attachments.image_bytes(str(path))
 def test_jpeg_markers_do_not_make_non_image_bytes_valid(self):
  with tempfile.TemporaryDirectory()as directory:
   path=Path(directory)/'broken.jpg';path.write_bytes(b'\xff\xd8not-a-jpeg\xff\xd9')
   with self.assertRaises(ValueError):attachments.image_bytes(str(path))
 def test_decompression_pixel_limit_is_enforced_before_large_decode(self):
  def chunk(t,v):return struct.pack('>I',len(v))+t+v+struct.pack('>I',zlib.crc32(t+v)&0xffffffff)
  data=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',8000,8000,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\0\0\0\0'))+chunk(b'IEND',b'')
  with tempfile.TemporaryDirectory()as directory:
   path=Path(directory)/'huge.png';path.write_bytes(data)
   with self.assertRaises(ValueError):attachments.image_bytes(str(path))
 def test_animated_png_is_not_silently_verified_as_its_first_frame(self):
  out=io.BytesIO();Image.new('RGBA',(2,2),'red').save(out,format='PNG',save_all=True,append_images=[Image.new('RGBA',(2,2),'blue')],duration=50,loop=0)
  with tempfile.TemporaryDirectory()as directory:
   path=Path(directory)/'animated.png';path.write_bytes(out.getvalue())
   with self.assertRaises(ValueError):attachments.image_bytes(str(path))
 def invoke(self,source,download,remove_source=False):
  with tempfile.TemporaryDirectory()as directory:
   path=Path(directory)/'test.png';path.write_bytes(source)
   plan={'storage_key':'a'*32,'sha256':hashlib.sha256(source).hexdigest(),'image_path':str(path)}
   if remove_source:path.unlink()
   opener=Opener(download)
   with patch('qianji_agent.attachments.urllib.request.build_opener',return_value=opener):
    try:result=attachments.verify_upload(plan)
    except QianjiError:result={}
   return result,opener.requests
 def test_native_lossless_variant_verifies_pixels_without_claiming_original_bytes(self):
  result,requests=self.invoke(png(),png(metadata=True))
  self.assertIs(result.get('image_pixels_verified'),True)
  self.assertIs(result.get('file_content_verified'),False)
  self.assertEqual(result.get('download_variant'),'native_huge')
  self.assertEqual(requests[0].full_url,'https://billimg.qianjiapp.com/'+'a'*32+'!huge')
  self.assertNotIn('Authorization',requests[0].headers)
  Receipt.model_validate({'state':'verified',**result})
 def test_one_changed_pixel_is_not_equivalent_downloaded_content(self):
  result,_=self.invoke(png(),png(color=(21,40,60,255)))
  self.assertFalse(result.get('image_pixels_verified',False))
  self.assertFalse(result.get('file_content_verified',False))
 def test_raw_byte_match_remains_verifiable_after_original_local_file_removed(self):
  source=png();result,_=self.invoke(source,source,remove_source=True)
  self.assertIs(result.get('file_content_verified'),True)
  self.assertIs(result.get('image_pixels_verified'),True)
 def test_palette_and_rgb_encodings_can_describe_exactly_the_same_pixels(self):
  source=png();out=io.BytesIO()
  with Image.open(io.BytesIO(source))as image:image.convert('P').save(out,format='PNG')
  result,_=self.invoke(source,out.getvalue())
  self.assertIs(result.get('image_pixels_verified'),True)
  self.assertIs(result.get('file_content_verified'),False)
 def test_corrupt_input_returns_actionable_error_and_creates_no_dispatch_record(self):
  with tempfile.TemporaryDirectory()as directory:
   path=Path(directory)/'bad.jpg';path.write_bytes(b'\xff\xd8not-a-jpeg\xff\xd9')
   backend=Backend();engine=Engine(backend,'123',Path(directory)/'state')
   result=engine.execute('bad-image',{'action':'attachment_upload','image_path':str(path)})
   self.assertEqual(result['state'],'not_executed')
   self.assertEqual(result['code'],'invalid_image_content')
   self.assertEqual(backend.writes,0)
   self.assertIsNone(engine.journal.get('bad-image'))
 def test_storage_ack_is_not_reported_as_pixel_or_byte_verification(self):
  with tempfile.TemporaryDirectory()as directory:
   path=Path(directory)/'valid.png';path.write_bytes(png())
   backend=Backend();backend.upload=lambda plan:{'key':plan['storage_key'],'hash':plan['etag']}
   engine=Engine(backend,'123',Path(directory)/'state')
   with patch('qianji_agent.attachments.verify_upload',side_effect=QianjiError('upload_not_verified')):
    result=engine.execute('storage-only',{'action':'attachment_upload','image_path':str(path)})
   self.assertEqual(result['state'],'verified')
   self.assertIs(result['storage_hash_verified'],True)
   self.assertIs(result['file_content_verified'],False)
   self.assertIs(result['image_pixels_verified'],False)
   self.assertIsNone(result.get('download_variant'))

if __name__=='__main__':unittest.main()
