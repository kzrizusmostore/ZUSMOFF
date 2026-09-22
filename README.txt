ZUSMO FF - GITHUB SPLIT MAP EDITION
===================================

Project ini sudah disesuaikan agar file map besar tidak perlu di-upload sebagai satu file >25 MB.

SOURCE MAP
----------
Aset asli source.blend (~198 MB) sudah dipecah menjadi:
  assets/map/source.blend.part000
  assets/map/source.blend.part001
  ...
  assets/map/source.blend.part009

Setiap part maksimal 20,000,000 bytes (<25 MB).
JANGAN rename part-part tersebut.

PREPARE / BUILD ASSET
---------------------
1) Install Blender 4.x pada PC.
2) Dari folder ZUSMO_FF_GITHUB jalankan:

   blender --background --python tools/prepare_assets.py

Script akan:
- otomatis menyatukan source.blend.part* ke file sementara,
- membuka map asli,
- export map ke GLB,
- auto-rig karakter OBJ,
- export karakter ke GLB,
- otomatis memecah GLB apa pun yang >20 MB menjadi .part000, .part001, dst,
- membuat file .parts.json,
- menghapus GLB besar agar tidak ada file hasil build >20 MB.

Contoh hasil map jika besar:
  assets/map/map.glb.parts.json
  assets/map/map.glb.part000
  assets/map/map.glb.part001
  ...

Game di js/main.js sudah mendukung format split tersebut. Browser akan fetch semua part dan menyatukannya di memori sebelum GLTFLoader mem-parse model.

OPTIONAL: REBUILD SOURCE.BLEND MANUAL
-------------------------------------
Kalau ingin membuat source.blend utuh secara manual:

  python tools/rebuild_source_map.py

File source.blend hasil rebuild jangan di-upload ke GitHub karena ukurannya besar.

RUN WEBSITE
-----------
Serve lewat HTTP, jangan file://.
Contoh:

  python -m http.server 8080

Lalu buka:
  http://<IP-PC>:8080

atau deploy file project ke GitHub Pages / Netlify / Vercel.

CATATAN GITHUB
--------------
Untuk repo/deploy, setelah prepare_assets.py selesai kamu tidak wajib upload source.blend.part* jika hanya butuh game hasil jadi.
Cukup upload file website + hasil map.glb.part* / manifest + character_rigged GLB atau part-nya.

Controls:
- Mobile: joystick kiri, JUMP kanan, drag sisi kanan untuk kamera, fullscreen kanan atas.
- Desktop: WASD, Shift, Space, mouse drag.
