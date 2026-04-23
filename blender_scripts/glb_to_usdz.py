"""
Blender headless script — runs inside Blender's Python environment.
Usage (invoked by blender_service.py):

  blender --background --python glb_to_usdz.py -- --input /path/model.glb --output /path/model.usdz
"""

import argparse
import os
import sys

import bpy
import addon_utils


def parse_args():
    # Arguments after "--" are passed to the script
    try:
        idx = sys.argv.index("--")
        script_args = sys.argv[idx + 1:]
    except ValueError:
        script_args = []

    parser = argparse.ArgumentParser(description="Convert GLB to USDZ via Blender")
    parser.add_argument("--input", required=True, help="Path to input .glb file")
    parser.add_argument("--output", required=True, help="Path to output .usdz file")
    parser.add_argument("--bake-resolution", type=int, default=1024, help="Bake texture resolution (px)")
    return parser.parse_args(script_args)


def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def enable_gltf_addon():
    addon_utils.enable("io_scene_gltf2", default_set=False)


def import_glb(filepath: str):
    bpy.ops.import_scene.gltf(filepath=filepath)


def handle_textures(tex_dir: str, bake_resolution: int = 1024):
    has_packed = any(img.packed_file is not None for img in bpy.data.images)

    if has_packed:
        _unpack_embedded_textures(tex_dir)
    else:
        _bake_vertex_colors(tex_dir, bake_resolution)


def _unpack_embedded_textures(tex_dir: str):
    os.makedirs(tex_dir, exist_ok=True)
    for image in bpy.data.images:
        if image.packed_file is None:
            continue
        dest = os.path.join(tex_dir, f"{image.name}.png")
        image.filepath_raw = dest
        image.save()
        image.unpack(method="USE_LOCAL")
        print(f"Unpacked texture: {dest}")


def _bake_vertex_colors(tex_dir: str, bake_resolution: int = 1024):
    os.makedirs(tex_dir, exist_ok=True)
    bpy.context.scene.render.engine = "CYCLES"
    bpy.context.scene.cycles.device = "CPU"
    bpy.context.scene.cycles.samples = 1

    for obj in bpy.data.objects:
        if obj.type != "MESH" or not obj.data.color_attributes:
            continue

        mesh = obj.data
        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        # Ensure UV map exists
        if not mesh.uv_layers:
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.uv.smart_project()
            bpy.ops.object.mode_set(mode="OBJECT")

        # Create bake target image
        bake_image_name = f"{obj.name}_baked"
        bake_img = bpy.data.images.new(bake_image_name, width=bake_resolution, height=bake_resolution)
        bake_img_path = os.path.join(tex_dir, f"{bake_image_name}.png")

        # Set up material nodes for baking
        mat = obj.active_material
        if mat is None:
            mat = bpy.data.materials.new(name=f"{obj.name}_mat")
            obj.data.materials.append(mat)
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        vc_node = nodes.new("ShaderNodeVertexColor")
        bsdf_node = nodes.new("ShaderNodeBsdfPrincipled")
        output_node = nodes.new("ShaderNodeOutputMaterial")
        img_node = nodes.new("ShaderNodeTexImage")

        img_node.image = bake_img
        links.new(vc_node.outputs["Color"], bsdf_node.inputs["Base Color"])
        links.new(bsdf_node.outputs["BSDF"], output_node.inputs["Surface"])

        # Select the image node as active so Blender bakes into it
        nodes.active = img_node

        bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, save_mode="INTERNAL")

        bake_img.filepath_raw = bake_img_path
        bake_img.file_format = "PNG"
        bake_img.save()
        print(f"Baked vertex colors to: {bake_img_path}")

        # Replace vertex color node with UV image texture node
        nodes.remove(vc_node)
        uv_img_node = nodes.new("ShaderNodeTexImage")
        uv_img_node.image = bake_img
        links.new(uv_img_node.outputs["Color"], bsdf_node.inputs["Base Color"])


def export_usdz(output_path: str):
    bpy.ops.wm.usd_export(
        filepath=output_path,
        export_materials=True,
        export_textures_mode="NEW",
        overwrite_textures=True,
        generate_preview_surface=True,
    )


def main():
    args = parse_args()
    input_path = os.path.abspath(args.input)
    output_path = os.path.abspath(args.output)
    tex_dir = os.path.join(os.path.dirname(output_path), "textures")

    print(f"[glb_to_usdz] Input:  {input_path}")
    print(f"[glb_to_usdz] Output: {output_path}")

    clear_scene()
    enable_gltf_addon()
    import_glb(input_path)
    handle_textures(tex_dir, args.bake_resolution)
    export_usdz(output_path)

    if not os.path.exists(output_path):
        raise RuntimeError(f"[glb_to_usdz] Export produced no file at {output_path}")

    print(f"[glb_to_usdz] Conversion complete: {output_path}")


main()
