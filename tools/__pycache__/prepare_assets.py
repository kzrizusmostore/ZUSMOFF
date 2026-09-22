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


# Terrain material repair for web/glTF.
# The original Peak map uses a complex terrain shader (MixRGB + AllTerrainMask +
# lightmaps/normal maps). glTF cannot reproduce that Blender node graph 1:1 and
# the mask can appear as raw RGB (blue/green/red) on Android. We bake the final
# terrain color into ordinary PNG textures before exporting.
TERRAIN_NAME_HINTS = (
    'main_large_terrain',
    'large_terrain',
)
TERRAIN_BAKE_SIZE = 2048


def is_main_terrain_object(obj):
    if obj.type != 'MESH':
        return False
    name = obj.name.lower()
    mesh_name = (obj.data.name if obj.data else '').lower()
    return any(h in name or h in mesh_name for h in TERRAIN_NAME_HINTS)


def clear_mesh_color_attributes(mesh):
    # COLOR_0 in glTF multiplies Base Color. The original terrain uses color/mask
    # data for shader blending, so exporting it directly causes rainbow ground.
    try:
        attrs = mesh.color_attributes
        for attr in list(attrs):
            attrs.remove(attr)
    except Exception:
        try:
            vcols = mesh.vertex_colors
            for layer in list(vcols):
                vcols.remove(layer)
        except Exception:
            pass


def ensure_object_uv(obj):
    mesh = obj.data
    if len(mesh.uv_layers) > 0:
        mesh.uv_layers.active_index = 0
        return True

    print('  Terrain has no UV; creating Smart UV:', obj.name)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    try:
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.02)
        bpy.ops.object.mode_set(mode='OBJECT')
        return len(mesh.uv_layers) > 0
    except Exception as exc:
        print('  WARNING: could not create UV for', obj.name, exc)
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            pass
        return False


def image_name_score(image):
    if image is None:
        return -10_000
    name = (image.name + ' ' + (getattr(image, 'filepath', '') or '')).lower()
    score = 0
    # Prefer actual color/albedo/grass/dirt textures.
    for good, pts in [
        ('diff', 10), ('albedo', 10), ('basecolor', 10), ('base_color', 10),
        ('_d.', 9), ('_d_', 8), ('grass', 8), ('dirt', 8), ('soil', 8),
        ('ground', 7), ('terrain', 6), ('rock', 4), ('base_01', 5),
    ]:
        if good in name:
            score += pts
    # Strongly reject control maps / normals / roughness / masks.
    for bad, pts in [
        ('mask', 30), ('allterrainmask', 50), ('lightmap', 35), ('rtshadow', 35),
        ('normal', 30), ('_n.', 25), ('_nor', 25), ('rough', 25), ('spec', 20),
        ('_s.', 20), ('metal', 20), ('orm', 20), ('height', 20), ('bump', 20),
    ]:
        if bad in name:
            score -= pts
    return score


def fallback_simplify_terrain_material(obj):
    """Last-resort repair if baking fails: choose a likely diffuse texture."""
    candidates = []
    for slot in obj.material_slots:
        mat = slot.material
        if not mat or not mat.use_nodes or not mat.node_tree:
            continue
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and getattr(node, 'image', None):
                candidates.append((image_name_score(node.image), node.image))

    candidates.sort(key=lambda x: x[0], reverse=True)
    image = candidates[0][1] if candidates and candidates[0][0] > -10 else None

    mat = bpy.data.materials.new(name='ZUSMO_Terrain_WebFallback_' + obj.name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.inputs['Roughness'].default_value = 0.88
    nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])

    if image:
        tex = nt.nodes.new('ShaderNodeTexImage')
        tex.image = image
        tex.interpolation = 'Linear'
        nt.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
        print('  Fallback terrain texture:', obj.name, '->', image.name)
    else:
        # Natural muted green/brown rather than RGB debug colors.
        bsdf.inputs['Base Color'].default_value = (0.18, 0.28, 0.10, 1.0)
        print('  Fallback terrain color:', obj.name)

    obj.data.materials.clear()
    obj.data.materials.append(mat)
    for poly in obj.data.polygons:
        poly.material_index = 0
    clear_mesh_color_attributes(obj.data)


