bl_info = {
    "name": "Export UV as Sewing Pattern",
    "author": "Gemini",
    "version": (5, 2),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Sewing",
    "description": "Exports UV islands as an SVG sewing pattern using native exact boundary packing.",
    "category": "Import-Export",
}

import bpy
import bmesh
import math

class EXPORT_OT_uv_sewing_pattern(bpy.types.Operator):
    """Export UV layout as SVG with exact boundary packing and tiling"""
    bl_idname = "export_mesh.uv_sewing_pattern"
    bl_label = "Export Sewing Pattern (SVG)"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".svg"
    filter_glob: bpy.props.StringProperty(
        default="*.svg",
        options={'HIDDEN'},
        maxlen=255,
    )

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    
    seam_allowance_cm: bpy.props.FloatProperty(
        name="Seam Allowance (cm)",
        default=1.0,
        description="Size of the seam allowance in centimeters",
        min=0.0
    )
    
    padding_cm: bpy.props.FloatProperty(
        name="Island Padding (cm)",
        default=0.5,
        description="Extra empty space between islands",
        min=0.0
    )
    
    page_width_cm: bpy.props.FloatProperty(
        name="Page Width (cm)",
        default=21.0,
        description="Printable width of a single page",
        min=5.0
    )

    page_height_cm: bpy.props.FloatProperty(
        name="Page Height (cm)",
        default=28.0,
        description="Printable height of a single page",
        min=5.0
    )

    draw_page_boundaries: bpy.props.BoolProperty(
        name="Draw Page Boundaries",
        default=True,
        description="Include blue dashed lines indicating physical pages"
    )

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        original_obj = context.active_object
        
        if not original_obj or original_obj.type != 'MESH':
            self.report({'ERROR'}, "Active object must be a mesh.")
            return {'CANCELLED'}

        if not original_obj.data.uv_layers.active:
            self.report({'ERROR'}, "Mesh has no active UV map.")
            return {'CANCELLED'}

        # 1. Duplicate active object
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        original_obj.select_set(True)
        context.view_layer.objects.active = original_obj
        
        bpy.ops.object.duplicate(linked=False)
        temp_obj = context.active_object

        # 2. Filter Duplicates & Mirrors
        bm = bmesh.new()
        bm.from_mesh(temp_obj.data)
        bm.transform(temp_obj.matrix_world)
        uv_layer = bm.loops.layers.uv.active

        adj_faces = {f: set() for f in bm.faces}
        for edge in bm.edges:
            if len(edge.link_faces) == 2:
                f1, f2 = edge.link_faces
                l1 = next((l for l in f1.loops if l.edge == edge), None)
                l2 = next((l for l in f2.loops if l.edge == edge), None)
                if l1 and l2:
                    uv1_a = l1[uv_layer].uv
                    uv1_b = l1.link_loop_next[uv_layer].uv
                    uv2_a = l2.link_loop_next[uv_layer].uv
                    uv2_b = l2[uv_layer].uv
                    if (uv1_a - uv2_a).length < 1e-4 and (uv1_b - uv2_b).length < 1e-4:
                        adj_faces[f1].add(f2)
                        adj_faces[f2].add(f1)

        visited_faces = set()
        islands = []
        for f in bm.faces:
            if f not in visited_faces:
                island_faces = []
                queue = [f]
                visited_faces.add(f)
                while queue:
                    curr = queue.pop(0)
                    island_faces.append(curr)
                    for neighbor in adj_faces[curr]:
                        if neighbor not in visited_faces:
                            visited_faces.add(neighbor)
                            queue.append(neighbor)
                islands.append(island_faces)

        faces_to_delete = []
        seen_signatures = set()
        for island_faces in islands:
            perim_3d = 0.0
            area_3d = 0.0
            edge_lengths = []
            island_edge_counts = {}
            for f in island_faces:
                area_3d += f.calc_area()
                for loop in f.loops:
                    edge = loop.edge
                    island_edge_counts[edge] = island_edge_counts.get(edge, 0) + 1
            for edge, count in island_edge_counts.items():
                if count == 1:
                    l = edge.calc_length()
                    perim_3d += l
                    edge_lengths.append(round(l, 3))

            edge_lengths.sort()
            signature = (round(area_3d, 3), round(perim_3d, 3), tuple(edge_lengths))
            
            if signature not in seen_signatures:
                seen_signatures.add(signature)
            else:
                faces_to_delete.extend(island_faces)

        bmesh.ops.delete(bm, geom=faces_to_delete, context='FACES')
        bm.to_mesh(temp_obj.data)
        bm.free()

        # 3. Native Packing & Scale Calibration
        desired_spacing_cm = self.padding_cm + (self.seam_allowance_cm * 2)
        margin_value = 0.001
        
        target_area = next((a for a in context.screen.areas if a.type == 'IMAGE_EDITOR'), None)
        original_type = None
        
        if not target_area:
            target_area = next((a for a in context.screen.areas if a.type != 'VIEW_3D'), context.area)
            original_type = target_area.type
            target_area.type = 'IMAGE_EDITOR'
            target_area.ui_type = 'UV'

        window_region = next((r for r in target_area.regions if r.type == 'WINDOW'), None)
        space_data = target_area.spaces.active

        try:
            for i in range(2):
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                
                with context.temp_override(window=context.window, area=target_area, region=window_region, space_data=space_data):
                    bpy.ops.uv.select_all(action='SELECT')
                    bpy.ops.uv.pack_islands(margin=margin_value, rotate=True, shape_method='CONCAVE')
                
                bpy.ops.object.mode_set(mode='OBJECT')
                
                bm_temp = bmesh.new()
                bm_temp.from_mesh(temp_obj.data)
                uv_layer_temp = bm_temp.loops.layers.uv.active
                
                total_3d = 0.0
                total_uv = 0.0
                for face in bm_temp.faces:
                    for loop in face.loops:
                        total_3d += (loop.vert.co - loop.link_loop_next.vert.co).length
                        total_uv += (loop[uv_layer_temp].uv - loop.link_loop_next[uv_layer_temp].uv).length
                
                uv_to_cm = (total_3d / total_uv) * 100.0 if total_uv > 0 else 1.0
                bm_temp.free()
                
                margin_value = desired_spacing_cm / uv_to_cm
                if margin_value > 1.0: margin_value = 1.0
                
        finally:
            if original_type:
                target_area.type = original_type

        # 4. Extract Final Layout
        bpy.ops.object.mode_set(mode='OBJECT')
        bm = bmesh.new()
        bm.from_mesh(temp_obj.data)
        uv_layer = bm.loops.layers.uv.active

        edge_counts = {}
        for face in bm.faces:
            for loop in face.loops:
                uv1 = loop[uv_layer].uv
                uv2 = loop.link_loop_next[uv_layer].uv
                p1 = (round(uv1.x * uv_to_cm, 4), round((1.0 - uv1.y) * uv_to_cm, 4))
                p2 = (round(uv2.x * uv_to_cm, 4), round((1.0 - uv2.y) * uv_to_cm, 4))
                if p1 == p2: continue
                edge = tuple(sorted([p1, p2]))
                edge_counts[edge] = edge_counts.get(edge, 0) + 1
                
        boundaries = [e for e, c in edge_counts.items() if c == 1]
        
        adj = {}
        for p1, p2 in boundaries:
            adj.setdefault(p1, []).append(p2)
            adj.setdefault(p2, []).append(p1)
            
        paths = []
        visited_edges = set()
        for start_edge in boundaries:
            edge_key = tuple(sorted(start_edge))
            if edge_key in visited_edges: continue
            
            path = [start_edge[0], start_edge[1]]
            visited_edges.add(edge_key)
            
            curr = start_edge[1]
            while True:
                next_nodes = adj.get(curr, [])
                found_next = False
                for nxt in next_nodes:
                    ekey = tuple(sorted([curr, nxt]))
                    if ekey not in visited_edges:
                        visited_edges.add(ekey)
                        path.append(nxt)
                        curr = nxt
                        found_next = True
                        break
                if not found_next:
                    break
            paths.append(path)
            
        bm.free()
        
        # Clean up temp object
        bpy.data.objects.remove(temp_obj, do_unlink=True)
        context.view_layer.objects.active = original_obj
        original_obj.select_set(True)

        if not paths:
            self.report({'ERROR'}, "No patterns generated.")
            return {'CANCELLED'}

        # 5. Tile & Generate SVG
        min_x = min(p[0] for path in paths for p in path)
        max_x = max(p[0] for path in paths for p in path)
        min_y = min(p[1] for path in paths for p in path)
        max_y = max(p[1] for path in paths for p in path)
        
        gap = self.padding_cm / 2.0
        shift_x = gap - min_x
        shift_y = gap - min_y
        
        max_svg_width = (max_x - min_x) + (gap * 2)
        max_svg_height = (max_y - min_y) + (gap * 2)
        
        cols = math.ceil(max_svg_width / self.page_width_cm)
        rows = math.ceil(max_svg_height / self.page_height_cm)
        
        max_svg_width = cols * self.page_width_cm
        max_svg_height = rows * self.page_height_cm
        
        page_rects = []
        for r in range(rows):
            for c in range(cols):
                rx = c * self.page_width_cm
                ry = r * self.page_height_cm
                page_rects.append((rx, ry, self.page_width_cm, self.page_height_cm))

        stroke_width = self.seam_allowance_cm * 2 
        outline_thickness = 0.05
        inner_sw = max(0, stroke_width - (outline_thickness * 2))
        
        svg_lines = []
        svg_lines.append('<?xml version="1.0" standalone="no"?>')
        svg_lines.append(f'<svg width="{max_svg_width:.2f}cm" height="{max_svg_height:.2f}cm" viewBox="0 0 {max_svg_width:.2f} {max_svg_height:.2f}" version="1.1" xmlns="http://www.w3.org/2000/svg">')

        if self.draw_page_boundaries:
            for rect in page_rects:
                rx, ry, rw, rh = rect
                svg_lines.append(f'<rect x="{rx:.4f}" y="{ry:.4f}" width="{rw:.4f}" height="{rh:.4f}" fill="none" stroke="#add8e6" stroke-width="0.1" stroke-dasharray="0.5,0.5"/>')

        for path in paths:
            points_str = []
            for p in path:
                x = p[0] + shift_x
                y = p[1] + shift_y 
                points_str.append(f"{x:.4f},{y:.4f}")
            
            pts = " ".join(points_str)
            
            svg_lines.append('<g>')
            if self.seam_allowance_cm > 0:
                svg_lines.append(f'<polygon points="{pts}" fill="none" stroke="black" stroke-width="{stroke_width:.4f}" stroke-linejoin="round"/>')
                svg_lines.append(f'<polygon points="{pts}" fill="white" stroke="white" stroke-width="{inner_sw:.4f}" stroke-linejoin="round"/>')
            else:
                svg_lines.append(f'<polygon points="{pts}" fill="white" stroke="none"/>')
                
            svg_lines.append(f'<polygon points="{pts}" fill="none" stroke="black" stroke-width="0.05" stroke-dasharray="0.3,0.3" stroke-linejoin="round"/>')
            svg_lines.append('</g>')

        svg_lines.append('</svg>')

        if not self.filepath.endswith(".svg"):
            self.filepath += ".svg"

        with open(self.filepath, 'w') as f:
            f.write("\n".join(svg_lines))

        self.report({'INFO'}, f"Exported sewing pattern to {self.filepath}")
        return {'FINISHED'}

class VIEW3D_PT_sewing_pattern(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Sewing'
    bl_label = "UV to Sewing Pattern"

    def draw(self, context):
        layout = self.layout
        layout.operator("export_mesh.uv_sewing_pattern", text="Export SVG Pattern")

def register():
    bpy.utils.register_class(EXPORT_OT_uv_sewing_pattern)
    bpy.utils.register_class(VIEW3D_PT_sewing_pattern)

def unregister():
    bpy.utils.unregister_class(EXPORT_OT_uv_sewing_pattern)
    bpy.utils.unregister_class(VIEW3D_PT_sewing_pattern)

if __name__ == "__main__":
    register()
