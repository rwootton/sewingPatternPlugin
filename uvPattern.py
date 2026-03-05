bl_info = {
    "name": "Export UV as Sewing Pattern",
    "author": "Gemini",
    "version": (1, 1),
    "blender": (5, 0, 1),
    "location": "View3D > Sidebar > Sewing",
    "description": "Exports UV islands as an SVG sewing pattern with seam allowances.",
    "category": "Import-Export",
}

import bpy
import bmesh

class EXPORT_OT_uv_sewing_pattern(bpy.types.Operator):
    """Export UV layout as SVG with seam allowance"""
    bl_idname = "export_mesh.uv_sewing_pattern"
    bl_label = "Export Sewing Pattern (SVG)"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    
    seam_allowance_cm: bpy.props.FloatProperty(
        name="Seam Allowance (cm)",
        default=1.0,
        description="Size of the seam allowance in centimeters",
        min=0.0
    )
    
    uv_scale_cm: bpy.props.FloatProperty(
        name="UV Layout Size (cm)",
        default=100.0,
        description="Physical size of the 1x1 UV square in cm (e.g., 100 means 1 UV unit = 1 meter)",
        min=1.0
    )

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        obj = context.active_object
        
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Active object must be a mesh.")
            return {'CANCELLED'}

        mesh = obj.data
        if not mesh.uv_layers.active:
            self.report({'ERROR'}, "Mesh has no active UV map.")
            return {'CANCELLED'}

        scale = self.uv_scale_cm
        
        # 1. Find all edges in UV space
        bm = bmesh.new()
        bm.from_mesh(mesh)
        uv_layer = bm.loops.layers.uv.active

        edge_segments = {}
        for face in bm.faces:
            for i in range(len(face.loops)):
                loop1 = face.loops[i]
                loop2 = face.loops[(i+1) % len(face.loops)]
                uv1 = loop1[uv_layer].uv
                uv2 = loop2[uv_layer].uv
                
                p1 = (round(uv1.x, 5), round(uv1.y, 5))
                p2 = (round(uv2.x, 5), round(uv2.y, 5))
                
                if p1 == p2:
                    continue # Ignore zero-length edges
                    
                key = tuple(sorted([p1, p2]))
                if key in edge_segments:
                    edge_segments[key] += 1
                else:
                    edge_segments[key] = 1
                    
        # 2. Filter for boundary edges (edges that only belong to one face in UV space)
        boundaries = [edge for edge, count in edge_segments.items() if count == 1]
        
        # 3. Chain boundary edges into continuous paths
        adj = {}
        for p1, p2 in boundaries:
            adj.setdefault(p1, []).append(p2)
            adj.setdefault(p2, []).append(p1)
            
        paths = []
        visited = set()
        
        for start_edge in boundaries:
            # Check if this edge was already traversed
            if tuple(sorted(start_edge)) in visited: 
                continue
            
            path = [start_edge[0], start_edge[1]]
            visited.add(tuple(sorted(start_edge)))
            
            curr = start_edge[1]
            while True:
                next_nodes = adj.get(curr, [])
                found_next = False
                for nxt in next_nodes:
                    edge = tuple(sorted([curr, nxt]))
                    if edge not in visited:
                        visited.add(edge)
                        path.append(nxt)
                        curr = nxt
                        found_next = True
                        break
                if not found_next:
                    break
            paths.append(path)

        bm.free()

        # 4. Generate SVG output
        # SVG strokes are centered. A stroke of 2cm means 1cm extends outward and 1cm extends inward.
        stroke_width = self.seam_allowance_cm * 2 
        
        svg_lines = []
        svg_lines.append('<?xml version="1.0" standalone="no"?>')
        svg_lines.append(f'<svg width="{scale}cm" height="{scale}cm" viewBox="0 0 {scale} {scale}" version="1.1" xmlns="http://www.w3.org/2000/svg">')

        for path in paths:
            points_str = []
            for p in path:
                x = p[0] * scale
                y = (1.0 - p[1]) * scale # Invert Y for SVG
                points_str.append(f"{x:.4f},{y:.4f}")
            
            pts = " ".join(points_str)
            
            svg_lines.append('<g>')
            # The thick background stroke (Cutting Line)
            svg_lines.append(f'<polygon points="{pts}" fill="none" stroke="#d3d3d3" stroke-width="{stroke_width}" stroke-linejoin="round"/>')
            # The white fill layer covers the inner half of the thick stroke, 
            # while the black dashed stroke represents the Sewing Line.
            svg_lines.append(f'<polygon points="{pts}" fill="white" stroke="black" stroke-width="0.1" stroke-dasharray="0.5,0.5" stroke-linejoin="round"/>')
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
