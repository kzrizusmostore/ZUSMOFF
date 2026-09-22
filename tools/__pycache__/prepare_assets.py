# Run with: blender --background --python tools/prepare_assets.py
import bpy, os, math, glob, json
from pathlib import Path

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
MAP_DIR = os.path.join(ROOT, 'assets', 'map')
CHAR_DIR = os.path.join(ROOT, 'assets', 'character')
MAX_PART_BYTES = 20_000_000


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


def split_web_asset(path):
    remove_split_artifacts(path)
    size = os.path.getsize(path)
    if size <= MAX_PART_BYTES:
        print(os.path.basename(path), 'is', size, 'bytes; no split needed.')
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
        'version': 1,
        'original': os.path.basename(path),
        'totalBytes': size,
        'partSizeLimit': MAX_PART_BYTES,
        'parts': part_names,
    }
    with open(path + '.parts.json', 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)
    os.remove(path)
    print('Removed oversized', os.path.basename(path), '; runtime will load split parts.')


# MAP
blend_path, temporary_blend = rebuild_source_blend()
bpy.ops.wm.open_mainfile(filepath=blend_path)
map_glb = os.path.join(MAP_DIR, 'map.glb')
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
bpy.ops.wm.obj_import(filepath=obj)
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

# Deterministic skinning: avoid Bone Heat failure and Blender 4.0 glTF exporter crash.
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

# Procedural animation clips.
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