def bake_terrain_object(obj, index):
    print('Baking terrain for web:', obj.name)
    if not ensure_object_uv(obj):
        fallback_simplify_terrain_material(obj)
        return False

    # A single bake image is used as target for every source material slot.
    safe = ''.join(c if c.isalnum() or c in '-_' else '_' for c in obj.name)
    image = bpy.data.images.new(
        name='ZUSMO_TERRAIN_BAKED_' + safe,
        width=TERRAIN_BAKE_SIZE,
        height=TERRAIN_BAKE_SIZE,
        alpha=False,
    )
    image.file_format = 'PNG'
    image.generated_color = (0.16, 0.24, 0.09, 1.0)

    temp_nodes = []
    mats = []
    for slot in obj.material_slots:
        mat = slot.material
        if not mat:
            continue
        if not mat.use_nodes:
            mat.use_nodes = True
        nt = mat.node_tree
        target = nt.nodes.new('ShaderNodeTexImage')
        target.name = 'ZUSMO_BAKE_TARGET'
        target.label = 'ZUSMO terrain bake target'
        target.image = image
        nt.nodes.active = target
        target.select = True
        temp_nodes.append((nt, target))
        mats.append(mat)

    if not temp_nodes:
        fallback_simplify_terrain_material(obj)
        return False

    # Bake only material color, without scene lighting. This flattens the complex
    # shader into a glTF-safe texture while keeping the map's original look.
    bpy.context.scene.render.engine = 'CYCLES'
    try:
        bpy.context.scene.cycles.samples = 1
    except Exception:
        pass
    bpy.context.scene.render.bake.margin = 8
    bpy.context.scene.render.bake.use_clear = True

    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    try:
        bpy.ops.object.bake(type='DIFFUSE', pass_filter={'COLOR'}, use_clear=True, margin=8)
    except Exception as exc:
        print('  WARNING: terrain bake failed for', obj.name, ':', exc)
        for nt, node in temp_nodes:
            try:
                nt.nodes.remove(node)
            except Exception:
                pass
        try:
            bpy.data.images.remove(image)
        except Exception:
            pass
        fallback_simplify_terrain_material(obj)
        return False

    baked_path = os.path.join(MAP_DIR, 'terrain_baked_%02d.png' % index)
    try:
        image.filepath_raw = baked_path
        image.save()
        image.pack()
    except Exception as exc:
        print('  WARNING: could not save/pack baked terrain image:', exc)

    for nt, node in temp_nodes:
        try:
            nt.nodes.remove(node)
        except Exception:
            pass

    # Replace complex Blender material with simple glTF-safe Principled material.
    mat = bpy.data.materials.new(name='ZUSMO_Terrain_Baked_' + safe)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.inputs['Roughness'].default_value = 0.90
    tex = nt.nodes.new('ShaderNodeTexImage')
    tex.image = image
    tex.interpolation = 'Linear'
    nt.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
    nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])

    obj.data.materials.clear()
    obj.data.materials.append(mat)
    for poly in obj.data.polygons:
        poly.material_index = 0

    # Remove shader-control vertex colors after baking so GLTFLoader cannot
    # multiply RGB mask colors back onto the baked Base Color.
    clear_mesh_color_attributes(obj.data)
    print('  Terrain bake OK:', obj.name, '->', os.path.basename(baked_path))
    return True


def repair_main_terrain_for_web():
    terrains = [o for o in bpy.context.scene.objects if is_main_terrain_object(o)]
    terrains.sort(key=lambda o: o.name)
    print('Main terrain objects found:', [o.name for o in terrains])
    if not terrains:
        print('WARNING: no Main_Large_Terrain objects found; applying no terrain bake.')
        return

    baked = 0
    for i, obj in enumerate(terrains, 1):
        if bake_terrain_object(obj, i):
            baked += 1
    print('Terrain repair finished:', baked, '/', len(terrains), 'objects baked.')


# MAP
blend_path, temporary_blend = rebuild_source_blend()
bpy.ops.wm.open_mainfile(filepath=blend_path)
repair_main_terrain_for_web()
map_glb = os.path.join(MAP_DIR, 'map.glb')
# Remove previous generated chunks first so a failed rebuild can never pass verification
# by accidentally reusing stale runtime files from the repository.
remove_split_artifacts(map_glb)
try:
    if os.path.exists(map_glb):
        os.remove(map_glb)
except OSError:
    pass
map_export_kwargs = dict(
    filepath=map_glb,
    export_format='GLB',
    export_apply=True,
    export_texcoords=True,
    export_normals=True,
    export_materials='EXPORT'
)
# Do not export the original terrain color/mask attributes. In glTF COLOR_0 is
# multiplied into the material Base Color and was the direct cause of the RGB
# terrain seen on Android. Keep compatibility with Blender versions where the
# option name is unavailable.
try:
    props = bpy.ops.export_scene.gltf.get_rna_type().properties.keys()
    if 'export_colors' in props:
        map_export_kwargs['export_colors'] = False
except Exception:
    pass
bpy.ops.export_scene.gltf(**map_export_kwargs)
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
remove_split_artifacts(character_glb)
try:
    if os.path.exists(character_glb):
        os.remove(character_glb)
except OSError:
    pass
bpy.ops.export_scene.gltf(
    filepath=character_glb,
    export_format='GLB',
    export_animations=True,
    export_nla_strips=True,
    export_apply=True
)
split_web_asset(character_glb)
print('Prepared split-safe web assets. No generated GLB file will exceed 20,000,000 bytes.')
