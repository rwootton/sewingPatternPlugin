bl_info = {
    "name": "Export UV as Sewing Pattern",
    "author": "Gemini",
    "version": (5, 8),
    "blender": (5, 0, 1),
    "location": "View3D > Sidebar > Sewing",
    "description": "Exports UV islands as an SVG sewing pattern from all selected objects.",
    "category": "Import-Export",
}

import bpy
import bmesh
import math

import sys
import subprocess
import importlib
import site

def install_and_import_shapely():
    try:
        import shapely
    except ImportError:
        python_exe = sys.executable
        subprocess.check_call([python_exe, "-m", "ensurepip"])
        subprocess.check_call([python_exe, "-m", "pip", "install", "--user", "shapely"])
        user_site = site.getusersitepackages()
        if user_site not in sys.path:
            sys.path.append(user_site)
        importlib.invalidate_caches()

install_and_import_shapely()

import shapely
from shapely.geometry import Polygon, Point

class EXPORT_OT_uv_sewing_pattern(bpy.types.Operator):
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
        default=0.7,
        min=0.0
    )
    
    padding_cm: bpy.props.FloatProperty(
        name="Island Padding (cm)",
        default=0.2,
        min=0.0
    )
    
    page_width_cm: bpy.props.FloatProperty(
        name="Page Width (cm)",
        default=100,
        min=5.0
    )

    page_height_cm: bpy.props.FloatProperty(
        name="Page Height (cm)",
        default=60,
        min=5.0
    )

    draw_page_boundaries: bpy.props.BoolProperty(
        name="Draw Page Boundaries",
        default=True
    )

    draw_sewing_line: bpy.props.BoolProperty(
        name="Draw Sewing Line",
        default=True
    )

    remove_duplicates: bpy.props.BoolProperty(
        name="Remove Duplicates/Mirrors",
        default=True,
        description="Automatically remove identical or mirrored mesh islands"
    )

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        # 1. Gather all selected valid meshes
        selected_meshes = [obj for obj in context.selected_objects if obj.type == 'MESH' and obj.data.uv_layers.active]
        
        if not selected_meshes:
            self.report({'ERROR'}, "No selected meshes with active UV maps found.")
            return {'CANCELLED'}

        original_active = context.active_object
        original_selection = context.selected_objects[:]

        # 2. Duplicate and combine them into a single temporary mesh
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        
        for obj in selected_meshes:
            obj.select_set(True)
            
        bpy.ops.object.duplicate(linked=False)
        temp_objects = context.selected_objects[:]
        context.view_layer.objects.active = temp_objects[0]
        
        if len(temp_objects) > 1:
            bpy.ops.object.join()
            
        temp_obj = context.active_object

        bm = bmesh.new()
        bm.from_mesh(temp_obj.data)
        bm.transform(temp_obj.matrix_world)
        uv_layer = bm.loops.layers.uv.active

        # 3. Island Identification
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

        # 4. Optional Duplicate Filtering
        if self.remove_duplicates:
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

            if faces_to_delete:
                bmesh.ops.delete(bm, geom=faces_to_delete, context='FACES')
                
        bm.to_mesh(temp_obj.data)
        bm.free()

        desired_spacing_cm = (self.padding_cm + (self.seam_allowance_cm * 2)) * 1.25
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
            for i in range(4):
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

        bpy.ops.object.mode_set(mode='OBJECT')
        bm = bmesh.new()
        bm.from_mesh(temp_obj.data)
        uv_layer = bm.loops.layers.uv.active

        edge_counts = {}
        edge_to_3d_idx = {}
        sharp_3d_edges = set()
        
        for face in bm.faces:
            for loop in face.loops:
                uv1 = loop[uv_layer].uv
                uv2 = loop.link_loop_next[uv_layer].uv
                p1 = (round(uv1.x * uv_to_cm, 4), round((1.0 - uv1.y) * uv_to_cm, 4))
                p2 = (round(uv2.x * uv_to_cm, 4), round((1.0 - uv2.y) * uv_to_cm, 4))
                if p1 == p2: continue
                edge_key = tuple(sorted([p1, p2]))
                edge_counts[edge_key] = edge_counts.get(edge_key, 0) + 1
                edge_to_3d_idx[edge_key] = loop.edge.index
                
                if not loop.edge.smooth:
                    sharp_3d_edges.add(loop.edge.index)
                
        boundaries = [e for e, c in edge_counts.items() if c == 1]
        
        notch_id_map = {}
        for i, e_idx in enumerate(sorted(list(sharp_3d_edges))):
            notch_id_map[e_idx] = str(i + 1)
        
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
        
        # Cleanup temp object and restore selection
        bpy.data.objects.remove(temp_obj, do_unlink=True)
        for obj in original_selection:
            obj.select_set(True)
        if original_active:
            context.view_layer.objects.active = original_active

        if not paths:
            self.report({'ERROR'}, "No patterns generated.")
            return {'CANCELLED'}

        min_x = min(p[0] for path in paths for p in path)
        max_x = max(p[0] for path in paths for p in path)
        min_y = min(p[1] for path in paths for p in path)
        max_y = max(p[1] for path in paths for p in path)
        
        shift_x = (self.padding_cm / 2.0) + self.seam_allowance_cm - min_x
        shift_y = (self.padding_cm / 2.0) + self.seam_allowance_cm - min_y
        
        max_svg_width = (max_x - min_x) + (self.seam_allowance_cm * 2) + self.padding_cm
        max_svg_height = (max_y - min_y) + (self.seam_allowance_cm * 2) + self.padding_cm
        
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

        svg_lines = []
        svg_lines.append('<?xml version="1.0" standalone="no"?>')
        svg_lines.append(f'<svg width="{max_svg_width:.2f}cm" height="{max_svg_height:.2f}cm" viewBox="0 0 {max_svg_width:.2f} {max_svg_height:.2f}" version="1.1" xmlns="http://www.w3.org/2000/svg">')

        if self.draw_page_boundaries:
            for rect in page_rects:
                rx, ry, rw, rh = rect
                svg_lines.append(f'<rect x="{rx:.4f}" y="{ry:.4f}" width="{rw:.4f}" height="{rh:.4f}" fill="none" stroke="#add8e6" stroke-width="0.1" stroke-dasharray="0.5,0.5"/>')

        for path in paths:
            poly = Polygon(path)
            cut_poly = poly.buffer(self.seam_allowance_cm, join_style=2)
            cut_path = list(cut_poly.exterior.coords)
            
            points_str = []
            for p in path:
                x = p[0] + shift_x
                y = p[1] + shift_y 
                points_str.append(f"{x:.4f},{y:.4f}")

            cut_points_str = []
            for p in cut_path:
                x = p[0] + shift_x
                y = p[1] + shift_y 
                cut_points_str.append(f"{x:.4f},{y:.4f}")
            
            pts = " ".join(points_str)
            cut_pts = " ".join(cut_points_str)
            
            svg_lines.append('<g>')
            svg_lines.append(f'<polygon points="{cut_pts}" fill="none" stroke="black" stroke-width="0.05" />')
                
            if self.draw_sewing_line:
                svg_lines.append(f'<polygon points="{pts}" fill="none" stroke="gray" stroke-width="0.05" />')
            
            for i in range(len(path) - 1):
                p1 = path[i]
                p2 = path[i+1]
                edge_key = tuple(sorted([p1, p2]))
                
                if edge_key in edge_to_3d_idx:
                    e_idx = edge_to_3d_idx[edge_key]
                    if e_idx in notch_id_map:
                        n_id = notch_id_map[e_idx]
                        
                        mid_x = (p1[0] + p2[0]) / 2.0
                        mid_y = (p1[1] + p2[1]) / 2.0
                        mid_pt = Point(mid_x, mid_y)
                        
                        if self.seam_allowance_cm > 0:
                            dist = cut_poly.exterior.project(mid_pt)
                            cut_pt = cut_poly.exterior.interpolate(dist)
                            
                            sx1, sy1 = mid_x + shift_x, mid_y + shift_y
                            sx2, sy2 = cut_pt.x + shift_x, cut_pt.y + shift_y
                            
                            svg_lines.append(f'<line x1="{sx1:.4f}" y1="{sy1:.4f}" x2="{sx2:.4f}" y2="{sy2:.4f}" stroke="black" stroke-width="0.05" />')
                            
                            dx = sx1 - sx2
                            dy = sy1 - sy2
                            length = math.hypot(dx, dy)
                            if length > 0:
                                idx = sx1 + (dx/length) * 0.3
                                idy = sy1 + (dy/length) * 0.3
                                svg_lines.append(f'<text x="{idx:.4f}" y="{idy:.4f}" font-size="0.3" font-family="sans-serif" text-anchor="middle" dominant-baseline="middle">{n_id}</text>')
                        else:
                            sx1, sy1 = mid_x + shift_x, mid_y + shift_y
                            svg_lines.append(f'<text x="{sx1:.4f}" y="{sy1:.4f}" font-size="0.3" font-family="sans-serif" text-anchor="middle" dominant-baseline="middle">{n_id}</text>')

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
