"""Bounded PNG/JPEG decoding and exact oriented RGBA pixel identity."""
import hashlib,io,struct
from PIL import Image,ImageOps

MAX_PIXELS=24_000_000

def image_fingerprint(data):
 try:
  with Image.open(io.BytesIO(data),formats=['PNG','JPEG'])as image:
   if image.width<=0 or image.height<=0 or image.width*image.height>MAX_PIXELS:raise ValueError('image_pixel_limit_exceeded')
   if getattr(image,'n_frames',1)!=1:raise ValueError('animated_image_unsupported')
   image.verify()
  with Image.open(io.BytesIO(data),formats=['PNG','JPEG'])as image:
   image.load()
   pixels=ImageOps.exif_transpose(image).convert('RGBA')
   identity=hashlib.sha256(struct.pack('>II',pixels.width,pixels.height)+pixels.tobytes()).hexdigest()
   return (pixels.size,identity)
 except ValueError as error:
  if str(error)in ('image_pixel_limit_exceeded','animated_image_unsupported'):raise
  raise ValueError('invalid_image_content')from None
 except Exception:raise ValueError('invalid_image_content')from None
