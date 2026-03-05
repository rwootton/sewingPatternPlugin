bl_info = {
    "name": "Export UV as Sewing Pattern",
    "author": "Gemini",
    "version": (4, 0),
    "blender": (5, 0, 1),
    "location": "View3D > Sidebar > Sewing",
    "description": "Exports UV islands as an SVG sewing pattern with tiling and duplicate filtering.",
    "category": "Import-Export",
}

import bpy
import bmesh
import math

class EXPORT_OT_uv_sewing_pattern(bpy.types.Operator):
    """Export UV layout as SVG with page tiling"""
    bl_idname = "export_mesh.uv_sewing_pattern"
    bl_label = "Export Sewing Pattern (SVG)"
    bl_options = {'REGISTER', 'UNDO'}

    # Automatically handle the .svg extension in the file browser
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
        default=2.0,
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
        obj = context.active_object
        
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Active object must be a mesh.")
            return {'CANCELLED'}

        mesh = obj.data
        if not mesh.uv_layers.active:
            self.report({'ERROR'}, "Mesh has no active UV map.")
            return {'CANCELLED'}

        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.transform(obj.matrix_world)
        uv_layer = bm.loops.layers.uv.active

        # 1. Calculate Real-World Scale
        total_3d_len = 0.0
        total_uv_len = 0.0
        for face in bm.faces:
            for loop in face.loops:
                v1 = loop.vert.co
                v2 = loop.link_loop_next.vert.co
                uv1 = loop[uv_layer].uv
                uv2 = loop.link_loop_next[uv_layer].uv
                
                total_3d_len += (v1 - v2).length
                total_uv_len += (uv1 - uv2).length

        if total_uv_len == 0:
            self.report({'ERROR'}, "UV map has no area.")
            bm.free()
            return {'CANCELLED'}

        uv_to_cm = (total_3d_len / total_uv_len) * 100.0

        # 2. Group faces into islands
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

        # 3. Extract boundaries and calculate bounding boxes
        island_data = []
        for faces in islands:
            edge_counts = {}
            for face in faces:
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
            
            if not paths: continue

            min_x = min(p[0] for path in paths for p in path)
            max_x = max(p[0] for path in paths for p in path)
            min_y = min(p[1] for path in paths for p in path)
            max_y = max(p[1] for path in paths for p in path)
            
            island_data.append({
                'paths': paths,
                'min_x': min_x, 'max_x': max_x,
                'min_y': min_y, 'max_y': max_y,
                'width': max_x - min_x,
                'height': max_y - min_y
            })

        bm.free()

        # 4. Filter Duplicates & Mirrors
        unique_islands = []
        seen_signatures = set()
        
        for isl in island_data:
            perimeter = 0
            area = 0
            edge_lengths = []
            
            for path in isl['paths']:
                path_area = 0
                for i in range(len(path)):
                    p1 = path[i]
                    p2 = path[(i + 1) % len(path)]
                    dx = p2[0] - p1[0]
                    dy = p2[1] - p1[1]
                    length = math.hypot(dx, dy)
                    perimeter += length
                    edge_lengths.append(round(length, 1)) # Round to 1 decimal place for tolerance
                    
                    path_area += (p1[0] * p2[1]) - (p2[0] * p1[1])
                area += abs(path_area) / 2.0
                
            edge_lengths.sort()
            sig_area = round(area, 1)
            sig_perim = round(perimeter, 1)
            
            w = isl['width']
            h = isl['height']
            bbox_ratio = round(max(w, h) / min(w, h), 2) if min(w, h) > 0 else 0.0
                
            signature = (sig_area, sig_perim, bbox_ratio, tuple(edge_lengths))
            
            if signature not in seen_signatures:
                seen_signatures.add(signature)
                unique_islands.append(isl)
                
        island_data = unique_islands

        # 5. Fixed-Bin Packing
        class FixedPacker:
            def __init__(self, width, height):
                self.root = {'x': 0, 'y': 0, 'w': width, 'h': height}
                self.blocks = []

            def fit(self, block):
                node = self.find_node(self.root, block['w'], block['h'])
                if node:
                    block['fit'] = self.split_node(node, block['w'], block['h'])
                    self.blocks.append(block)
                    return True
                return False

            def find_node(self, node, w, h):
                if node.get('used'):
                    right_node = self.find_node(node.get('right'), w, h) if node.get('right') else None
                    if right_node: return right_node
                    return self.find_node(node.get('down'), w, h) if node.get('down') else None
                elif w <= node['w'] and h <= node['h']:
                    return node
                return None

            def split_node(self, node, w, h):
                node['used'] = True
                node['down']  = {'x': node['x'],     'y': node['y'] + h, 'w': node['w'],     'h': node['h'] - h}
                node['right'] = {'x': node['x'] + w, 'y': node['y'],     'w': node['w'] - w, 'h': h}
                return node

        spacing = self.padding_cm + (self.seam_allowance_cm * 2)
        blocks = []
        for isl in island_data:
            blocks.append({
                'w': isl['width'] + spacing,
                'h': isl['height'] + spacing,
                'island': isl
            })
            
        blocks.sort(key=lambda b: max(b['w'], b['h']), reverse=True)

        standard_pages = []
        oversize_blocks = []

        for block in blocks:
            if block['w'] <= self.page_width_cm and block['h'] <= self.page_height_cm:
                placed = False
                for page in standard_pages:
                    if page.fit(block):
                        placed = True
                        break
                if not placed:
                    new_page = FixedPacker(self.page_width_cm, self.page_height_cm)
                    new_page.fit(block)
                    standard_pages.append(new_page)
            else:
                oversize_blocks.append(block)

        # 6. Global Layout
        layout_items = []

        for page in standard_pages:
            layout_items.append({
                'type': 'standard',
                'w': self.page_width_cm,
                'h': self.page_height_cm,
                'blocks': page.blocks
            })

        for ob in oversize_blocks:
            cols = math.ceil(ob['w'] / self.page_width_cm)
            rows = math.ceil(ob['h'] / self.page_height_cm)
            layout_items.append({
                'type': 'oversize',
                'w': cols * self.page_width_cm,
                'h': rows * self.page_height_cm,
                'cols': cols,
                'rows': rows,
                'block': ob
            })

        gap = 2.0
        max_layout_width = (self.page_width_cm * 5) + (gap * 4)
        
        current_x = gap
        current_y = gap
        row_height = 0
        max_svg_width = gap
        max_svg_height = gap
        
        svg_paths_data = [] 
        page_rects = [] 

        for item in layout_items:
            if current_x + item['w'] > max_layout_width and current_x > gap:
                current_x = gap
                current_y += row_height + gap
                row_height = 0
                
            if item['type'] == 'standard':
                page_rects.append((current_x, current_y, item['w'], item['h']))
                for block in item['blocks']:
                    shift_x = current_x + block['fit']['x'] - block['island']['min_x'] + (spacing / 2)
                    shift_y = current_y + block['fit']['y'] - block['island']['min_y'] + (spacing / 2)
                    for path in block['island']['paths']:
                        svg_paths_data.append({'path': path, 'sx': shift_x, 'sy': shift_y})
            
            elif item['type'] == 'oversize':
                for c in range(item['cols']):
                    for r in range(item['rows']):
                        page_rects.append((current_x + c * self.page_width_cm, current_y + r * self.page_height_cm, self.page_width_cm, self.page_height_cm))
                
                block = item['block']
                shift_x = current_x - block['island']['min_x'] + (spacing / 2)
                shift_y = current_y - block['island']['min_y'] + (spacing / 2)
                for path in block['island']['paths']:
                    svg_paths_data.append({'path': path, 'sx': shift_x, 'sy': shift_y})

            current_x += item['w'] + gap
            row_height = max(row_height, item['h'])
            max_svg_width = max(max_svg_width, current_x)
            max_svg_height = max(max_svg_height, current_y + row_height + gap)

        # 7. Generate SVG 
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

        for item in svg_paths_data:
            points_str = []
            for p in item['path']:
                x = p[0] + item['sx']
                y = p[1] + item['sy'] 
                points_str.append(f"{x:.4f},{y:.4f}")
            
            pts = " ".join(points_str)
            
            svg_lines.append('<g>')
            if self.seam_allowance_cm > 0:
                # Outer black cutting line
                svg_lines.append(f'<polygon points="{pts}" fill="none" stroke="black" stroke-width="{stroke_width:.4f}" stroke-linejoin="round"/>')
                # Inner white layer to hollow it out + fill the shape
                svg_lines.append(f'<polygon points="{pts}" fill="white" stroke="white" stroke-width="{inner_sw:.4f}" stroke-linejoin="round"/>')
            else:
                svg_lines.append(f'<polygon points="{pts}" fill="white" stroke="none"/>')
                
            # Dashed sewing line on the actual UV boundary
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
