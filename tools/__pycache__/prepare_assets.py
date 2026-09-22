# Run with: blender --background --python tools/prepare_assets.py
# ZUSMO FF runtime asset builder - TERRAIN_FIX_V3
import bpy, os, math, glob, json, hashlib
from pathlib import Path

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
MAP_DIR = os.path.join(ROOT, 'assets', 'map')
CHAR_DIR = os.path.join(ROOT, 'assets', 'character')
MAX_PART_BYTES = 20_000_000
TERRAIN_NAMES = {
    'Main_Large_Terrain02',
    'Main_Large_Terrain03',
    'Main_Large_Terrain04',
    'Main_Large_Terrain05',
}
BAKE_SIZE = 1024


def rebuild_source_blend():
    direct = os.path.join(MAP_DIR, 'source.blend')
    if os.path.exists(direct):
        return direct, False
    parts = sorted(glob.glob(os.path.join(MAP_DIR, 'source.blend.part[0-9][0-9][0-9]')))
    if not parts:
        raise FileNotFoundError('Missing source.blend and source.blend.partNNN files')
    rebuilt = os.path.join(MAP_DIR, '_source.rebuilt.blend')
    print('Rebuilding source.blend temporarily from', len(parts), 'parts...')
    with open(rebuilt, 'wb') as out:
        for part in parts:
            print('  +', os.path.basename(part))
            with open(part, 'rb') as src:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
    return rebuilt, True


def remove_split_artifacts(path):
    for old in glob.glob(path + '.part*'):
        try:
            os.remove(old)
        except OSError:
            pass
    manifest = path + '.parts.json'
    if os.path.exists(manifest):
        try:
            os.remove(manifest)
        except OSError:
            pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def split_web_asset(path):
    remove_split_artifacts(path)
    size = os.path.getsize(path)
    cache_key = sha256_file(path)[:20]
    if size <= MAX_PART_BYTES:
        print(os.path.basename(path), 'is', size, 'bytes; no split needed. cacheKey=', cache_key)
        return

    part_names = []
    with open(path, 'rb') as src:
        index = 0
        while True:
            data = src.read(MAX_PART_BYTES)
            if not data:
                break
            name = os.path.basename(path) + '.part%03d' % index
            part_path = os.path.join(os.path.dirname(path), name)
            with open(part_path, 'wb') as dst:
                dst.write(data)
            part_names.append(name)
            print('Created', name, len(data), 'bytes')
            index += 1

    manifest = {
        'version': 2,
        'original': os.path.basename(path),
        'totalBytes': size,
        'partSizeLimit': MAX_PART_BYTES,
        'cacheKey': cache_key,
        'parts': part_names,
    }
    with open(path + '.parts.json', 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)
    os.remove(path)
    print('Removed oversized', os.path.basename(path), '; runtime will load split parts. cacheKey=', cache_key)


def select_only(obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.hide_set(False)
    obj.hide_render = False
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def get_principled(mat):
    if not mat or not mat.use_nodes or not mat.node_tree:
        return None
    for node in mat.node_tree.nodes:
        if node.type == 'BSDF_PRINCIPLED':
            return node
    return None


def best_diffuse_image_for_object(obj):
    """Find a real terrain albedo, explicitly rejecting masks/normal/roughness/lightmaps."""
    bad = ('mask', 'lightmap', 'shadow', 'normal', '_nor', '_n.', '_n_', 'rough', '_s.', '_s_', 'spec', 'metal', 'ao')
    scored = []

    def score_image(img, node=None):
        if not img:
            return
        name = (img.name or '').lower()
        if any(x in name for x in bad):
            return
        score = 0
        if 'terrain_ground' in name:
            score += 100
        if 'ground' in name:
            score += 50
        if '_d' in name or name.endswith('d.png'):
            score += 35
        if 'grass' in name:
            score += 10
        if node is not None:
            score += 20
        if score:
            scored.append((score, img, node))

    for slot in obj.material_slots:
        mat = slot.material
        if not mat or not mat.use_nodes or not mat.node_tree:
            continue
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE':
                score_image(node.image, node)

    # Packed terrain textures may exist in the .blend even when the material graph is unusual.
    for img in bpy.data.images:
        score_image(img, None)

    if not scored:
        return None, None
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1], scored[0][2]


