"""Texturas que chegam em arquivos separados do modelo.

Dois passos, rodados logo depois de importar o asset:

1. religar: imagem que o modelo referencia mas não achou (caminho da máquina de quem
   exportou, pasta diferente) é procurada pelo nome na pasta do asset;
2. aplicar por nome: material que continua sem textura de cor recebe as imagens da
   pasta cujo nome casa com ele (``Corpo_BaseColor.png`` -> material ``Corpo``).

O que foi feito por dedução volta como nota, para aparecer no laudo.
"""

from __future__ import annotations

import re
from pathlib import Path

import bpy
import numpy as np

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff", ".webp", ".exr", ".dds")

# Papel da textura -> sufixos usuais no nome do arquivo.
ROLE_TOKENS = {
    "base": ("basecolor", "albedo", "diffuse", "diff", "color", "col", "bc", "d"),
    "normal": ("normal", "normalmap", "nrm", "nor", "norm", "n"),
    "roughness": ("roughness", "rough", "r"),
    "metallic": ("metallic", "metalness", "metal", "m"),
}
ROLE_LABELS = {"base": "cor", "normal": "normal", "roughness": "rugosidade", "metallic": "metálico"}
_SOCKETS = {"base": "Base Color", "roughness": "Roughness", "metallic": "Metallic"}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _tokens(stem: str) -> list[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", stem)  # BodyBaseColor -> Body Base Color
    return [t for t in re.split(r"[^a-z0-9]+", spaced.lower()) if t]


def classify(stem: str) -> tuple[str | None, str]:
    """(papel, resto do nome sem o sufixo de papel). Papel None = não deu para saber."""
    tokens = _tokens(stem)
    for size in (2, 1):  # "base color" são duas palavras
        if len(tokens) >= size:
            tail = "".join(tokens[-size:])
            for role, names in ROLE_TOKENS.items():
                if tail in names:
                    return role, "".join(tokens[:-size])
    return None, "".join(tokens)


def image_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS)


def _principled(mat):
    if mat.node_tree is None:
        return None
    return next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)


def has_base_texture(mat) -> bool:
    bsdf = _principled(mat)
    return bool(bsdf and bsdf.inputs["Base Color"].is_linked)


def used_materials() -> list:
    seen = {}
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH":
            for slot in obj.material_slots:
                if slot.material:
                    seen[slot.material.name] = slot.material
    return list(seen.values())


def relink_missing(folder: Path) -> list[str]:
    files = image_files(folder)
    by_name = {p.name.lower(): p for p in files}
    by_stem = {p.stem.lower(): p for p in files}
    notes = []
    for img in bpy.data.images:
        if img.source != "FILE" or img.packed_file:
            continue
        if img.filepath and Path(bpy.path.abspath(img.filepath)).exists():
            continue
        wanted = Path((img.filepath or img.name).replace("\\", "/")).name.lower()
        hit = by_name.get(wanted) or by_stem.get(Path(wanted).stem)
        if hit:
            img.filepath = str(hit)
            img.reload()
            notes.append(f"Textura '{hit.name}' encontrada na pasta do personagem e religada.")
    return notes


def _apply(mat, role: str, path: Path) -> bool:
    mat.use_nodes = True
    bsdf = _principled(mat)
    if bsdf is None:
        return False
    tree = mat.node_tree
    tex = tree.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(str(path), check_existing=True)
    tex.location = (bsdf.location.x - 420, bsdf.location.y - 280 * list(ROLE_TOKENS).index(role))
    if role == "normal":
        tex.image.colorspace_settings.name = "Non-Color"
        normal = tree.nodes.new("ShaderNodeNormalMap")
        normal.location = (bsdf.location.x - 190, tex.location.y)
        tree.links.new(tex.outputs["Color"], normal.inputs["Color"])
        tree.links.new(normal.outputs["Normal"], bsdf.inputs["Normal"])
        return True
    if role != "base":
        tex.image.colorspace_settings.name = "Non-Color"
    tree.links.new(tex.outputs["Color"], bsdf.inputs[_SOCKETS[role]])
    return True


