"""
Blender headless script: GLB → USDZ conversion.

Confirmed working on Blender 5.0.1 (snap) on Ubuntu.
Handles both image-textured and vertex-colored GLB files.

Called via:
  blender --background --python app/services/blender_scripts/glb_to_usdz.py \
          -- --input /path/to/model.glb --output /path/to/model.usdz
"""

import os
import sys
import bpy


def parse_args():
    """Parse args after '--' separator (Blender's custom arg convention)."""
    argv = sys.argv
    if "--" not in argv:
        raise ValueError(
            "Usage: blender --background --python glb_to_usdz.py "
            "-- --input <glb_path> --output <usdz_path>"
        )
    args = argv[argv.index("--") + 1:]
    input_path, output_path, bake_resolution = None, None, 1024
    for i, arg in enumerate(args):
        if arg == "--input":
            input_path = args[i + 1]
        elif arg == "--output":
            output_path = args[i + 1]
        elif arg == "--bake-resolution":
            bake_resolution = int(args[i + 1])
    if not input_path or not output_path:
        raise ValueError("Both --input and --output are required.")
    return input_path, output_path, bake_resolution


def bake_vertex_colors(obj, tex_dir, bake_size=2048):
    """
    Bake vertex colors to a texture image and wire it into the material.
    Returns the baked image or None if baking failed.
    """
    mesh = obj.data
    if not mesh.color_attributes:
        return None

    # Deselect all, then make only this object active
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    # Add UV map if missing
    if not mesh.uv_layers:
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.uv.smart_project(angle_limit=66.0)
        bpy.ops.object.mode_set(mode='OBJECT')
        print(f"[Blender] Created UV map for {obj.name}")

    # Create bake texture
    bake_img_name = f"{obj.name}_baked.png"
    bake_img = bpy.data.images.new(bake_img_name, width=bake_size, height=bake_size)
    bake_img.colorspace_settings.name = 'sRGB'
    bake_img.filepath_raw = os.path.join(tex_dir, bake_img_name)

    # Set up material with vertex color + image texture node for baking
    mat = obj.data.materials[0] if obj.data.materials else None
    if mat is None:
        mat = bpy.data.materials.new(name=f"{obj.name}_mat")
        obj.data.materials.append(mat)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    # Add image texture node (target for bake)
    img_node = nodes.new("ShaderNodeTexImage")
    img_node.image = bake_img
    nodes.active = img_node  # Must be active for baking

    # Add vertex color node and connect to Principled BSDF base color
    vcol_node = nodes.new("ShaderNodeVertexColor")
    vcol_node.layer_name = mesh.color_attributes[0].name
    principled = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if principled:
        links.new(vcol_node.outputs['Color'], principled.inputs['Base Color'])

    # Bake vertex colors → image texture
    bpy.context.scene.render.engine = 'CYCLES'
    bpy.context.scene.cycles.device = 'CPU'
    bpy.context.scene.cycles.samples = 1
    bpy.context.scene.display_settings.display_device = 'sRGB'
    bpy.context.scene.view_settings.view_transform = 'Standard'
    bpy.context.scene.view_settings.look = 'None'
    bpy.ops.object.bake(type='DIFFUSE', pass_filter={'COLOR'}, save_mode='INTERNAL')

    bake_img.save()
    print(f"[Blender] Baked vertex colors → {bake_img.filepath_raw}")

    # Replace vertex color node with UV image texture node in material
    uv_node = nodes.new("ShaderNodeTexCoord")
    links.new(uv_node.outputs['UV'], img_node.inputs['Vector'])
    if principled:
        links.new(img_node.outputs['Color'], principled.inputs['Base Color'])
    nodes.remove(vcol_node)

    return bake_img


def main():
    input_path, output_path, bake_resolution = parse_args()

    tex_dir = os.path.join(os.path.dirname(output_path), "textures")
    os.makedirs(tex_dir, exist_ok=True)

    # ── Step 1: Clear default scene ───────────────────────────────────
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # ── Step 2: Enable GLB import addon (required in headless Blender) ─
    import addon_utils
    addon_utils.enable("io_scene_gltf2", default_set=False)

    # ── Step 3: Import GLB ────────────────────────────────────────────
    print(f"[Blender] Importing GLB: {input_path}")
    bpy.ops.import_scene.gltf(filepath=input_path)

    # ── Step 4: Handle textures ───────────────────────────────────────
    has_images = any(img for img in bpy.data.images if img.packed_file)
    has_vertex_colors = any(
        obj.data.color_attributes
        for obj in bpy.data.objects
        if obj.type == 'MESH' and obj.data.color_attributes
    )

    if has_images:
        # Unpack embedded image textures to disk
        unpacked = 0
        for image in bpy.data.images:
            if image.packed_file:
                name = image.name
                if not os.path.splitext(name)[1]:
                    name = name + ".png"
                image.filepath_raw = os.path.join(tex_dir, name)
                image.save()
                image.unpack(method='USE_LOCAL')
                unpacked += 1
        print(f"[Blender] Unpacked {unpacked} image texture(s)")

    elif has_vertex_colors:
        # Bake vertex colors to image textures
        print("[Blender] No image textures found — baking vertex colors to texture")
        for obj in bpy.data.objects:
            if obj.type == 'MESH' and obj.data.color_attributes:
                bake_vertex_colors(obj, tex_dir, bake_size=bake_resolution)

    # ── Step 5: Export to .usdz ───────────────────────────────────────
    print(f"[Blender] Exporting USDZ: {output_path}")
    result = bpy.ops.wm.usd_export(
        filepath=output_path,
        export_materials=True,
        export_textures_mode='NEW',
        overwrite_textures=True,
        generate_preview_surface=True,
    )
    print(f"[Blender] Export result: {result}")

    if not os.path.exists(output_path):
        raise RuntimeError(f"USD export returned {result} but file not found: {output_path}")

    print(f"[Blender] Done → {output_path} ({os.path.getsize(output_path)} bytes)")


if __name__ == "__main__":
    main()