def make_simple_terrain_material(obj, image=None, name_suffix='FALLBACK'):
    mat = bpy.data.materials.new(name=f'ZUSMO_Terrain_{obj.name}_{name_suffix}')
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.inputs['Roughness'].default_value = 0.88
    bsdf.inputs['Metallic'].default_value = 0.0
    if image is not None:
        try:
            image.colorspace_settings.name = 'sRGB'
        except Exception:
            pass
        tex = nt.nodes.new('ShaderNodeTexImage')
        tex.image = image
        tex.interpolation = 'Linear'
        nt.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
        if 'Alpha' in tex.outputs and 'Alpha' in bsdf.inputs:
            # Terrain must remain opaque. Do not connect alpha.
            bsdf.inputs['Alpha'].default_value = 1.0
    else:
        # Safe natural fallback instead of RGB mask colors.
        bsdf.inputs['Base Color'].default_value = (0.16, 0.20, 0.10, 1.0)
    nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])

    obj.data.materials.clear()
    obj.data.materials.append(mat)
    for poly in obj.data.polygons:
        poly.material_index = 0
    return mat


def bake_terrain_object(obj):
    print(f'[TERRAIN_FIX_V3] Processing {obj.name}')
    if obj.type != 'MESH':
        print(f'[TERRAIN_FIX_V3] SKIP {obj.name}: not a mesh')
        return False

    # Baking needs a UV target. Existing game terrain normally already has one.
    if not obj.data.uv_layers:
        print(f'[TERRAIN_FIX_V3] {obj.name}: no UV map; using diffuse fallback')
        img, _ = best_diffuse_image_for_object(obj)
        make_simple_terrain_material(obj, img, 'NO_UV')
        return False

    # Keep the current render UV as bake destination.
    uv = obj.data.uv_layers.active or obj.data.uv_layers[0]
    obj.data.uv_layers.active = uv
    try:
        uv.active_render = True
    except Exception:
        pass

    image = bpy.data.images.new(
        name=f'ZUSMO_BAKED_{obj.name}',
        width=BAKE_SIZE,
        height=BAKE_SIZE,
        alpha=False,
        float_buffer=False,
    )
    image.generated_color = (0.16, 0.20, 0.10, 1.0)
    try:
        image.colorspace_settings.name = 'sRGB'
    except Exception:
        pass

    targets = []
    valid_materials = 0
    for slot in obj.material_slots:
        mat = slot.material
        if mat is None:
            continue
        if not mat.use_nodes:
            mat.use_nodes = True
        if not mat.node_tree:
            continue
        valid_materials += 1
        node = mat.node_tree.nodes.new('ShaderNodeTexImage')
        node.name = f'ZUSMO_BAKE_TARGET_{obj.name}'
        node.label = 'ZUSMO terrain bake target'
        node.image = image
        node.select = True
        mat.node_tree.nodes.active = node
        targets.append((mat, node))

    if not valid_materials:
        print(f'[TERRAIN_FIX_V3] {obj.name}: no usable material nodes; using diffuse fallback')
        img, _ = best_diffuse_image_for_object(obj)
        make_simple_terrain_material(obj, img, 'NO_MATERIAL')
        return False

    select_only(obj)
    scene = bpy.context.scene
    old_engine = scene.render.engine
    try:
        scene.render.engine = 'CYCLES'
        scene.cycles.device = 'CPU'
        scene.cycles.samples = 1
        scene.render.bake.margin = 6
        scene.render.bake.use_clear = True
        scene.render.bake.use_pass_direct = False
        scene.render.bake.use_pass_indirect = False
        scene.render.bake.use_pass_color = True

        # DIFFUSE/COLOR evaluates the original Blender shader but strips lighting,
        # converting mask/layer terrain shaders into one ordinary albedo texture.
        bpy.ops.object.bake(type='DIFFUSE', pass_filter={'COLOR'})
        image.pack()
        make_simple_terrain_material(obj, image, 'BAKED')
        print(f'[TERRAIN_FIX_V3] BAKED OK {obj.name} -> {image.name} {BAKE_SIZE}x{BAKE_SIZE}')
        ok = True
    except Exception as exc:
        print(f'[TERRAIN_FIX_V3] BAKE FAILED {obj.name}: {exc}')
        img, node = best_diffuse_image_for_object(obj)
        if img:
            print(f'[TERRAIN_FIX_V3] FALLBACK {obj.name} -> {img.name}')
        else:
            print(f'[TERRAIN_FIX_V3] FALLBACK {obj.name} -> natural base color')
        make_simple_terrain_material(obj, img, 'FALLBACK')
        ok = False
    finally:
        try:
            scene.render.engine = old_engine
        except Exception:
            pass
        for mat, node in targets:
            try:
                if node.name in mat.node_tree.nodes:
                    mat.node_tree.nodes.remove(node)
            except Exception:
                pass
    return ok