def assign_by_name(folder: Path) -> tuple[list[str], list[str]]:
    """Aplica imagens soltas em materiais sem textura. Devolve (notas, imagens sem destino)."""
    in_use = {Path(bpy.path.abspath(i.filepath)).resolve() for i in bpy.data.images if i.filepath}
    loose = [p for p in image_files(folder) if p.resolve() not in in_use]
    bare = [m for m in used_materials() if not has_base_texture(m)]
    if not loose or not bare:
        return [], []

    notes: list[str] = []
    taken: set[Path] = set()
    classified = [(p, *classify(p.stem)) for p in loose]

    def give(mat, role: str, path: Path) -> None:
        if _apply(mat, role, path):
            taken.add(path)
            notes.append(f"'{path.name}' aplicada como {ROLE_LABELS[role]} no material '{mat.name}' (deduzido pelo nome).")

    for mat in bare:
        key = _norm(re.sub(r"\.\d{3}$", "", mat.name))  # sem o ".001" que o Blender acrescenta
        done: set[str] = set()
        for path, role, rest in classified:
            if path in taken or role is None or role in done:
                continue
            if len(key) >= 3 and rest and (key in rest or rest in key):
                give(mat, role, path)
                done.add(role)

    # Um único material sem textura: as imagens que sobraram só podem ser dele.
    still_bare = [m for m in bare if not has_base_texture(m)]
    if len(still_bare) == 1:
        left = [(p, role) for p, role, _ in classified if p not in taken]
        bases = [p for p, role in left if role == "base"] or ([left[0][0]] if len(left) == 1 and left[0][1] is None else [])
        if len(bases) == 1:
            give(still_bare[0], "base", bases[0])
            for role in ("normal", "roughness", "metallic"):
                same = [p for p, r in left if r == role]
                if len(same) == 1:
                    give(still_bare[0], role, same[0])

    return notes, [p.name for p in loose if p not in taken]


def _lowest_alpha(image) -> float:
    """Menor alfa da imagem, medido numa cópia reduzida (a original pode ter 4096²)."""
    if image.channels < 4 or not image.size[0]:
        return 1.0
    small = image.copy()
    try:
        if max(small.size) > 256:
            small.scale(256, 256)
        pixels = np.empty(small.size[0] * small.size[1] * 4, dtype=np.float32)
        small.pixels.foreach_get(pixels)
        return float(pixels[3::4].min())
    finally:
        bpy.data.images.remove(small)


def fix_false_transparency() -> list[str]:
    """Desliga a transparência de material cuja textura tem o canal alfa todo opaco.

    Exportadores (o do Tripo, por exemplo) gravam PNG RGBA e ligam o alfa ao material
    mesmo sem nada transparente. O material vira "transparente" e, no navegador e nas
    engines, perde a ordenação de profundidade: faces de trás aparecem por cima das da
    frente e o personagem parece falhado.
    """
    notes = []
    for mat in used_materials():
        bsdf = _principled(mat)
        if bsdf is None or not bsdf.inputs["Alpha"].is_linked:
            continue
        link = bsdf.inputs["Alpha"].links[0]
        image = getattr(link.from_node, "image", None)
        if link.from_node.type != "TEX_IMAGE" or image is None:
            continue
        if _lowest_alpha(image) >= 0.98:
            mat.node_tree.links.remove(link)
            bsdf.inputs["Alpha"].default_value = 1.0
            if hasattr(mat, "blend_method"):
                mat.blend_method = "OPAQUE"
            notes.append(f"Material '{mat.name}': a textura tem canal alfa, mas ele é todo opaco. Transparência desligada para o personagem não renderizar falhado.")
        else:
            notes.append(f"Material '{mat.name}' usa transparência de verdade (alfa da textura). Mantida como veio.")
    return notes


def link_textures(folder: Path) -> dict:
    notes = relink_missing(folder)
    assigned, unused = assign_by_name(folder)
    return {"notes": notes + assigned + fix_false_transparency(), "unused_files": unused}