def fix_terrain_materials():
    print('[TERRAIN_FIX_V3] START - converting terrain mask shaders to glTF-safe albedo materials')
    found = []
    for name in sorted(TERRAIN_NAMES):
        obj = bpy.data.objects.get(name)
        if obj:
            found.append(obj)
    # Also catch Blender-renamed variants if present.
    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH' and obj.name.startswith('Main_Large_Terrain') and obj not in found:
            found.append(obj)

    if not found:
        print('[TERRAIN_FIX_V3] WARNING: no Main_Large_Terrain objects found')
        return

    success = 0
    for obj in found:
        if bake_terrain_object(obj):
            success += 1
    print(f'[TERRAIN_FIX_V3] DONE - baked {success}/{len(found)} terrain objects; all terrain materials sanitized')


# MAP
blend_path, temporary_blend = rebuild_source_blend()
bpy.ops.wm.open_mainfile(filepath=blend_path)

# This is the important texture fix. It MUST run before glTF export.
fix_terrain_materials()

map_glb = os.path.join(MAP_DIR, 'map.glb')
remove_split_artifacts(map_glb)
if os.path.exists(map_glb):
    os.remove(map_glb)

bpy.ops.export_scene.gltf(
    filepath=map_glb,
    export_format='GLB',
    export_apply=True,
    export_texcoords=True,
    export_normals=True,
    export_materials='EXPORT'
)
split_web_asset(map_glb)
if temporary_blend:
    try:
        os.remove(blend_path)
    except OSError:
        pass

# CHARACTER
bpy.ops.wm.read_factory_settings(use_empty=True)
obj = os.path.join(CHAR_DIR, 'Free Fire T Shirt 3D Character Model.obj')
try:
    bpy.ops.wm.obj_import(filepath=obj)
except Exception:
    bpy.ops.import_scene.obj(filepath=obj)
meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
bpy.ops.object.join()
mesh = bpy.context.object

mesh.rotation_euler = (math.radians(90), 0, 0)
bpy.context.view_layer.objects.active = mesh
bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
dims = mesh.dimensions
scale = 1.78 / max(dims)
mesh.scale = (scale,) * 3
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

from mathutils import Vector
bb = [mesh.matrix_world @ Vector(c) for c in mesh.bound_box]
minz = min(v.z for v in bb)
cx = sum(v.x for v in bb) / 8
cy = sum(v.y for v in bb) / 8
mesh.location = (-cx, -cy, -minz)
bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)

bpy.ops.object.armature_add(enter_editmode=True, location=(0, 0, 0))
arm = bpy.context.object
arm.name = 'ZUSMO_RIG'
eb = arm.data.edit_bones
eb.remove(eb[0])


def bone(n, a, b, parent=None):
    x = eb.new(n)
    x.head = a
    x.tail = b
    x.parent = parent
    return x


hips = bone('Hips', (0, 0, .82), (0, 0, 1.02))
sp = bone('Spine', (0, 0, 1.02), (0, 0, 1.28), hips)
ch = bone('Chest', (0, 0, 1.28), (0, 0, 1.48), sp)
neck = bone('Neck', (0, 0, 1.48), (0, 0, 1.59), ch)
bone('Head', (0, 0, 1.59), (0, 0, 1.76), neck)
for s in (-1, 1):
    side = 'L' if s < 0 else 'R'
    ua = bone(side + 'UpperArm', (s * .13, 0, 1.45), (s * .39, 0, 1.39), ch)
    la = bone(side + 'LowerArm', (s * .39, 0, 1.39), (s * .61, 0, 1.25), ua)
    bone(side + 'Hand', (s * .61, 0, 1.25), (s * .72, 0, 1.20), la)
    ul = bone(side + 'UpperLeg', (s * .10, 0, .88), (s * .11, 0, .48), hips)
    ll = bone(side + 'LowerLeg', (s * .11, 0, .48), (s * .10, 0, .10), ul)
    bone(side + 'Foot', (s * .10, 0, .10), (s * .10, -.18, .04), ll)

bpy.ops.object.mode_set(mode='OBJECT')

# Deterministic skinning: avoids Bone Heat failure and Blender glTF skin crash.
for vg in list(mesh.vertex_groups):
    mesh.vertex_groups.remove(vg)
mesh.parent = arm
arm_mod = mesh.modifiers.new(name='ZUSMO_Armature', type='ARMATURE')
arm_mod.object = arm
arm_mod.use_vertex_groups = True

groups = {}
segments = []
for b in arm.data.bones:
    b.use_deform = True
    groups[b.name] = mesh.vertex_groups.new(name=b.name)
    segments.append((b.name, b.head_local.copy(), b.tail_local.copy()))


def point_segment_distance(p, a, b):
    ab = b - a
    denom = ab.length_squared
    if denom <= 1e-12:
        return (p - a).length
    t = max(0.0, min(1.0, (p - a).dot(ab) / denom))
    q = a + ab * t
    return (p - q).length


counts = {name: 0 for name in groups}
for v in mesh.data.vertices:
    p = v.co
    nearest_name = min(segments, key=lambda s: point_segment_distance(p, s[1], s[2]))[0]
    groups[nearest_name].add([v.index], 1.0, 'REPLACE')
    counts[nearest_name] += 1

if mesh.data.vertices:
    fallback_index = mesh.data.vertices[0].index
    for name, count in counts.items():
        if count == 0:
            groups[name].add([fallback_index], 0.0001, 'ADD')

mesh.select_set(True)
arm.select_set(True)
bpy.context.view_layer.objects.active = arm
print('Character skin weights created deterministically.')


def clip(name, frames, run=False, jump=False):
    act = bpy.data.actions.new(name)
    arm.animation_data_create()
    arm.animation_data.action = act
    for f in frames:
        t = f / frames[-1] * math.tau if frames[-1] else 0
        for n in ['LUpperLeg', 'RUpperLeg', 'LUpperArm', 'RUpperArm', 'LLowerLeg', 'RLowerLeg']:
            p = arm.pose.bones.get(n)
            p.rotation_mode = 'XYZ'
            p.rotation_euler = (0, 0, 0)
        if jump:
            k = math.sin(math.pi * f / frames[-1])
            arm.pose.bones['LUpperLeg'].rotation_euler.x = -.35 * k
            arm.pose.bones['RUpperLeg'].rotation_euler.x = -.35 * k
        elif name != 'IDLE':
            amp = .75 if run else .42
            arm.pose.bones['LUpperLeg'].rotation_euler.x = math.sin(t) * amp
            arm.pose.bones['RUpperLeg'].rotation_euler.x = -math.sin(t) * amp
            arm.pose.bones['LUpperArm'].rotation_euler.x = -math.sin(t) * amp * .7
            arm.pose.bones['RUpperArm'].rotation_euler.x = math.sin(t) * amp * .7
        for p in arm.pose.bones:
            p.keyframe_insert('rotation_euler', frame=f)
    return act


for n, fr, r, j in [
    ('IDLE', [1, 30], 0, 0),
    ('WALK', [1, 15, 30], 0, 0),
    ('RUN', [1, 10, 20], 1, 0),
    ('JUMP_START', [1, 8], 0, 1),
    ('JUMP_AIR', [1, 12], 0, 1),
    ('JUMP_LAND', [1, 8], 0, 1),
]:
    clip(n, fr, r, j)

arm.animation_data.action = None
for act in bpy.data.actions:
    tr = arm.animation_data.nla_tracks.new()
    tr.name = act.name
    tr.strips.new(act.name, int(act.frame_range[0]), act)

character_glb = os.path.join(CHAR_DIR, 'character_rigged.glb')
bpy.ops.export_scene.gltf(
    filepath=character_glb,
    export_format='GLB',
    export_animations=True,
    export_nla_strips=True,
    export_apply=True
)
split_web_asset(character_glb)
print('Prepared split-safe web assets. No generated GLB file will exceed 20,000,000 bytes.')
